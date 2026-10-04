import time

import pytest
from fastapi.testclient import TestClient

from voice_prompt_sidecar.app import SidecarConfig, create_app
from voice_prompt_sidecar.models import PARAFORMER, QWEN, SENSE, CHUNK_SAMPLES
from voice_prompt_sidecar.recorder import VoiceRecorder
from voice_prompt_sidecar.sessions import RecordingService
from voice_prompt_sidecar.transcriber import TranscriptionResult


class Input:
    def start(self, callback):
        self.callback = callback
        self.stopped = False

    def stop(self):
        self.stopped = True


class Runtime:
    def __init__(self, model):
        self.model = model
        self.chunks = []
        self.transcribed_lengths = []

    def prepare(self):
        pass

    def stream_chunk(self, samples, cache, final=False):
        cache["count"] = cache.get("count", 0) + 1
        self.chunks.append((len(samples), final, cache["count"]))
        return "尾" if final else "字"

    def transcribe(self, samples, sample_rate, language, **kwargs):
        self.transcribed_lengths.append(len(samples))
        return TranscriptionResult(self.model, language, self.model)


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr("voice_prompt_sidecar.sessions.release_memory", lambda: None)
    monkeypatch.setattr("voice_prompt_sidecar.model_pool.release_memory", lambda: None)
    audio = Input()
    return RecordingService(VoiceRecorder(audio), lambda model, **_: Runtime(model)), audio


def wait_for(predicate):
    deadline = time.monotonic() + 3
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(0.01)


def ready_start(backend, settings):
    backend.prepare(settings)
    wait_for(lambda: any(item["model"] == settings.model and item["status"] in ("ready", "error")
                         for item in backend.pool.snapshot(settings)["models"]))
    return backend.start(settings)


def test_streams_before_stop_flushes_tail_and_resets_cache(service):
    backend, audio = service
    for _ in range(2):
        started = ready_start(backend, SidecarConfig(model=PARAFORMER))
        audio.callback([0.1] * (CHUNK_SAMPLES * 2 + 17))
        wait_for(lambda: backend.get(started["sessionId"]).snapshot()["rawText"] == "字字")
        result = backend.finish(started["sessionId"])
        assert result["rawText"] == "字字尾"
        assert result["status"] == "done"
        assert backend.runtime.chunks[-3:] == [(9600, False, 1), (9600, False, 2), (17, True, 3)]
        assert audio.stopped
        assert backend.recorder._on_frame is None


def test_exact_chunk_boundary_and_silence(service):
    backend, audio = service
    for samples, expected in [([0.1] * 19200, "字尾"), ([0.0] * 19000, "")]:
        result = ready_start(backend, SidecarConfig(model=PARAFORMER))
        audio.callback(samples)
        assert backend.finish(result["sessionId"])["rawText"] == expected


def test_api_switches_models_rejects_busy_and_stale_requests(service):
    backend, audio = service
    client = TestClient(create_app(service=backend))
    previous = "stale"
    for model in (QWEN, SENSE, PARAFORMER, QWEN):
        config = SidecarConfig(model=model)
        backend.prepare(config)
        wait_for(lambda: all(item["status"] == "ready" for item in backend.pool.snapshot(config)["models"]))
        started = client.post("/recording/start", json={"model": model}).json()
        assert client.post("/recording/start", json={"model": SENSE}).status_code == 409
        assert client.post("/recording/stop", json={"sessionId": previous}).status_code == 409
        audio.callback([0.1] * 1000)
        result = client.post("/recording/stop", json={"sessionId": started["sessionId"]})
        assert result.status_code == 200
        assert result.json()["model"] == model
        assert result.json()["status"] == "done"
        previous = started["sessionId"]
    assert client.post("/recording/start", json={"model": "unknown"}).status_code == 422


def test_stream_failure_stops_capture_and_can_retry(service):
    backend, audio = service
    started = ready_start(backend, SidecarConfig(model=PARAFORMER))
    def fail(*args, **kwargs):
        raise RuntimeError("inference failed")
    backend.runtime.stream_chunk = fail
    audio.callback([0.1] * 10000)
    wait_for(lambda: backend.get(started["sessionId"]).snapshot()["status"] == "error")
    assert audio.stopped
    assert backend.get(started["sessionId"]).snapshot()["rawText"] == ""
    started = ready_start(backend, SidecarConfig(model=SENSE))
    audio.callback([0.1] * 1000)
    assert backend.finish(started["sessionId"])["status"] == "done"


