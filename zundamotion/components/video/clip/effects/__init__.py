"""Character overlay effect resolvers.

This package exposes helper utilities that translate high-level effect
configuration into FFmpeg filter graph snippets and overlay expressions.
"""

from .resolve import (
    FilterSnippet,
    ScreenEffectSnippet,
    resolve_character_effects,
    resolve_screen_effects,
)

__all__ = [
    "FilterSnippet",
    "ScreenEffectSnippet",
    "resolve_character_effects",
    "resolve_screen_effects",
]
