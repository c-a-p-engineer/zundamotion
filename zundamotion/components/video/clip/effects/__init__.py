"""Character overlay effect resolvers.

This package exposes helper utilities that translate high-level effect
configuration into FFmpeg filter graph snippets and overlay expressions.
"""

from .resolve import FilterSnippet, resolve_character_effects

__all__ = ["FilterSnippet", "resolve_character_effects"]
