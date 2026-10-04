from voice_prompt_sidecar.recorder import RecorderStateError, VoiceRecorder
from voice_prompt_sidecar.recorder import SoundDeviceAudioInput
import concurrent.futures
import sys
import threading
from types import SimpleNamespace
import numpy as np
import pytest


@pytest.fixture
def native_input(monkeypatch):
    streams = []
    class Stream:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.callback = kwargs["callback"]
            self.active = False
            self.closed = False
            self.started = threading.Event()
            streams.append(self)
        def start(self):
            self.active = True
            self.started.set()
        def emit(self, samples, **flags):
            self.callback(np.asarray(samples, dtype=np.float32).reshape(-1, 1), len(samples), None, SimpleNamespace(**flags))
        def stop(self):
            self.active = False
        def close(self):
            self.active = False
            self.closed = True
    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(InputStream=Stream))
    audio = SoundDeviceAudioInput()
    yield audio, streams
    audio.close()


def test_prepare_does_not_capture_and_start_waits_for_valid_frames(native_input):
    audio, streams = native_input
    frames = []
    audio.prepare()
    audio.prepare()
    assert len(streams) == 1 and not streams[0].active
    with concurrent.futures.ThreadPoolExecutor() as executor:
        start = executor.submit(audio.start, frames.extend)
        assert streams[0].started.wait(1)
        assert not start.done()
        streams[0].emit([0.0] * 4, input_underflow=True)
        assert not start.done() and not audio.diagnostics()["captureReady"]
        streams[0].emit([0.25] * 4)
        start.result(timeout=1)
    assert frames == [0.0] * 4 + [0.25] * 4
    assert audio.diagnostics()["captureReady"]
    assert audio.diagnostics()["captureStartMs"] is not None
    audio.stop()
    assert not streams[0].closed and not streams[0].active
    assert not audio.diagnostics()["captureReady"]
    streams[0].emit([0.5])
    assert len(frames) == 8


def test_overflow_preserves_current_samples_and_warns_and_resets_next_recording(native_input):
    audio, streams = native_input
    audio.prepare()
    for index in range(2):
        frames = []
        streams[0].started.clear()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            start = executor.submit(audio.start, frames.extend)
            assert streams[0].started.wait(1)
            streams[0].emit([0.25, 0.5], input_overflow=index == 0)
            start.result(timeout=1)
        assert frames == [0.25, 0.5]
        warning = audio.diagnostics()["captureWarning"]
        assert ("溢出 1 次" in warning) if index == 0 else warning is None
        audio.stop()
    assert len(streams) == 1


def test_invalid_samples_and_clipping_are_reported_without_corrupting_audio(native_input):
    audio, streams = native_input
    frames = []
    audio.prepare()
    with concurrent.futures.ThreadPoolExecutor() as executor:
        start = executor.submit(audio.start, frames.extend)
        assert streams[0].started.wait(1)
        streams[0].emit([float("nan"), float("inf"), 1.0, 0.25])
        start.result(timeout=1)
    assert frames == [0.0, 0.0, 1.0, 0.25]
    assert "无效" in audio.diagnostics()["captureWarning"]
    assert "削波" in audio.diagnostics()["captureWarning"]


def test_missing_first_frame_fails_and_releases_device(native_input, monkeypatch):
    audio, streams = native_input
    audio.prepare()
    monkeypatch.setattr(audio._first_frame, "wait", lambda timeout: False)
    with pytest.raises(RecorderStateError, match="有效采样"):
        audio.start(lambda frame: None)
    assert streams[0].closed
    assert audio._stream is None
    assert not audio.diagnostics()["captureReady"]


class FakeAudioInput:
    def __init__(self):
        self.started = False
        self.stopped = False

    def start(self, on_frame):
        self.started = True
        on_frame([0.1, 0.2, 0.3])

    def stop(self):
        self.stopped = True


class FailingAudioInput:
    def start(self, on_frame):
        del on_frame
        raise RuntimeError("audio input unavailable")

    def stop(self):
        raise AssertionError("stop should not be called")


def test_recorder_collects_frames_between_start_and_stop():
    audio = FakeAudioInput()
    recorder = VoiceRecorder(audio_input=audio, sample_rate=16000)

    recorder.start()
    result = recorder.stop()

    assert audio.started is True
    assert audio.stopped is True
    assert result.samples == [0.1, 0.2, 0.3]
    assert result.sample_rate == 16000
    assert result.duration_ms >= 0


