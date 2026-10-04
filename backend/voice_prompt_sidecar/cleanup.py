from __future__ import annotations

import re


def clean_transcript(text: str) -> str:
    """Light cleanup that preserves mixed Chinese/English technical terms."""
    cleaned = re.sub(r"\s+", " ", text.strip())
    cleaned = _remove_adjacent_duplicate_tokens(cleaned)
    cleaned = _remove_adjacent_duplicate_chinese_phrases(cleaned)
    return cleaned.strip()


def _remove_adjacent_duplicate_tokens(text: str) -> str:
    tokens = text.split(" ")
    output: list[str] = []
    for token in tokens:
        if token and (not output or output[-1] != token):
            output.append(token)
    return " ".join(output)


def _remove_adjacent_duplicate_chinese_phrases(text: str) -> str:
    previous = None
    current = text
    phrase_with_space = re.compile(r"([\u4e00-\u9fff]{2,6})\s+\1")
    phrase_without_space = re.compile(r"([\u4e00-\u9fff]{2,6})\1")
    while previous != current:
        previous = current
        current = phrase_with_space.sub(r"\1", current)
        current = phrase_without_space.sub(r"\1", current)
    return current
