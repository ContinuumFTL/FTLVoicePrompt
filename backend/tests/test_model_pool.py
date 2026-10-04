import threading
import time
import weakref

from voice_prompt_sidecar.app import SidecarConfig
from voice_prompt_sidecar.model_pool import ModelPool
from voice_prompt_sidecar.models import QWEN, SENSE, PARAFORMER


def wait_ready(pool, settings):
    deadline = time.monotonic() + 3
    while not all(item["status"] == "ready" for item in pool.snapshot(settings)["models"]):
        assert time.monotonic() < deadline
        time.sleep(.01)


def test_only_selected_model_loads_and_previous_model_is_released(monkeypatch):
    # This unit test uses fake runtimes: do not import torch and initialize the
    # real CUDA runtime inside its three-second background loading deadline.
    releases = []
    monkeypatch.setattr("voice_prompt_sidecar.model_pool.release_memory", lambda: releases.append(True))
    gate = threading.Event()
    loaded = []
    class Runtime:
        def __init__(self, model):
            self.model = model
        def prepare(self):
            assert gate.wait(3)
            loaded.append(self.model)
    pool = ModelPool(lambda model, **_: Runtime(model))
    config = SidecarConfig(model=SENSE)
    started = time.monotonic()
    pool.prepare(config)
    assert time.monotonic() - started < .2
    assert not loaded
    gate.set()
    wait_ready(pool, config)
    assert loaded == [SENSE]
    original = weakref.ref(pool.ready(config))
    pool.prepare(config)
    assert pool.ready(config) is original()
    for model in (QWEN, PARAFORMER, SENSE):
        settings = config.model_copy(update={"model": model})
        pool.prepare(settings)
        wait_ready(pool, settings)
        assert len(pool.entries) == 1
    assert original() is None
    assert loaded == [SENSE, QWEN, PARAFORMER, SENSE]
    assert len(releases) == 3


def test_switch_during_load_skips_obsolete_queued_model(monkeypatch):
    releases = []
    monkeypatch.setattr("voice_prompt_sidecar.model_pool.release_memory", lambda: releases.append(True))
    gate = threading.Event()
    loading = threading.Event()
    loaded = []
    class Runtime:
        def __init__(self, model): self.model = model
        def prepare(self):
            loaded.append(self.model)
            if self.model == QWEN:
                loading.set()
                assert gate.wait(3)
    pool = ModelPool(lambda model, **_: Runtime(model))
    pool.prepare(SidecarConfig(model=QWEN))
    assert loading.wait(3)
    pool.prepare(SidecarConfig(model=SENSE))
    pool.prepare(SidecarConfig(model=PARAFORMER))
    gate.set()
    wait_ready(pool, SidecarConfig(model=PARAFORMER))
    assert loaded == [QWEN, PARAFORMER]
    assert len(pool.entries) == 1
    assert len(releases) == 1


def test_precision_alias_does_not_reload_qwen():
    class Runtime:
        def prepare(self):
            pass
    pool = ModelPool(lambda **_: Runtime())
    config = SidecarConfig(model=QWEN, dtype="bfloat16")
    pool.prepare(config)
    wait_ready(pool, config)
    assert pool.ready(config) is pool.ready(config.model_copy(update={"dtype": "auto"}))
    assert pool.ready(config) is pool.ready(config.model_copy(update={"device": "cuda:0"}))


def test_missing_local_cache_fails_without_downloading(monkeypatch):
    from voice_prompt_sidecar.local_models import local_model_path
    import huggingface_hub
    import pytest
    def missing(model, **kwargs):
        assert kwargs == {"local_files_only": True}
        raise FileNotFoundError(model)
    monkeypatch.setattr(huggingface_hub, "snapshot_download", missing)
    with pytest.raises(RuntimeError, match="不会自动联网等待"):
        local_model_path(QWEN)
