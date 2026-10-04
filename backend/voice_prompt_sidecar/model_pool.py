"""Load only the selected model in the background, releasing the previous one."""
import threading
import time

from .models import QWEN, create_runtime, release_memory


def model_key(settings):
    dtype = settings.dtype
    if settings.model != QWEN or settings.device == "cpu":
        dtype = "float32"
    elif dtype == "auto":
        dtype = "bfloat16"
    # In this app both auto and cuda:0 resolve to GPU 0, falling back to CPU
    # when CUDA is unavailable. They must share the same prepared instance.
    device = "auto" if settings.device == "cuda:0" else settings.device
    return settings.model, device, dtype


class ModelPool:
    def __init__(self, factory=create_runtime):
        self.factory = factory
        self.entries = {}
        self.pending = []
        self.condition = threading.Condition()
        self.worker = None

    def prepare(self, settings, retry=False):
        with self.condition:
            key = model_key(settings)
            # A loader already in progress cannot be interrupted safely. Drop
            # obsolete queued choices and load only the latest selection next.
            self.pending.clear()
            for old in list(self.entries):
                if old != key and self.entries[old]["status"] == "queued":
                    del self.entries[old]
            entry = self.entries.get(key)
            if entry is None or (retry and entry["status"] == "error"):
                entry = dict(status="queued", error=None, runtime=None, started=None)
                self.entries[key] = entry
            if entry["status"] == "queued":
                self.pending.append((key, settings))
            if self.worker is None or not self.worker.is_alive():
                self.worker = threading.Thread(target=self._load, daemon=True)
                self.worker.start()
            self.condition.notify_all()
        return self.snapshot(settings)

    def snapshot(self, settings):
        with self.condition:
            entry = self.entries.get(model_key(settings), {})
            elapsed = time.monotonic() - entry["started"] if entry.get("started") else 0
            return {"models": [dict(model=settings.model, status=entry.get("status", "queued"),
                                    error=entry.get("error"), elapsedSeconds=round(elapsed, 1))],
                    "selected": settings.model}

    def ready(self, settings):
        with self.condition:
            entry = self.entries.get(model_key(settings))
            if not entry or entry["status"] != "ready":
                raise RuntimeError((entry or {}).get("error") or "模型尚未就绪，请等待后台准备完成后再录音。")
            return entry["runtime"]

    def _load(self):
        while True:
            with self.condition:
                while not self.pending:
                    self.condition.wait()
                key, settings = self.pending.pop(0)
                entry = self.entries[key]
                entry.update(status="loading", started=time.monotonic())
                # Release every previous model before allocating the new one.
                obsolete = [old for old in self.entries if old != key
                            and self.entries[old]["status"] in ("ready", "error")]
                for old in obsolete:
                    del self.entries[old]
            try:
                if obsolete:
                    release_memory()
                runtime = self.factory(**settings.model_dump())
                runtime.prepare()
                with self.condition:
                    entry.update(status="ready", runtime=runtime, error=None)
            except Exception as exc:
                with self.condition:
                    entry.update(status="error", runtime=None, error=str(exc))
            finally:
                runtime = None
