import pytest
from voice_prompt_sidecar.app import SidecarConfig
from voice_prompt_sidecar.output_format import format_output

@pytest.mark.parametrize("source, expected", [
    ("你好，世界。真的吗？（测试）", "你好, 世界. 真的吗? (测试)"),
    ("十六个文件，一百零二行，二零二六年九月八日。", "16个文件, 102行, 2026年9月8日. "),
    ("百分之三点五，负十二点零五，两千零六十元。", "3.5%, -12.05, 2060元. "),
    ("一起，一并，万一，千万别，三心二意，十全十美。", "一起, 一并, 万一, 千万别, 三心二意, 十全十美. "),
    ("Vibe Coding，Harness Engineering，float16。", "Vibe Coding, Harness Engineering, float16. "),
])
def test_formats_explicit_numbers_and_punctuation_without_damaging_words(source, expected):
    assert format_output(source, SidecarConfig()) == expected

@pytest.mark.parametrize("source", ["我有十六个文件。", "增长百分之三点五。", "我们一起测试。", "千万不要删除。", "编号二零二六。"])
def test_streaming_prefixes_never_revise_emitted_text(source):
    previous = ""
    for end in range(1, len(source)+1):
        current = format_output(source[:end], SidecarConfig(), final=False)
        assert current.startswith(previous), (previous, current)
        previous = current
    assert format_output(source, SidecarConfig()).startswith(previous)

def test_format_options_can_be_disabled():
    text = "十六个，三点五。"
    assert format_output(text, SidecarConfig(englishPunctuation=False, arabicNumbers=False)) == text


@pytest.mark.parametrize("source, expected", [
    ("为什么?你好. 测试,   再试;好了!", "为什么? 你好. 测试, 再试; 好了! "),
    ("数值3.14,时间12:30,版本1.2.3。", "数值3.14, 时间12:30, 版本1.2.3. "),
    ("打开https://example.com/a?q=1&b=2。", "打开https://example.com/a?q=1&b=2. "),
    ("联系me@example.com，打开app.py。", "联系me@example.com, 打开app.py. "),
])
def test_punctuation_spaces_preserve_technical_tokens(source, expected):
    assert format_output(source, SidecarConfig()) == expected

@pytest.mark.parametrize("source", ["数值3.14,下一个。", "https://example.com/a?q=1。", "好了? 下一句. ", "Vibe Coding, Skill。", "联系me@example.com，收到。"])
def test_spacing_is_append_only_during_streaming(source):
    previous = ""
    for end in range(1, len(source)+1):
        current = format_output(source[:end], SidecarConfig(), final=False)
        assert current.startswith(previous), (source[:end], previous, current)
        previous = current
    assert format_output(source, SidecarConfig()).startswith(previous)


@pytest.mark.parametrize("source, expected", [
    ("一个，两个，三个，十二个。", "一个, 两个, 3个, 12个. "),
    ("我有1个，你有2个，二个也行。", "我有一个, 你有两个, 两个也行. "),
    ("第一个，第二个，第1个，12个，1.2个，负两个。", "第1个, 第2个, 第1个, 12个, 1.2个, -2个. "),
])
def test_one_and_two_counting_preference(source, expected):
    assert format_output(source, SidecarConfig()) == expected

@pytest.mark.parametrize("punctuation", [True, False])
@pytest.mark.parametrize("source", ["我有1个和2个", "一个两个三个十二个", "1.2个和第2个"])
def test_counting_preference_streaming_never_revises(punctuation, source):
    settings = SidecarConfig(englishPunctuation=punctuation)
    previous = ""
    for end in range(1, len(source)+1):
        current = format_output(source[:end], settings, final=False)
        assert current.startswith(previous), (previous, current)
        previous = current
    assert format_output(source, settings).startswith(previous)


def test_disabled_numbers_leave_counting_untouched():
    assert format_output("1个两个三个", SidecarConfig(arabicNumbers=False)) == "1个两个三个"


