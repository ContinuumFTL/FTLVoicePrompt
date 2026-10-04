import pytest

from voice_prompt_sidecar.app import SidecarConfig
from voice_prompt_sidecar.output_format import format_output
from voice_prompt_sidecar.sessions import RecordingSession
from voice_prompt_sidecar.text_rules import load_text_rules


@pytest.mark.parametrize("punctuation", [True, False])
@pytest.mark.parametrize("source, expected", [
    ("写1些规则，1看2看，看1看", "写一些规则，一看二看，看一看"),
    ("瞧1瞧，看1看，用1用，使1使，钓1钓", "瞧一瞧，看一看，用一用，使一使，钓一钓"),
    ("瞧一瞧 看一看 用一用 使一使 钓一钓", "瞧一瞧 看一看 用一用 使一使 钓一钓"),
    ("一些 一看 二看 两看 一会儿", "一些 一看 二看 二看 一会儿"),
    ("1起1样1直1定1下1边2边", "一起一样一直一定一下一边两边"),
    ("第1个 11个 21些 1.2个 -2个 +1个 v1个", "第1个 11个 21些 1.2个 -2个 +1个 v1个"),
])
def test_common_phrases_and_streaming(source, expected, punctuation):
    settings = SidecarConfig(englishPunctuation=punctuation)
    rules = load_text_rules()
    expected = format_output(expected, SidecarConfig(englishPunctuation=punctuation, arabicNumbers=False))
    assert format_output(source, settings, rules=rules) == expected
    previous = ""
    for end in range(1, len(source) + 1):
        current = format_output(source[:end], settings, final=False, rules=rules)
        assert current.startswith(previous), (source[:end], previous, current)
        previous = current
    assert expected.startswith(previous)


def test_file_edit_and_removal_are_authoritative(tmp_path, monkeypatch):
    path = tmp_path / "rules.env"
    monkeypatch.setenv("FTL_VOICE_PROMPT_RULES_FILE", str(path))
    path.write_text('REPLACE_001="1些=>一些"\nCASE_001="opus=>Opus"\nKEEP_001="一起"\n', encoding="utf-8-sig")
    settings = SidecarConfig()
    assert format_output("1些 opus 一起", settings) == "一些 Opus 一起"
    path.write_text('REPLACE_001="1些=>少量"\n', encoding="utf-8")
    assert format_output("1些 opus 一起", settings) == "少量 opus 1起"
    path.write_text("# no rules\n", encoding="utf-8")
    assert format_output("1些 1个 opus", settings) == "1些 1个 opus"


def test_longest_replacement_streams_without_cascading(tmp_path):
    path = tmp_path / "rules.env"
    path.write_text('REPLACE_001="1些=>2些"\nREPLACE_002="1些什么=>什么"\nREPLACE_003="2些=>少量"\n', encoding="utf-8")
    rules = load_text_rules(path)
    settings = SidecarConfig()
    assert format_output("1些", settings, rules=rules) == "2些"
    source = "1些什么东西"
    previous = ""
    for end in range(1, len(source) + 1):
        current = format_output(source[:end], settings, final=False, rules=rules)
        assert current.startswith(previous), (source[:end], previous, current)
        previous = current
    assert format_output(source, settings, rules=rules) == "什么东西"


def test_recording_freezes_rules_and_next_recording_reloads(tmp_path, monkeypatch):
    class Recorder:
        def diagnostics(self):
            return {}
    path = tmp_path / "rules.env"
    monkeypatch.setenv("FTL_VOICE_PROMPT_RULES_FILE", str(path))
    path.write_text('REPLACE_001="1些=>一些"\n', encoding="utf-8")
    first = RecordingSession(None, SidecarConfig(), Recorder())
    first.text = "1些内容"
    assert first.snapshot()["rawText"] == "一些内容"
    path.write_text('REPLACE_001="1些=>少量"\n', encoding="utf-8")
    assert first.snapshot()["rawText"] == "一些内容"
    first.status = "done"
    assert first.snapshot()["rawText"] == "一些内容"
    second = RecordingSession(None, SidecarConfig(), Recorder())
    second.text = "1些内容"
    assert second.snapshot()["rawText"] == "少量内容"


@pytest.mark.parametrize("body", [
    'REPLACE_001=1些=>一些',
    'REPLACE_001="1些"',
    'REPLACE_001="1些=>"',
    'REPLACE_001="1些=>一些"\nREPLACE_001="2些=>两些"',
    'REPLACE_001="1些=>一些"\nREPLACE_002="1些=>少量"',
    'REPLACE_001="[12]个=>两个"',
    'CASE_001="opus=>Opus"\nCASE_002="OPUS=>OPUS"',
    'OTHER_001="unknown"',
])
def test_invalid_file_reports_location(tmp_path, body):
    path = tmp_path / "bad.env"
    path.write_text("# heading\n" + body, encoding="utf-8")
    with pytest.raises(ValueError, match=r"bad\.env:[23]:"):
        load_text_rules(path)


def test_missing_file_errors_but_disabled_preferences_do_not_read_it(tmp_path, monkeypatch):
    path = tmp_path / "missing.env"
    monkeypatch.setenv("FTL_VOICE_PROMPT_RULES_FILE", str(path))
    with pytest.raises(ValueError, match="missing.env"):
        format_output("1些", SidecarConfig())
    assert format_output("1些", SidecarConfig(arabicNumbers=False)) == "1些"


def test_live_formatter_preview_uses_external_rules_without_recording(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from voice_prompt_sidecar.app import create_app
    path = tmp_path / "rules.env"
    path.write_text('REPLACE_001="1看=>一看"\n', encoding="utf-8")
    monkeypatch.setenv("FTL_VOICE_PROMPT_RULES_FILE", str(path))
    # No audio service methods are needed for this diagnostic.
    client = TestClient(create_app(service=object()))
    health = client.get("/health").json()
    assert health["protocol"] == 12
    result = client.post("/format/preview", json={"text": "看1看"}).json()
    assert result["text"] == "看一看"
    assert result["pid"] == health["pid"]
    assert result["rulesFile"] == str(path.resolve())
    assert result["arabicNumbers"] is True
    assert client.post("/format/preview", json={"text": "看1看", "settings": {"arabicNumbers": False}}).json()["text"] == "看1看"
