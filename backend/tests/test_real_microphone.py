"""Opt-in capture lifecycle check; retains only counts, never audio or text."""
import os
import time
import pytest
from voice_prompt_sidecar.recorder import SoundDeviceAudioInput


@pytest.mark.skipif(os.getenv("FTL_REAL_MICROPHONE") != "1", reason="opt-in microphone check")
def test_prepared_microphone_first_frame_and_restart():
    audio = SoundDeviceAudioInput()
    try:
        audio.prepare()
        assert not audio._stream.active
        stream = audio._stream
        for attempt in range(2):
            count = 0
            def count_samples(frame):
                nonlocal count
                count += len(frame)
            audio.start(count_samples)
            ready = audio.diagnostics()
            assert ready["captureReady"]
            assert ready["captureStartMs"] < 3000
            time.sleep(0.2)
            audio.stop()
            diagnostics = audio.diagnostics()
            assert count > 0 and not audio._stream.active
            assert audio._stream is stream
            assert not diagnostics["captureReady"]
            assert not diagnostics["captureWarning"], diagnostics
            print({"attempt": attempt + 1, "samples": count, **diagnostics}, flush=True)
    finally:
        audio.close()


@pytest.mark.skipif(os.getenv("FTL_REAL_MICROPHONE") != "1", reason="opt-in microphone check")
def test_default_microphone_refresh_and_explicit_selection():
    audio = SoundDeviceAudioInput()
    try:
        devices = audio.input_devices()
        assert any(device["isDefault"] for device in devices)
        print({"inputDevices": [device["name"] for device in devices]}, flush=True)
        for choice in ("", *(device["id"] for device in devices), ""):
            audio.select_device(choice)
            count = 0
            def count_samples(frame):
                nonlocal count
                count += len(frame)
            audio.start(count_samples)
            assert audio.diagnostics()["captureReady"]
            audio.stop()
            assert count > 0
            print({"selection": "explicit" if choice else "default", "samples": count}, flush=True)
    finally:
        audio.close()
