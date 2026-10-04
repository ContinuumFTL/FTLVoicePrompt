"""Resolve installed weights without any network requests or retry loops."""
from pathlib import Path
from .model_catalog import model_repository


def local_model_path(model: str) -> str:
    if Path(model).is_dir():
        return str(Path(model).resolve())
    try:
        if model.startswith("Qwen/"):
            from huggingface_hub import snapshot_download
            path = snapshot_download(model, local_files_only=True)
        else:
            from modelscope.hub.snapshot_download import snapshot_download
            repo = model_repository(model)
            path = snapshot_download(repo, local_files_only=True)
        if not Path(path).is_dir():
            raise FileNotFoundError(path)
        return str(Path(path).resolve())
    except Exception as exc:
        raise RuntimeError(f"未找到 {model} 的完整本地权重，请先安装模型；不会自动联网等待。") from exc
