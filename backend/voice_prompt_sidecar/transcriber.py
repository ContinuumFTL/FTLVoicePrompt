from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .cleanup import clean_transcript


@dataclass(frozen=True)
class TranscriptionResult:
    raw_text: str
    language: str
    model: str


class QwenAsrRuntime:
    def __init__(
        self,
        model_name: str = "Qwen/Qwen3-ASR-1.7B",
        device: str = "cuda:0",
        dtype: str = "bfloat16",
        max_new_tokens: int = 512,
        model_factory: Callable[..., Any] | None = None,
    ):
        self._model_name = model_name
        self._device = device
        self._dtype = dtype
        self._max_new_tokens = max_new_tokens
        self._model_factory = model_factory
        self._model: Any | None = None

    def prepare(self) -> None:
        self._load_model()

    def transcribe(
        self,
        samples: Iterable[float] | str | Path,
        sample_rate: int,
        language: str = "auto",
        terms: str = "",
    ) -> TranscriptionResult:
        model = self._load_model()
        context_terms = list(dict.fromkeys(line.strip() for line in terms.splitlines() if line.strip()))
        # A recognition hint for a frequently confused word, never a replacement
        # of legitimate artwork references in the resulting transcript.
        if _normalize_language(language) == "Chinese" and "会话" not in context_terms:
            context_terms.append("会话")
        results = model.transcribe(
            audio=_normalize_audio(samples, sample_rate),
            language=_normalize_language(language),
            **({"context": "\n".join(context_terms)} if context_terms else {}),
        )
        first = _first_result(results)
        return TranscriptionResult(
            raw_text=clean_transcript(_read_text(first)),
            language=_read_language(first) or language or "auto",
            model=self._model_name,
        )

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model

        kwargs = self._model_kwargs(self._device, self._dtype)
        try:
            self._model = self._model_factory(**kwargs) if self._model_factory else _load_qwen_model(**kwargs)
        except AssertionError as exc:
            if not _is_cuda_unavailable_error(exc) or _normalize_device(self._device) == "cpu":
                raise
            fallback_kwargs = self._model_kwargs("cpu", "float32")
            self._model = (
                self._model_factory(**fallback_kwargs)
                if self._model_factory
                else _load_qwen_model(**fallback_kwargs)
            )
        return self._model

    def _model_kwargs(self, device: str, dtype: str) -> dict[str, Any]:
        resolved_device = _resolve_device(device)
        resolved_dtype = _resolve_dtype(dtype, resolved_device)
        return {
            "model_name": self._model_name,
            "dtype": resolved_dtype,
            "device_map": resolved_device,
            "max_new_tokens": self._max_new_tokens,
            "max_inference_batch_size": 1,
        }


def _normalize_device(device: str | None) -> str:
    return (device or "auto").strip().lower()


def _cuda_is_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _resolve_device(device: str | None) -> str:
    normalized = _normalize_device(device)
    if normalized == "auto":
        return "cuda:0" if _cuda_is_available() else "cpu"
    if normalized.startswith("cuda") and not _cuda_is_available():
        return "cpu"
    return normalized


def _resolve_dtype(dtype: str | None, device: str) -> str:
    normalized = (dtype or "auto").strip().lower()
    if device == "cpu":
        return "float32"
    if normalized == "auto":
        return "bfloat16"
    return normalized


def _is_cuda_unavailable_error(exc: AssertionError) -> bool:
    return "cuda" in str(exc).lower()


def _build_qwen_model_kwargs(
    model_name: str,
    dtype: str,
    device_map: str,
    max_new_tokens: int,
    max_inference_batch_size: int,
) -> dict[str, Any]:
    import torch

    dtype_value = {
        "auto": torch.bfloat16,
        "bfloat16": torch.bfloat16,
        "float16": torch.float16,
        "float32": torch.float32,
    }.get(dtype, torch.float32 if device_map == "cpu" else torch.bfloat16)

    return {
        "pretrained_model_name_or_path": model_name,
        "dtype": dtype_value,
        "device_map": device_map,
        "max_inference_batch_size": max_inference_batch_size,
        "max_new_tokens": max_new_tokens,
    }


def _load_qwen_model(
    model_name: str,
    dtype: str,
    device_map: str,
    max_new_tokens: int,
    max_inference_batch_size: int,
) -> Any:
    from .local_models import local_model_path
    model_name = local_model_path(model_name)
    from qwen_asr import Qwen3ASRModel

    return Qwen3ASRModel.from_pretrained(
        **_build_qwen_model_kwargs(
            model_name=model_name,
            dtype=dtype,
            device_map=device_map,
            max_new_tokens=max_new_tokens,
            max_inference_batch_size=max_inference_batch_size,
        )
    )


def _normalize_audio(samples: Iterable[float] | str | Path, sample_rate: int) -> Any:
    if isinstance(samples, (str, Path)):
        return str(samples)

    import numpy as np

    return (np.asarray(list(samples), dtype=np.float32), sample_rate)


def _normalize_language(language: str | None) -> str | None:
    if not language or language == "auto":
        return None
    language_map = {
        "zh": "Chinese",
        "zh-cn": "Chinese",
        "chinese": "Chinese",
        "en": "English",
        "en-us": "English",
        "english": "English",
    }
    return language_map.get(language.lower(), language)


def _first_result(results: Any) -> Any:
    if isinstance(results, list):
        if not results:
            raise ValueError("Qwen ASR returned no transcription results")
        return results[0]
    return results


def _read_text(result: Any) -> str:
    if isinstance(result, dict):
        return str(result.get("text", ""))
    return str(getattr(result, "text", ""))


def _read_language(result: Any) -> str | None:
    if isinstance(result, dict):
        language = result.get("language")
    else:
        language = getattr(result, "language", None)
    return str(language) if language else None
