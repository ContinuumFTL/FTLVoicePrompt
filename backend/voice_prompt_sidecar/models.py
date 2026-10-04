"""Local ASR runtimes. A single runtime is owned by the recording service."""
from __future__ import annotations

import gc
import re
from pathlib import Path

import numpy as np

from .transcriber import QwenAsrRuntime, TranscriptionResult, _resolve_device
from .model_catalog import QWEN, SENSE, PARAFORMER

MODEL_IDS = (QWEN, SENSE, PARAFORMER)
CHUNK_SAMPLES = 9600  # 600 ms at 16 kHz


def release_memory():
    gc.collect()
    import torch
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def has_audio(samples):
    return len(samples) >= 160 and bool(np.max(np.abs(samples)) > 0.001)


class FunAsrRuntime:
    def __init__(self, model_name, device="auto", **_):
        self.model_name = model_name
        self.device = _resolve_device(device)
        self.model = None

    def prepare(self):
        if self.model is None:
            from .local_models import local_model_path
            path = local_model_path(self.model_name)
            from funasr import AutoModel
            self.model = AutoModel(
                model=path, device=self.device,
                disable_update=True, disable_pbar=True,
            )

    def stream_chunk(self, samples, cache, final=False):
        result = self.model.generate(
            input=np.asarray(samples, dtype=np.float32), cache=cache,
            is_final=final, chunk_size=[0, 10, 5],
            encoder_chunk_look_back=4, decoder_chunk_look_back=1,
            disable_pbar=True,
        )
        return "".join(item.get("text", "") for item in result)

    def transcribe(self, samples, sample_rate=16000, language="auto"):
        self.prepare()
        if isinstance(samples, (str, Path)):
            import soundfile as sf
            samples, rate = sf.read(samples, dtype="float32")
            if rate != sample_rate:
                import librosa
                samples = librosa.resample(samples, orig_sr=rate, target_sr=sample_rate)
        samples = np.asarray(samples, dtype=np.float32)
        if not has_audio(samples):
            return TranscriptionResult("", language, self.model_name)
        if self.model_name == PARAFORMER:
            cache = {}
            parts = []
            for offset in range(0, len(samples), CHUNK_SAMPLES):
                parts.append(self.stream_chunk(samples[offset:offset + CHUNK_SAMPLES], cache,
                                               offset + CHUNK_SAMPLES >= len(samples)))
            text = "".join(parts)
        else:
            results = self.model.generate(input=samples, language=language, use_itn=True,
                                          batch_size_s=60, disable_pbar=True)
            text = "".join(re.sub(r"<\|[^|]*\|>", "", item.get("text", "")) for item in results)
        return TranscriptionResult(text.strip(), language, self.model_name)


def create_runtime(model, device="auto", dtype="auto", **_):
    if model not in MODEL_IDS:
        raise ValueError(f"不支持的语音模型：{model}")
    if model == QWEN:
        return QwenAsrRuntime(model_name=model, device=device, dtype=dtype)
    return FunAsrRuntime(model, device)