def test_recorder_rejects_double_start():
    recorder = VoiceRecorder(audio_input=FakeAudioInput(), sample_rate=16000)

    recorder.start()

    try:
        recorder.start()
    except RecorderStateError as exc:
        assert "already recording" in str(exc)
    else:
        raise AssertionError("expected RecorderStateError")


def test_recorder_rolls_back_state_when_audio_input_fails_to_start():
    recorder = VoiceRecorder(audio_input=FailingAudioInput(), sample_rate=16000)

    try:
        recorder.start()
    except RuntimeError as exc:
        assert "audio input unavailable" in str(exc)
    else:
        raise AssertionError("expected audio input startup failure")

    assert recorder.is_recording is False


def test_device_refresh_closes_old_stream_and_resolves_saved_name_after_reordering(native_input, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    audio, streams = native_input
    sd = sys.modules["sounddevice"]
    devices = [dict(name="USB mic", hostapi=0, max_input_channels=1),
               dict(name="Speaker", hostapi=0, max_input_channels=0)]
    refreshes = []
    monkeypatch.setattr(sd, "_terminate", lambda: refreshes.append("stop"), raising=False)
    monkeypatch.setattr(sd, "_initialize", lambda: refreshes.append("start"), raising=False)
    monkeypatch.setattr(sd, "query_hostapis", lambda: [dict(name="Windows WASAPI", default_input_device=0)], raising=False)
    monkeypatch.setattr(sd, "query_devices", lambda: devices, raising=False)
    audio.prepare()
    listed = audio.input_devices()
    assert streams[0].closed
    assert len(listed) == 1
    devices.reverse()
    audio.select_device(listed[0]["id"])
    assert audio._device == 1
    devices.pop()
    with pytest.raises(RecorderStateError, match="所选麦克风不可用"):
        audio.select_device(listed[0]["id"])
    devices.append(dict(name="Default mic", hostapi=0, max_input_channels=1))
    devices.reverse()
    audio.select_device("")
    assert audio._device == 0
    assert refreshes == ["stop", "start"] * 4


def test_device_refresh_is_rejected_while_recording():
    recorder = VoiceRecorder(FakeAudioInput())
    recorder.start()
    with pytest.raises(RecorderStateError, match="停止录音"):
        recorder.input_devices()
    with pytest.raises(RecorderStateError, match="停止录音"):
        recorder.select_device("")
    assert recorder.is_recording
    recorder.stop()


def test_windows_lists_only_endpoints_and_accepts_legacy_selection(native_input, monkeypatch):
    import json
    monkeypatch.setattr(sys, "platform", "win32")
    audio, streams = native_input
    sd = sys.modules["sounddevice"]
    hosts = [dict(name=name, default_input_device=4 if name == "Windows WASAPI" else 0)
             for name in ("MME", "Windows DirectSound", "Windows WASAPI", "Windows WDM-KS")]
    devices = [dict(name=name, hostapi=host, max_input_channels=channels)
               for name, host, channels in [("Mapper", 0, 2), ("USB mic", 0, 1),
                   ("USB mic", 1, 1), ("Speaker", 2, 0), ("USB mic", 2, 2),
                   ("Headset", 2, 1), ("USB mic", 3, 1), ("Hidden driver", 3, 2)]]
    monkeypatch.setattr(sd, "_terminate", lambda: None, raising=False)
    monkeypatch.setattr(sd, "_initialize", lambda: None, raising=False)
    monkeypatch.setattr(sd, "query_hostapis", lambda: hosts, raising=False)
    monkeypatch.setattr(sd, "query_devices", lambda: devices, raising=False)
    monkeypatch.setattr(sd, "WasapiSettings", lambda **kwargs: kwargs, raising=False)
    listed = audio.input_devices()
    assert [item["name"] for item in listed] == ["USB mic", "Headset"]
    audio.select_device(json.dumps(["MME", "USB mic"]))
    assert audio._device == 4
    audio.prepare()
    assert streams[-1].kwargs["extra_settings"] == {"auto_convert": True}
    audio.select_device("")
    assert streams[-1].closed and audio._device == 4
    with pytest.raises(RecorderStateError, match="不可用"):
        audio.select_device(json.dumps(["Windows WDM-KS", "Hidden driver"]))
    devices.clear()
    assert audio.input_devices() == []
    with pytest.raises(RecorderStateError, match="默认麦克风"):
        audio.select_device("")
