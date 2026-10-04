from __future__ import annotations

import time
import json
import sys
import threading
from dataclasses import dataclass
from typing import Callable, Protocol, Sequence


class RecorderStateError(RuntimeError):
    pass


class AudioInput(Protocol):
    def start(self, on_frame: Callable[[Sequence[float]], None]) -> None:
        ...

    def stop(self) -> None:
        ...


@dataclass(frozen=True)
class RecordedAudio:
    samples: list[float]
    sample_rate: int
    duration_ms: int


class VoiceRecorder:
    def __init__(self, audio_input: AudioInput, sample_rate: int = 16000):
        self._audio_input = audio_input
        self._sample_rate = sample_rate
        self._samples: list[float] = []
        self._started_at: float | None = None
        self._on_frame = None
        self._control_lock = threading.RLock()

    @property
    def is_recording(self) -> bool:
        return self._started_at is not None

    def start(self, on_frame=None) -> None:
        with self._control_lock:
            self._start(on_frame)

    def prepare(self) -> None:
        with self._control_lock:
            if not self.is_recording and hasattr(self._audio_input, "prepare"):
                self._audio_input.prepare()

    def diagnostics(self) -> dict:
        if hasattr(self._audio_input, "diagnostics"):
            return self._audio_input.diagnostics()
        return {}

    def input_devices(self):
        with self._control_lock:
            if self.is_recording:
                raise RecorderStateError("请停止录音后刷新麦克风")
            return self._audio_input.input_devices()

    def select_device(self, device):
        with self._control_lock:
            if self.is_recording:
                raise RecorderStateError("请停止录音后切换麦克风")
            if hasattr(self._audio_input, "select_device"):
                self._audio_input.select_device(device)

    def _start(self, on_frame=None) -> None:
        if self.is_recording:
            raise RecorderStateError("recorder is already recording")
        self._samples = []
        self._on_frame = on_frame
        self._started_at = time.monotonic()
        try:
            self._audio_input.start(self._append_frame)
        except Exception:
            self._started_at = None
            try:
                self._audio_input.stop()
            except Exception:
                pass  # Preserve the original capture startup error.
            self._on_frame = None
            raise

    def stop(self) -> RecordedAudio:
        with self._control_lock:
            return self._stop()

    def _stop(self) -> RecordedAudio:
        if not self.is_recording:
            raise RecorderStateError("recorder is not recording")
        started_at = self._started_at
        self._started_at = None
        try:
            self._audio_input.stop()
        finally:
            # Do not retain the completed session and its model while switching.
            self._on_frame = None
        duration_ms = int((time.monotonic() - started_at) * 1000) if started_at else 0
        return RecordedAudio(
            samples=list(self._samples),
            sample_rate=self._sample_rate,
            duration_ms=max(duration_ms, 0),
        )

    def _append_frame(self, frame: Sequence[float]) -> None:
        self._samples.extend(float(sample) for sample in frame)
        if self._on_frame:
            self._on_frame(frame)