@pytest.mark.parametrize("source, expected", [
    ("一个一条一段一片，两条两段两片", "一个一条一段一片，两条两段两片"),
    ("1条2段1片2件1份2次", "一条两段一片两件一份两次"),
    ("一秒两分钟一元两米一倍", "1秒2分钟1元2米1倍"),
    ("第一条第二段第1片第2件", "第1条第2段第1片第2件"),
    ("十二条二十一条负两条百分之二", "12条21条-2条2%"),
    ("12条21片1.2段-2条+1条v1条", "12条21片1.2段-2条+1条v1条"),
    ("一起一样一边两边一共", "一起一样一边两边一共"),
])
def test_counting_and_numeric_boundaries(source, expected):
    settings = SidecarConfig(englishPunctuation=False)
    assert format_output(source, settings) == expected


@pytest.mark.parametrize("punctuation", [True, False])
@pytest.mark.parametrize("source", [
    "1条2段1片2件1份2次", "一个一条一段一片，两条两段两片",
    "一秒两分钟一元两米一倍", "第一条第二段第1片第2件",
    "十二条二十一条负两条百分之二", "12条21片1.2段-2条+1条v1条",
])
def test_new_counting_boundaries_are_append_only(source, punctuation):
    settings = SidecarConfig(englishPunctuation=punctuation)
    previous = ""
    for end in range(1, len(source) + 1):
        current = format_output(source[:end], settings, final=False)
        assert current.startswith(previous), (source[:end], previous, current)
        previous = current
    assert format_output(source, settings).startswith(previous)


@pytest.mark.parametrize("source, expected", [
    ("我想做三D模型", "我想做3D模型"),
    ("使用二D和三D，支持四D", "使用2D和3D，支持4D"),
    ("三D", "3D"),
    ("使用三d打印", "使用3d打印"),
    ("使用3D模型和一个零件", "使用3D模型和一个零件"),
    ("张三Debug", "张三Debug"),
])
@pytest.mark.parametrize("punctuation", [True, False])
def test_dimension_notation_in_chinese_and_streaming(source, expected, punctuation):
    settings = SidecarConfig(englishPunctuation=punctuation)
    assert format_output(source, settings) == format_output(expected, settings)
    previous = ""
    for end in range(1, len(source) + 1):
        current = format_output(source[:end], settings, final=False)
        assert current.startswith(previous), (source[:end], previous, current)
        previous = current
    assert format_output(source, settings).startswith(previous)


def test_disabled_numbers_preserve_chinese_dimension_notation():
    assert format_output("使用三D模型", SidecarConfig(arabicNumbers=False)) == "使用三D模型"


@pytest.mark.parametrize("source, expected", [
    ("opus五点五, 1点, 2点, 3点", "Opus5.5, 一点, 两点, 3点"),
    ("一点 两点 三点 一个 二个 三个", "一点 两点 3点 一个 两个 3个"),
    ("选三 再加五 共七种", "选3 再加5 共7种"),
    ("1点五 2点5 五点5 十二点05", "1.5 2.5 5.5 12.05"),
    ("12千元 3万5千元", "12000元 35000元"),
    ("十一点 十二点 第一点 第2点 1.2点 -2点", "11点 12点 第1点 第2点 1.2点 -2点"),
    ("opus五点五版本，1个和2个", "Opus5.5版本，一个和两个"),
    ("千万不要 三心二意 千方百计 一起 一定 两边", "千万不要 三心二意 千方百计 一起 一定 两边"),
])
@pytest.mark.parametrize("punctuation", [True, False])
def test_numeric_default_then_personal_exceptions(source, expected, punctuation):
    settings = SidecarConfig(englishPunctuation=punctuation)
    expected = format_output(expected, SidecarConfig(englishPunctuation=punctuation, arabicNumbers=False))
    assert format_output(source, settings) == expected
    previous = ""
    for end in range(1, len(source) + 1):
        current = format_output(source[:end], settings, final=False)
        assert current.startswith(previous), (source[:end], previous, current)
        previous = current
    assert expected.startswith(previous)
    assert format_output(expected, settings) == expected


def test_disabled_numeric_preferences_preserve_point_and_brand_text():
    source = "opus五点五 1点 2点 1点五"
    assert format_output(source, SidecarConfig(arabicNumbers=False)) == source
