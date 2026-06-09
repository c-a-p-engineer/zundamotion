"""Character base-image path resolution with optional color filtering."""

from pathlib import Path
from typing import Any, Optional

from .image_color_filter_cache import ImageColorFilterCache


class CharacterImageResolver:
    """Resolve expression-specific character base PNGs."""

    def __init__(self, image_color_filter_cache: ImageColorFilterCache) -> None:
        self.image_color_filter_cache = image_color_filter_cache

    @staticmethod
    def resolve_base_image(name: str, expression: str) -> Optional[Path]:
        base_dir = Path(f"assets/characters/{name}")
        candidates = [
            base_dir / expression / "base.png",
            base_dir / f"{expression}.png",
            base_dir / "default" / "base.png",
            base_dir / "default.png",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    async def resolve_image(
        self,
        name: str,
        expression: str,
        color_filter: Any = None,
    ) -> Optional[Path]:
        source_path = self.resolve_base_image(name, expression)
        if source_path is None or color_filter is None:
            return source_path
        return await self.image_color_filter_cache.filter_image(source_path, color_filter)