class SoundDeviceAudioInput:
    def __init__(self, sample_rate: int = 16000, channels: int = 1):
        self._sample_rate = sample_rate
        self._channels = channels
        self._stream = None
        self._on_frame = None
        self._first_frame = threading.Event()
        self._started_at = None
        self._first_frame_ms = None
        self._overflow_count = 0
        self._underflow_count = 0
        self._clipped_samples = 0
        self._sample_count = 0
        self._invalid_samples = 0
        self._device = None
        self._host_api = None

    def input_devices(self):
        import sounddevice as sd
        self.close()
        # PortAudio caches Windows endpoints. Refresh only under the recorder's
        # control lock, after closing our sole stream and while capture is idle.
        sd._terminate()
        sd._initialize()
        hosts = sd.query_hostapis()
        all_devices = sd.query_devices()
        devices = []
        for index, info in enumerate(all_devices):
            if info["max_input_channels"] < self._channels:
                continue
            host = hosts[info["hostapi"]]["name"]
            # WASAPI exposes the active Windows audio endpoints. Other APIs
            # duplicate them or expose low-level driver pins and mapper aliases.
            if sys.platform == "win32" and host != "Windows WASAPI":
                continue
            aliases = [json.dumps([hosts[item["hostapi"]]["name"], item["name"]], ensure_ascii=False)
                       for item in all_devices
                       if item["name"] == info["name"] and item["max_input_channels"] >= self._channels]
            devices.append(dict(id=json.dumps([host, info["name"]], ensure_ascii=False),
                                name=info["name"], hostApi=host, index=index, aliases=aliases,
                                isDefault=index == hosts[info["hostapi"]]["default_input_device"]))
        return devices

    def select_device(self, device):
        devices = self.input_devices()
        self._device = None
        self._host_api = None
        if device:
            matches = [item for item in devices if device in item["aliases"]]
            if len(matches) != 1:
                raise RecorderStateError("所选麦克风不可用或名称重复，请在设置中刷新并重新选择麦克风。")
            self._device = matches[0]["index"]
            self._host_api = matches[0]["hostApi"]
        elif sys.platform == "win32":
            default = next((item for item in devices if item["isDefault"]), None)
            if default is None:
                raise RecorderStateError("没有可用的系统默认麦克风，请检查 Windows 声音设置。")
            self._device = default["index"]
            self._host_api = default["hostApi"]

    def prepare(self) -> None:
        if self._stream is not None:
            return
        import sounddevice as sd
        # Open the device without starting capture. Reuse it for subsequent
        # recordings; no audio is collected while it is stopped.
        self._stream = sd.InputStream(
            extra_settings=sd.WasapiSettings(auto_convert=True) if self._host_api == "Windows WASAPI" else None,
            device=self._device,
            samplerate=self._sample_rate,
            channels=self._channels,
            dtype="float32",
            latency="low",
            callback=self._callback,
        )

    def _callback(self, indata, frames, time_info, status) -> None:
        import numpy as np
        callback = self._on_frame
        if callback is None:
            return
        self._overflow_count += int(bool(getattr(status, "input_overflow", False)))
        self._underflow_count += int(bool(getattr(status, "input_underflow", False)))
        values = indata.reshape(-1).astype("float32")
        if not len(values):
            return
        valid = np.isfinite(values)
        self._invalid_samples += int(np.count_nonzero(~valid))
        values = np.where(valid, values, 0.0)
        self._sample_count += len(values)
        self._clipped_samples += int(np.count_nonzero(np.abs(values) >= 0.999))
        # Overflow describes samples already lost by the device/driver. The
        # current buffer still contains useful audio and must not be discarded.
        callback(values.tolist())
        if not self._first_frame.is_set() and not getattr(status, "input_underflow", False) and valid.any():
            self._first_frame_ms = round((time.monotonic() - self._started_at) * 1000, 1)
            self._first_frame.set()

    def start(self, on_frame: Callable[[Sequence[float]], None]) -> None:
        self.prepare()
        self._first_frame.clear()
        self._first_frame_ms = None
        self._overflow_count = self._underflow_count = 0
        self._clipped_samples = self._sample_count = self._invalid_samples = 0
        self._on_frame = on_frame
        self._started_at = time.monotonic()
        try:
            self._stream.start()
            if not self._first_frame.wait(3):
                raise RecorderStateError("麦克风尚未送达有效采样，请检查输入设备后重试。")
        except Exception:
            self.close()
            raise

    def diagnostics(self) -> dict:
        warnings = []
        if self._overflow_count:
            warnings.append(f"音频输入溢出 {self._overflow_count} 次，可能有声音缺失")
        if self._underflow_count:
            warnings.append(f"音频输入欠载 {self._underflow_count} 次")
        if self._invalid_samples:
            warnings.append("检测到无效音频采样")
        if self._sample_count and self._clipped_samples / self._sample_count > 0.01:
            warnings.append("麦克风音量过高，出现削波失真")
        if self._on_frame is not None and self._stream is not None and not self._stream.active:
            warnings.append("麦克风采样已中断，请停止后重试")
        return dict(captureReady=self._first_frame.is_set() and self._on_frame is not None,
                    captureStartMs=self._first_frame_ms,
                    captureWarning="；".join(warnings) or None)

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
            except Exception:
                self.close()
                raise
            finally:
                self._on_frame = None

    def close(self) -> None:
        self._on_frame = None
        if self._stream is not None:
            stream, self._stream = self._stream, None
            stream.close()