def test_lost_client_stops_microphone(service):
    backend, audio = service
    started = ready_start(backend, SidecarConfig(model=SENSE))
    backend.get(started["sessionId"]).last_seen -= 20
    wait_for(lambda: backend.session.status == "error")
    assert audio.stopped


def test_model_preparation_failure_does_not_start_microphone_and_allows_retry(service):
    backend, audio = service
    good_factory = backend.pool.factory
    def fail(**kwargs):
        raise RuntimeError("model unavailable")
    backend.pool.factory = fail
    with pytest.raises(Exception, match="model unavailable"):
        ready_start(backend, SidecarConfig(model=SENSE))
    assert not backend.recorder.is_recording
    backend.pool.factory = good_factory
    backend.pool.prepare(SidecarConfig(model=SENSE), retry=True)
    started = ready_start(backend, SidecarConfig(model=SENSE))
    audio.callback([0.1] * 1000)
    assert backend.finish(started["sessionId"])["status"] == "done"


def test_abort_does_not_keep_partial_result(service):
    backend, audio = service
    started = ready_start(backend, SidecarConfig(model=PARAFORMER))
    audio.callback([0.1] * 10000)
    wait_for(lambda: bool(backend.session.text))
    backend.abort(started["sessionId"])
    wait_for(lambda: backend.session.status == "error")
    assert audio.stopped
    assert backend.session.snapshot()["rawText"] == ""


def test_meter_tracks_real_samples_independently_of_recognition(service):
    backend, audio = service
    started = ready_start(backend, SidecarConfig(model=SENSE))
    session = backend.get(started["sessionId"])
    audio.callback([0.0] * 1600)
    assert max(session.snapshot()["audioLevels"]) == 0
    audio.callback([0.1] * 1600)
    assert session.snapshot()["audioLevels"][-1] > 0.7
    assert session.snapshot()["rawText"] == ""
    audio.callback([0.0] * (800 * 32))
    assert max(session.snapshot()["audioLevels"]) == 0
    backend.finish(started["sessionId"])
    assert max(session.snapshot()["audioLevels"]) == 0


@pytest.mark.parametrize("model", [QWEN, SENSE])
def test_offline_models_wait_for_stop_and_transcribe_the_entire_recording(service, model):
    backend, audio = service
    started = ready_start(backend, SidecarConfig(model=model))
    audio.callback([0.1] * 96000)  # Exceeds the removed five-second split.
    audio.callback([0.0] * 8000)
    wait_for(lambda: backend.session.frames.empty())
    assert backend.session.snapshot()["rawText"] == ""
    assert backend.runtime.transcribed_lengths == []
    assert backend.session.status == "recording"
    audio.callback([0.1] * 1000)
    result = backend.finish(started["sessionId"])
    assert result["rawText"] == model
    assert backend.runtime.transcribed_lengths == [105000]
    assert result["status"] == "done"


@pytest.mark.parametrize("model", [QWEN, SENSE, PARAFORMER])
def test_stop_keeps_capturing_tail_before_finalizing(service, model):
    from concurrent.futures import ThreadPoolExecutor
    backend, audio = service
    started = ready_start(backend, SidecarConfig(model=model))
    session = backend.get(started["sessionId"])
    audio.callback([0.1] * 1000)
    with ThreadPoolExecutor() as executor:
        before = time.monotonic()
        result = executor.submit(backend.finish, session.id)
        wait_for(lambda: session.snapshot()["stopRequested"])
        assert session.snapshot()["status"] == "recording"
        assert not audio.stopped
        time.sleep(0.15)
        audio.callback([0.2] * 1600)
        assert session.snapshot()["audioLevels"][-1] > 0
        assert not result.done()
        final = result.result(timeout=5)
    assert time.monotonic() - before >= 1.5
    assert audio.stopped
    assert final["status"] == "done"
    assert len(session.audio.samples) == 2600
    if model == PARAFORMER:
        assert backend.runtime.chunks == [(2600, True, 1)]
    else:
        assert backend.runtime.transcribed_lengths == [2600]
