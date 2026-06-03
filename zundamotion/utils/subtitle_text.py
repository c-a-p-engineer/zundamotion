"""Helper utilities for normalizing and validating subtitle strings."""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

_BR_TAG_PATTERN = re.compile(r"<br\s*/?>", re.IGNORECASE)


def normalize_subtitle_text(text: str | None) -> str:
    """Normalize subtitle text for rendering and subtitle file output.

    This helper converts common manual line-break hints to actual newline characters
    so that creators can intentionally break long subtitles. Supported markers are:

    - literal ``\n`` sequences inside YAML strings
    - Windows style newlines (``\r\n``) and bare ``\r``
    - HTML style ``<br>`` tags (case insensitive, optional slash)

    The function returns an empty string when ``text`` is ``None`` to simplify
    downstream handling.
    """

    if text is None:
        return ""

    value = str(text)
    if not value:
        return ""

    # Normalise newline variants first
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    # Support literal "\n" sequences embedded in YAML strings
    value = value.replace("\\n", "\n")
    # Allow creators to use HTML style <br> markers as explicit breaks
    value = _BR_TAG_PATTERN.sub("\n", value)
    return value


def is_effective_subtitle_text(text: Optional[str]) -> bool:
    """Return True if the given text should produce a subtitle entry."""
    if text is None:
        return False

    normalized = normalize_subtitle_text(text).strip()
    if not normalized:
        return False

    if normalized in {'""', "''"}:
        return False

    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {'"', "'"}:
        inner = normalized[1:-1].strip()
        if not inner:
            return False

    return True


def subtitle_char_display_width(ch: str) -> float:
    """Return the approximate subtitle display width for a single character."""

    if not ch or ch == "\n":
        return 0.0

    if ord(ch) < 128:
        return 0.5

    east_asian_width = unicodedata.east_asian_width(ch)
    if east_asian_width in {"F", "W"}:
        return 1.0
    if east_asian_width in {"H", "Na"}:
        return 0.5
    return 1.0


def subtitle_display_width(text: str | None) -> float:
    """Return the approximate subtitle display width for a string."""

    if text is None:
        return 0.0
    return sum(subtitle_char_display_width(ch) for ch in str(text) if ch != "\n")


def wrap_subtitle_text_by_display_width(text: str | None, max_width: float) -> str:
    """Wrap subtitle text by approximate display width while preserving explicit newlines."""

    if text is None:
        return ""

    value = str(text).replace("\\n", "\n")
    if max_width <= 0:
        return value

    lines: list[str] = []
    for paragraph in value.split("\n"):
        if not paragraph:
            lines.append("")
            continue

        current_line_chars: list[str] = []
        current_width = 0.0
        for ch in paragraph:
            ch_width = subtitle_char_display_width(ch)
            if current_line_chars and current_width + ch_width > max_width:
                lines.append("".join(current_line_chars))
                current_line_chars = [ch]
                current_width = ch_width
                continue
            current_line_chars.append(ch)
            current_width += ch_width

        lines.append("".join(current_line_chars))

    return "\n".join(lines)
