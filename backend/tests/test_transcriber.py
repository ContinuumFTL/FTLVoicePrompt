from voice_prompt_sidecar.transcriber import QwenAsrRuntime, TranscriptionResult


class FakeQwenModel:
    def transcribe(self, audio, language=None):
        samples, sample_rate = audio
        assert sample_rate == 16000
        assert len(samples.tolist()) == 2
        assert abs(float(samples[0]) - 0.1) < 0.0001
        assert abs(float(samples[1]) - 0.2) < 0.0001
        assert sample_rate == 16000
        assert language is None
        return [type("Result", (), {"text": "  hello React  ", "language": "English"})()]


def test_qwen_runtime_normalizes_auto_language_and_cleans_text():
    runtime = QwenAsrRuntime(
        model_factory=lambda **_: FakeQwenModel(),
        model_name="Qwen/Qwen3-ASR-1.7B",
        device="cuda:0",
    )

    result = runtime.transcribe([0.1, 0.2], sample_rate=16000, language="auto")

    assert result == TranscriptionResult(
        raw_text="hello React",
        language="English",
        model="Qwen/Qwen3-ASR-1.7B",
    )


def test_qwen_runtime_maps_short_language_codes_to_qwen_names():
    class CapturingModel:
        def __init__(self):
            self.language = None

        def transcribe(self, audio, language=None, context=None):
            self.language = language
            assert context == "会话"
            return [type("Result", (), {"text": "你好", "language": "Chinese"})()]

    model = CapturingModel()
    runtime = QwenAsrRuntime(model_factory=lambda **_: model)

    runtime.transcribe([0.1], sample_rate=16000, language="zh")

    assert model.language == "Chinese"


def test_qwen_runtime_uses_cpu_when_cuda_is_not_available(monkeypatch):
    monkeypatch.setattr("voice_prompt_sidecar.transcriber._cuda_is_available", lambda: False)
    captured = {}

    class CapturingModel:
        def transcribe(self, audio, language=None):
            return [type("Result", (), {"text": "ok", "language": "English"})()]

    def factory(**kwargs):
        captured.update(kwargs)
        return CapturingModel()

    runtime = QwenAsrRuntime(model_factory=factory, device="cuda:0", dtype="bfloat16")

    runtime.transcribe([0.1], sample_rate=16000)

    assert captured["device_map"] == "cpu"
    assert captured["dtype"] == "float32"


def test_qwen_runtime_retries_cpu_when_model_loader_reports_cuda_unavailable(monkeypatch):
    import voice_prompt_sidecar.transcriber as transcriber_module

    monkeypatch.setattr(transcriber_module, "_cuda_is_available", lambda: True)
    calls = []

    class CapturingModel:
        def transcribe(self, audio, language=None):
            return [type("Result", (), {"text": "ok", "language": "English"})()]

    def factory(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise AssertionError("Torch not compiled with CUDA enabled")
        return CapturingModel()

    runtime = QwenAsrRuntime(model_factory=factory, device="auto", dtype="bfloat16")

    runtime.transcribe([0.1], sample_rate=16000)

    assert calls[-1]["device_map"] == "cpu"
    assert calls[-1]["dtype"] == "float32"


def test_terms_are_passed_as_context_without_replacing_recognition():
    class Model:
        def transcribe(self, **kwargs):
            assert kwargs["context"] == "Vibe Coding\nHarness Engineering\n会话"
            return [{"text": "web coding", "language": "Chinese"}]
    runtime = QwenAsrRuntime(model_factory=lambda **_: Model())
    result = runtime.transcribe([0.1], 16000, "zh", terms=" Vibe Coding \nHarness Engineering\nVibe Coding\n")
    assert result.raw_text == "web coding"


def test_session_hint_is_deduplicated_and_does_not_replace_artwork():
    class Model:
        def transcribe(self, **kwargs):
            assert kwargs["context"] == "会话\n绘画"
            return [{"text": "我喜欢绘画", "language": "Chinese"}]

    runtime = QwenAsrRuntime(model_factory=lambda **_: Model())
    result = runtime.transcribe([0.1], 16000, "zh", terms="会话\n绘画\n会话")
    assert result.raw_text == "我喜欢绘画"
