import json
from pathlib import Path

import pytest

from voice_prompt_sidecar import manage
from voice_prompt_sidecar.model_catalog import QWEN, SENSE, PARAFORMER, model_repository


def test_qwen_download_check_rejects_missing_shards(tmp_path):
    for name in ("config.json", "preprocessor_config.json", "tokenizer_config.json", "vocab.json", "merges.txt"):
        (tmp_path / name).write_text("{}")
    (tmp_path / "model.safetensors.index.json").write_text(json.dumps({"weight_map": {"a": "first.safetensors", "b": "second.safetensors"}}))
    (tmp_path / "first.safetensors").write_bytes(b"weights")
    with pytest.raises(RuntimeError, match="second.safetensors"):
        manage.validate_weights(QWEN, tmp_path)
    (tmp_path / "second.safetensors").write_bytes(b"weights")
    assert manage.validate_weights(QWEN, tmp_path) == tmp_path


def test_offline_check_reports_missing_model_without_downloading(monkeypatch, capsys):
    def missing(model):
        raise RuntimeError("weights are missing")
    monkeypatch.setattr(manage, "local_model_path", missing)
    monkeypatch.setattr(manage, "download_model", lambda _: pytest.fail("offline check downloaded weights"))
    assert manage.main(["check", "--models", "sensevoice"]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "weights are missing"


@pytest.mark.parametrize("weight_map", [{}, None, {"a": ""}])
def test_qwen_download_check_rejects_invalid_shard_index(tmp_path, weight_map):
    (tmp_path / "model.safetensors.index.json").write_text(json.dumps({"weight_map": weight_map}))
    with pytest.raises(RuntimeError, match="invalid shard index"):
        manage.validate_weights(QWEN, tmp_path)


def test_streaming_download_uses_production_repository():
    assert model_repository(PARAFORMER) == "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online"
    assert manage.selected_models(["sensevoice", "qwen", "sensevoice"]) == [SENSE, QWEN]
    assert manage.selected_models(["all"]) == [QWEN, SENSE, PARAFORMER]


def test_missing_dependencies_are_actionable(monkeypatch):
    def missing(_):
        raise manage.metadata.PackageNotFoundError
    monkeypatch.setattr(manage.metadata, "version", missing)
    with pytest.raises(RuntimeError, match="Run pnpm run setup"):
        manage.doctor()
