"""Opt-in local weight preparation and real-audio session integration test.

Run with FTL_REAL_MODELS=1. Downloads official weights and a public FunASR sample;
uses the normal recording service with sample frames instead of the microphone.
"""
import os
import time

import pytest

pytestmark = pytest.mark.skipif(os.getenv("FTL_REAL_MODELS") != "1", reason="opt-in real model test")


def test_real_models_and_streaming(tmp_path):
    import httpx
    import numpy as np
    import soundfile as sf
    from fastapi.testclient import TestClient
    from voice_prompt_sidecar.app import create_app
    from voice_prompt_sidecar.models import QWEN, SENSE, PARAFORMER
    from voice_prompt_sidecar.recorder import VoiceRecorder
    from voice_prompt_sidecar.sessions import RecordingService

    url = "https://isv-data.oss-cn-hangzhou.aliyuncs.com/ics/MaaS/ASR/test_audio/asr_example_zh.wav"
    response = httpx.get(url, timeout=60)
    response.raise_for_status()
    path = tmp_path / "public-sample.wav"
    path.write_bytes(response.content)
    samples, rate = sf.read(path, dtype="float32")
    assert rate == 16000 and samples.ndim == 1

    class AudioInput:
        def start(self, callback):
            self.callback = callback
        def stop(self):
            pass

    audio = AudioInput()
    backend = RecordingService(VoiceRecorder(audio))
    client = TestClient(create_app(service=backend))
    for model in (SENSE, PARAFORMER, PARAFORMER, QWEN, SENSE, QWEN):
        before = time.monotonic()
        config = {"model": model, "device": "auto"}
        deadline = time.monotonic() + 90
        while True:
            state = client.post("/models/prepare", json=config).json()
            selected = next(item for item in state["models"] if item["model"] == model)
            assert selected["status"] != "error", selected
            if selected["status"] == "ready":
                break
            assert time.monotonic() < deadline
            time.sleep(0.1)
        response = client.post("/recording/start", json={"model": model, "device": "auto"})
        assert response.status_code == 200, response.text
        session = response.json()["sessionId"]
        prepared = time.monotonic()
        partial = ""
        for offset in range(0, len(samples), 9600):
            audio.callback(samples[offset:offset + 9600].tolist())
            if model == PARAFORMER:
                time.sleep(0.1)
                partial = client.get(f"/recording/status/{session}").json()["rawText"] or partial
        if model == PARAFORMER:
            deadline = time.monotonic() + 15
            while not partial and time.monotonic() < deadline:
                time.sleep(0.1)
                partial = client.get(f"/recording/status/{session}").json()["rawText"]
            assert partial, "No streaming text before stop"
        else:
            assert client.get(f"/recording/status/{session}").json()["rawText"] == ""
        stopped = time.monotonic()
        result = client.post("/recording/stop", json={"sessionId": session})
        assert result.status_code == 200, result.text
        result = result.json()
        assert result["model"] == model and result["status"] == "done"
        assert len(result["rawText"]) > 5
        print({"model": model, "prepare_seconds": round(prepared-before, 2),
               "finish_seconds": round(time.monotonic()-stopped, 2),
               "partial": partial, "text": result["rawText"]}, flush=True)
