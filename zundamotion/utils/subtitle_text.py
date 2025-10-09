"""Helper utilities for normalizing and validating subtitle strings."""
from __future__ import annotations

from typing import Optional


def is_effective_subtitle_text(text: Optional[str]) -> bool:
    """Return True if the given text should produce a subtitle entry."""
    if text is None:
        return False

    normalized = str(text).strip()
    if not normalized:
        return False

    if normalized in {'""', "''"}:
        return False

    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {'"', "'"}:
        inner = normalized[1:-1].strip()
        if not inner:
            return False

    return True
