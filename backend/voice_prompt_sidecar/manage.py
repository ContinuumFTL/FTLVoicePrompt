"""Explicit environment/model preparation. No microphone or desktop input."""
from __future__ import annotations

import argparse
import contextlib
from importlib import metadata
import json
import os
from pathlib import Path
import sys
import time

from .local_models import local_model_path
from .model_catalog import QWEN, SENSE, PARAFORMER, model_repository

ALIASES = {"qwen": QWEN, "sensevoice": SENSE, "paraformer": PARAFORMER}
PACKAGES = ("fastapi", "numpy", "pydantic", "qwen-asr", "funasr", "torch", "torchaudio",
            "sounddevice", "soundfile", "uvicorn", "huggingface_hub", "modelscope")


def selected_models(names):
    return list(dict.fromkeys(ALIASES.values() if "all" in names else (ALIASES[name] for name in names)))


def validate_weights(model, path):
    root = Path(path)
    if model == QWEN:
        required = ["config.json", "preprocessor_config.json", "tokenizer_config.json", "vocab.json", "merges.txt"]
        index = root / "model.safetensors.index.json"
        if index.is_file():
            weight_map = json.loads(index.read_text(encoding="utf-8")).get("weight_map")
            if not isinstance(weight_map, dict) or not weight_map or not all(
                isinstance(name, str) and name.endswith(".safetensors")
                for name in weight_map.values()
            ):
                raise RuntimeError(f"Incomplete weights for {model}: invalid shard index. Run the download command again.")
            required += list(set(weight_map.values()))
        else:
            required.append("model.safetensors")
    else:
        required = ["model.pt", "config.yaml", "am.mvn", "tokens.json"]
    missing = [name for name in required if not (root / name).is_file() or (root / name).stat().st_size == 0]
    if missing:
        raise RuntimeError(f"Incomplete weights for {model}: {', '.join(missing)}. Run the download command again.")
    return root


def download_model(model):
    # Network access is confined to this explicit command; ordinary app loading stays offline.
    if model == QWEN:
        from huggingface_hub import snapshot_download
        path = snapshot_download(model)
        source = model
        revision = Path(path).name
    else:
        from modelscope.hub.snapshot_download import snapshot_download
        source = model_repository(model)
        path = snapshot_download(source)
        revision = None  # ModelScope's cache directory is not a commit identifier.
    validate_weights(model, path)
    return {"model": model, "source": source, "revision": revision, "path": str(Path(path).resolve())}


def doctor(runtime=False, require_cuda=False):
    versions, missing = {}, []
    for package in PACKAGES:
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            missing.append(package)
    if missing:
        raise RuntimeError(f"Missing Python dependencies: {', '.join(missing)}. Run pnpm run setup.")
    from .text_rules import load_text_rules
    load_text_rules()
    report = {"python": sys.version.split()[0], "packages": versions, "rules": "valid"}
    if runtime or require_cuda:
        import torch
        import torchaudio
        import sounddevice
        import soundfile
        from funasr import AutoModel
        from qwen_asr import Qwen3ASRModel
        report["cudaAvailable"] = bool(torch.cuda.is_available())
        if require_cuda and not report["cudaAvailable"]:
            raise RuntimeError("CUDA is unavailable. Check your NVIDIA driver and PyTorch CUDA installation, or use -Device cpu.")
    return report


def smoke(model, audio, device):
    from .models import create_runtime, release_memory, _resolve_device
    validate_weights(model, local_model_path(model))
    resolved = _resolve_device(device)
    if device != "auto" and resolved != device:
        raise RuntimeError(f"Requested {device}, but only {resolved} is available.")
    path = Path(audio).resolve()
    if not path.is_file():
        raise RuntimeError(f"Audio file not found: {path}")
    before = time.perf_counter()
    runtime = create_runtime(model, device=device, dtype="float32" if resolved == "cpu" else "auto")
    try:
        result = runtime.transcribe(path, 16000, "zh")
        if not result.raw_text.strip():
            raise RuntimeError("The model returned an empty transcript for the supplied sample.")
        return {"model": model, "device": resolved, "characters": len(result.raw_text),
                "elapsedSeconds": round(time.perf_counter() - before, 3), "includesModelLoad": True}
    finally:
        del runtime
        release_memory()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    diagnosis = commands.add_parser("doctor", help="Check dependencies/rules without recording or downloading")
    diagnosis.add_argument("--runtime", action="store_true")
    diagnosis.add_argument("--require-cuda", action="store_true")
    for name in ("download", "check"):
        command = commands.add_parser(name, help="Download weights explicitly" if name == "download" else "Inspect existing weights offline")
        command.add_argument("--models", nargs="+", choices=[*ALIASES, "all"], default=["qwen"])
    test = commands.add_parser("smoke", help="Transcribe a supplied public/test audio file; never opens a microphone")
    test.add_argument("--model", choices=ALIASES, default="sensevoice")
    test.add_argument("--device", choices=["auto", "cpu", "cuda:0"], default="cpu")
    test.add_argument("--audio", required=True)
    args = parser.parse_args(argv)
    try:
        with contextlib.redirect_stdout(sys.stderr):
            if args.command == "doctor":
                result = doctor(args.runtime, args.require_cuda)
            elif args.command == "download":
                # Do not silently inherit the app's offline environment for explicit preparation.
                os.environ.pop("HF_HUB_OFFLINE", None)
                os.environ.pop("TRANSFORMERS_OFFLINE", None)
                result = [download_model(model) for model in selected_models(args.models)]
                record = Path(__file__).resolve().parents[2] / ".data" / "model-downloads.json"
                record.parent.mkdir(parents=True, exist_ok=True)
                record.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                os.environ["HF_HUB_OFFLINE"] = "1"
                os.environ["TRANSFORMERS_OFFLINE"] = "1"
                if args.command == "check":
                    result = [{"model": model, "path": str(validate_weights(model, local_model_path(model)))}
                              for model in selected_models(args.models)]
                else:
                    result = smoke(ALIASES[args.model], args.audio, args.device)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
