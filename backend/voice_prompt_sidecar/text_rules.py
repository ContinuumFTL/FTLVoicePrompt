"""Read the editable UTF-8 environment-style formatting rules once per recording."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re


DEFAULT_RULES_PATH = Path(__file__).resolve().parents[1] / "text-rules.env"
NUMERIC_LEFT_BOUNDARY = r"(?<![A-Za-z0-9_.+\-第负零〇一二两三四五六七八九十百千万亿点])"


def hold_pending(text, sources, ignore_case=False):
    candidate = text.lower() if ignore_case else text
    pending = [end for source in sources for end in range(1, len(source))
               if candidate.endswith((source.lower() if ignore_case else source)[:end])]
    return text[:-max(pending)] if pending else text


@dataclass(frozen=True)
class TextRules:
    protected: tuple[str, ...]
    replacements: tuple[tuple[str, str], ...]
    casing: tuple[tuple[str, str], ...]

    def apply(self, text, final):
        # Longest literal source wins; replacements never cascade within a pass.
        replacements = dict(self.replacements)
        if replacements:
            if not final:
                text = hold_pending(text, replacements)
            alternatives = "|".join(re.escape(s) for s in sorted(replacements, key=len, reverse=True))
            text = re.sub(NUMERIC_LEFT_BOUNDARY + "(?:" + alternatives + ")",
                          lambda m: replacements[m.group()], text)
        casing = {source.lower(): target for source, target in self.casing}
        if casing:
            if not final:
                text = hold_pending(text, casing, ignore_case=True)
            alternatives = "|".join(re.escape(s) for s in sorted(casing, key=len, reverse=True))
            text = re.sub(r"(?<![A-Za-z])(?:" + alternatives + r")(?![A-Za-z])",
                          lambda m: casing[m.group().lower()], text, flags=re.IGNORECASE)
        return text


def load_text_rules(path=None):
    path = Path(path) if path is not None else Path(os.environ.get("FTL_VOICE_PROMPT_RULES_FILE") or DEFAULT_RULES_PATH)
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"无法读取文字替换规则文件 {path}: {exc}") from exc
    protected, replacements, casing = [], [], []
    keys, sources = set(), set()
    for number, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            key, value = line.split("=", 1)
            key = key.strip()
            if not re.fullmatch(r"(?:KEEP|REPLACE|CASE)_[A-Z0-9_]+", key) or key in keys:
                raise ValueError("键名无效或重复；使用 KEEP_、REPLACE_ 或 CASE_ 加唯一编号")
            value = json.loads(value.strip())
            if not isinstance(value, str) or not value or value != value.strip() or "\n" in value or "\r" in value:
                raise ValueError("值必须是非空、单行、无首尾空格的双引号字符串")
            keys.add(key)
            if key.startswith("KEEP_"):
                if value in protected:
                    raise ValueError("重复的保护词")
                protected.append(value)
                continue
            source, separator, target = value.partition("=>")
            if not separator or not source or not target or "=>" in target:
                raise ValueError("替换格式必须为 原文=>结果")
            kind = key.split("_", 1)[0]
            if kind == "REPLACE" and not re.fullmatch(r"[0-9]+[\u4e00-\u9fff]+", source):
                raise ValueError("REPLACE 原文必须是阿拉伯整数紧跟中文，例如 1些")
            if kind == "CASE" and not re.fullmatch(r"[A-Za-z]+", source):
                raise ValueError("CASE 原文必须是英文字母")
            identity = (kind, source.lower() if kind == "CASE" else source)
            if identity in sources:
                raise ValueError("重复的替换原文")
            sources.add(identity)
            (casing if kind == "CASE" else replacements).append((source, target))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"文字替换规则 {path}:{number}: {exc}") from exc
    return TextRules(tuple(protected), tuple(replacements), tuple(casing))
