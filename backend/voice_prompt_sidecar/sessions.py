from __future__ import annotations

import queue
import threading
import time
import uuid
from collections import deque

import numpy as np

from .output_format import format_output
from .text_rules import load_text_rules
from .models import QWEN, CHUNK_SAMPLES, PARAFORMER, create_runtime, has_audio, release_memory
from .recorder import RecorderStateError
from .model_pool import ModelPool, model_key


class RecordingSession:
    """One microphone session; inference never runs in the audio callback."""
    def __init__(self, runtime, settings, recorder):
        self.id = uuid.uuid4().hex
        self.runtime = runtime
        self.settings = settings
        self.text_rules = load_text_rules() if settings.arabicNumbers else None
        self.recorder = recorder
        self.status = "recording"
        self.stop_requested = False
        self.text = ""
        self.error = None
        self.duration = 0
        self.audio = None
        self.levels = deque([0.0] * 32, maxlen=32)
        self.meter_pending = np.empty(0, dtype=np.float32)
        self.last_audio_at = time.monotonic()
        self.frames = queue.Queue(maxsize=2048)
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.last_seen = time.monotonic()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def snapshot(self):
        with self.lock:
            self.last_seen = time.monotonic()
            return dict(sessionId=self.id, status=self.status, rawText=format_output(self.text, self.settings, final=self.status == "done", rules=self.text_rules),
                        model=self.settings.model, language=self.settings.language,
                        durationMs=self.duration, error=self.error, stopRequested=self.stop_requested,
                        audioLevels=list(self.levels) if self.status == "recording" and time.monotonic() - self.last_audio_at < 0.3 else [0.0] * 32,
                        **self.recorder.diagnostics())

    def start(self):
        self.recorder.start(self.push)
        self.thread.start()

    def push(self, frame):
        # Metering is independent of model inference, including during slow ASR.
        values = np.asarray(frame, dtype=np.float32)
        self.meter_pending = np.concatenate((self.meter_pending, values))
        while len(self.meter_pending) >= 800:  # one real RMS point per 50 ms
            rms = float(np.sqrt(np.mean(self.meter_pending[:800] ** 2)))
            level = float(np.clip((20 * np.log10(max(rms, 1e-6)) + 60) / 54, 0, 1))
            with self.lock:
                self.levels.append(level)
                self.last_audio_at = time.monotonic()
            self.meter_pending = self.meter_pending[800:]
        try:
            self.frames.put_nowait(list(frame))
        except queue.Full:
            self.error = "识别处理积压过多，请停止后重试。"
            self.cancelled.set()

    def finish(self):
        with self.lock:
            if self.status != "recording" or self.stop_requested:
                raise RecorderStateError(self.error or "录音已经结束")
            self.stop_requested = True
        # Keep capturing the user's last syllable after the stop key. Cancellation
        # interrupts the grace period; inference only finalizes after capture stops.
        if self.cancelled.wait(1.5):
            raise RecorderStateError(self.error or "录音已取消")
        with self.lock:
            self.status = "transcribing"
        self.audio = self.recorder.stop()
        self.duration = self.audio.duration_ms
        # Callback has stopped, so the final marker follows every captured frame.
        self.frames.put(None, timeout=5)
        self.thread.join(timeout=180)
        if self.thread.is_alive():
            self.cancelled.set()
            raise RuntimeError("转写超时，正在释放本轮识别任务，请稍后重试。")
        if self.error:
            raise RuntimeError(self.error)
        return self.snapshot()

    def abort(self):
        self.cancelled.set()
        if self.recorder.is_recording:
            try:
                self.recorder.stop()
            except RecorderStateError:
                pass

    def _run(self):
        pending = np.empty(0, dtype=np.float32)
        cache = {}
        try:
            while True:
                if self.cancelled.is_set():
                    raise RuntimeError(self.error or "录音已取消")
                if self.status == "recording" and time.monotonic() - self.last_seen > 15:
                    raise RuntimeError("录音连接已断开，请重新开始。")
                try:
                    frame = self.frames.get(timeout=0.2)
                except queue.Empty:
                    continue
                if self.settings.model == PARAFORMER:
                    if frame is not None:
                        pending = np.concatenate((pending, np.asarray(frame, dtype=np.float32)))
                        # Keep one chunk for final=True when the recording ends on a boundary.
                        while len(pending) > CHUNK_SAMPLES:
                            text = self.runtime.stream_chunk(pending[:CHUNK_SAMPLES], cache)
                            pending = pending[CHUNK_SAMPLES:]
                            with self.lock:
                                self.text += text
                    elif self.audio and has_audio(self.audio.samples):
                        text = self.runtime.stream_chunk(pending, cache, final=True)
                        with self.lock:
                            self.text += text
                    else:
                        self.text = ""
                if frame is None:
                    if self.settings.model != PARAFORMER:
                        if self.audio and has_audio(self.audio.samples):
                            result = self.runtime.transcribe(self.audio.samples, 16000,
                                                             self.settings.language,
                                                             **({"terms": self.settings.terms} if self.settings.model == QWEN else {}))
                            self.text = result.raw_text
                        else:
                            self.text = ""
                    if self.cancelled.is_set():
                        raise RuntimeError("录音已取消")
                    with self.lock:
                        self.text = self.text.strip()
                        self.status = "done"
                    break
        except Exception as exc:
            try:
                self.abort()
            finally:
                with self.lock:
                    self.error = str(exc)
                    self.text = ""
                    self.status = "error"


class RecordingService:
    def __init__(self, recorder, runtime_factory=create_runtime):
        self.recorder = recorder
        self.runtime_factory = runtime_factory
        self.runtime = None
        self.runtime_key = None
        self.pool = ModelPool(runtime_factory)
        self.session = None
        self.control = threading.Lock()

    def prepare(self, settings, retry=False):
        with self.control:
            if self.session and (self.session.thread.is_alive() or self.recorder.is_recording):
                raise RecorderStateError("录音或转写期间不能切换模型")
            if self.runtime_key != model_key(settings):
                self.runtime = None
                self.runtime_key = None
                if self.session:
                    self.session.runtime = None
            prepared = self.pool.prepare(settings, retry=retry)
            return prepared

    def input_devices(self):
        with self.control:
            if self.session and (self.session.thread.is_alive() or self.recorder.is_recording):
                raise RecorderStateError("请等待录音和转写结束后刷新麦克风")
            return self.recorder.input_devices()

    def start(self, settings):
        with self.control:
            if self.session and (self.session.thread.is_alive() or self.recorder.is_recording):
                raise RecorderStateError("已有录音或转写正在进行")
            try:
                runtime = self.pool.ready(settings)
            except RuntimeError as exc:
                raise RecorderStateError(str(exc)) from exc
            self.runtime = runtime
            self.recorder.select_device(settings.inputDevice)
            self.runtime_key = model_key(settings)
            session = RecordingSession(self.runtime, settings, self.recorder)
            self.session = session
            session.start()
            return session.snapshot()

    def get(self, session_id):
        session = self.session
        if session is None or session.id != session_id:
            raise RecorderStateError("录音会话已失效，请重新开始")
        return session

    def finish(self, session_id):
        with self.control:
            return self.get(session_id).finish()

    def abort(self, session_id):
        with self.control:
            self.get(session_id).abort()
