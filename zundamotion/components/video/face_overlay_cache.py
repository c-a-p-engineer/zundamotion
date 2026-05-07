from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional, Dict, Any

from PIL import Image, ImageOps

from zundamotion.cache import CacheManager


class FaceOverlayCache:
    """
    Cache for preprocessed face overlay PNGs (eyes/ mouth states) scaled to a
    specific factor and optionally alpha-thresholded to reduce edge thickening.
    """

    def __init__(self, cache_manager: CacheManager):
        self.cache = cache_manager

    @staticmethod
    def _render_scaled_overlay(
        *,
        src_path: Path,
        out_path: Path,
        scale: float,
        alpha_threshold: Optional[int],
        horizontal_flip: bool,
        vertical_flip: bool,
    ) -> Path:
        img = Image.open(src_path).convert("RGBA")
        if horizontal_flip:
            img = ImageOps.mirror(img)
        if vertical_flip:
            img = ImageOps.flip(img)
        if scale != 1.0:
            w, h = img.size
            sw = max(1, int(round(w * float(scale))))
            sh = max(1, int(round(h * float(scale))))
            img = img.resize((sw, sh), resample=Image.LANCZOS)
        if alpha_threshold is not None:
            r, g, b, a = img.split()
            thr = int(alpha_threshold)
            a = a.point(lambda v: 255 if v >= thr else 0)
            img = Image.merge("RGBA", (r, g, b, a))
        img.save(out_path, format="PNG")
        return out_path

    async def get_scaled_overlay(
        self,
        src_path: Path,
        scale: float,
        alpha_threshold: Optional[int] = 128,
        horizontal_flip: bool = False,
        vertical_flip: bool = False,
    ) -> Path:
        """
        Return path to a cached, pre-scaled/flipped (and optionally
        alpha-hard-thresholded) PNG derived from src_path.
        """
        p = Path(src_path)
        st = p.stat()
        key_data: Dict[str, Any] = {
            "src": str(p.resolve()),
            "mtime": int(st.st_mtime),
            "size": st.st_size,
            "scale": float(scale),
            "alpha_thr": int(alpha_threshold) if alpha_threshold is not None else None,
            "horizontal_flip": bool(horizontal_flip),
            "vertical_flip": bool(vertical_flip),
            "op": "face_overlay_scaled",
        }

        async def _creator(out_path: Path) -> Path:
            return await asyncio.to_thread(
                self._render_scaled_overlay,
                src_path=p,
                out_path=out_path,
                scale=float(scale),
                alpha_threshold=alpha_threshold,
                horizontal_flip=horizontal_flip,
                vertical_flip=vertical_flip,
            )

        return await self.cache.get_or_create(
            key_data=key_data,
            file_name="face_overlay",
            extension="png",
            creator_func=_creator,
        )
