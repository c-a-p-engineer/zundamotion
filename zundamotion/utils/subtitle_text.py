"""Helper utilities for normalizing and validating subtitle strings."""
from __future__ import annotations

import re
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
