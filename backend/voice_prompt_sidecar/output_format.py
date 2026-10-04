"""Numeric display preferences; never rewrite already emitted streaming text."""
import re

from .text_rules import hold_pending, load_text_rules

DIGITS = dict(zip("零〇一二两三四五六七八九", [0, 0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9]))
DIGITS.update({str(n): n for n in range(10)})
SMALL = {"十": 10, "百": 100, "千": 1000}
NUMBER = r"[0-9零〇一二两三四五六七八九十百千万亿]+"
PATTERN = re.compile(r"(百分之)?(负?" + NUMBER + r"(?:[点.][0-9零〇一二三四五六七八九]+)?)")
PUNCTUATION = str.maketrans({"，": ",", "。": ".", "！": "!", "？": "?", "；": ";", "：": ":", "、": ",", "（": "(", "）": ")", "【": "[", "】": "]", "“": '\"', "”": '\"', "‘": "'", "’": "'", "《": "<", "》": ">", "…": "...", "—": "-", "　": " "})


def integer(text):
    if all(c in DIGITS for c in text):
        return "".join(str(DIGITS[c]) for c in text)
    # Large units split recursively, supporting e.g. 一亿两千万.
    for unit, scale in [("亿", 100000000), ("万", 10000)]:
        if unit in text:
            left, right = text.split(unit, 1)
            return str(int(integer(left or "一")) * scale + (int(integer(right)) if right else 0))
    total = digit = 0
    for c in text:
        if c in DIGITS:
            digit = digit * 10 + DIGITS[c]
        else:
            total += (digit or 1) * SMALL[c]
            digit = 0
    return str(total + digit)


def space_punctuation(text):
    # Protect complete URL/email tokens, including their internal punctuation.
    protected = [(m.start(), m.start() + len(m.group().rstrip(".,!?;:"))) for m in re.finditer(r"(?:https?://|www\.)[A-Za-z0-9_~:/?#@!$&()*+,;=%.\-]+|[\w.+-]+@[\w.-]+\.[A-Za-z]+", text)]
    def replace(match):
        position = match.start()
        if any(start <= position < end for start, end in protected):
            return match.group()
        before = text[position-1:position]
        after = text[match.end():match.end()+1]
        mark = match.group()[0]
        # Decimal/version numbers, thousands separators, times, domain names,
        # filenames and member access keep their internal punctuation.
        if not match.group()[1:] and ((before.isdigit() and after.isdigit() and mark in ".,:") or (mark == "." and before.isascii() and before.isalnum() and after.isascii() and after.isalnum())):
            return match.group()
        return mark + " "
    return re.sub(r"[,.!?;:][ \t]*", replace, text)


def format_output(text, settings, final=True, rules=None):
    if not final and (settings.englishPunctuation or settings.arabicNumbers):
        # A trailing ASCII token might still become a URL, decimal or filename.
        # Hold it until a delimiter arrives, rather than revising pasted text.
        text = re.sub(r"[A-Za-z0-9_@./:?&=%+#,;!\-]+[ \t]*$", "", text)
    if settings.arabicNumbers:
        rules = load_text_rules() if rules is None else rules
        if not final:
            # A lexical exception may arrive across chunks (千万不 -> 千万不要).
            text = hold_pending(text, rules.protected)
            # Wait for the end of a possible dimension token (三D vs 三Debug).
            text = re.sub(NUMBER + r"[Dd][A-Za-z0-9_]*$", "", text)
            # Wait for a following character before deciding whether this is a
            # number or a word (一 -> 一起), including split decimal/percent forms.
            text = re.sub(r"[0-9零〇一二两三四五六七八九十百千万亿点.负分之]+$", "", text)
        protected = [(m.start(), m.end()) for word in rules.protected for m in re.finditer(re.escape(word), text)]
        def convert(match):
            if any(match.start() < end and match.end() > start for start, end in protected):
                return match.group()
            following = text[match.end():]
            previous = text[match.start()-1:match.start()] if match.start() else ""
            # Preserve a Chinese name immediately before an English identifier.
            # Dimension notation (三D模型) remains a numeric expression.
            if previous and '\u4e00' <= previous <= '\u9fff' and re.match(r"[A-Za-z]", following) and not re.match(r"[Dd](?![A-Za-z0-9_])", following):
                return match.group()
            number = match.group(2)
            sign = "-" if number.startswith("负") else ""
            number = number.lstrip("负")
            whole, dot, fraction = number.replace("点", ".").partition(".")
            value = sign + integer(whole)
            if dot:
                value += "." + "".join(str(DIGITS[c]) for c in fraction)
            return value + ("%" if match.group(1) else "")
        text = PATTERN.sub(convert, text)
        # Apply personal exceptions only after complete numeric values are parsed.
        text = rules.apply(text, final)
    if settings.englishPunctuation:
        text = re.sub(r"[，。！？；：、]", lambda m: m.group().translate(PUNCTUATION) + " ", text)
        return space_punctuation(text.translate(PUNCTUATION))
    return text
