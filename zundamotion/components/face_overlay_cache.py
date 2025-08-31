from __future__ import annotations

from pathlib import Path
from typing import Optional, Dict, Any

from PIL import Image

from zundamotion.cache import CacheManager


class FaceOverlayCache:
    """
    Cache for preprocessed face overlay PNGs (eyes/ mouth states) scaled to a
    specific factor and optionally alpha-thresholded to reduce edge thickening.
    """

    def __init__(self, cache_manager: CacheManager):
        self.cache = cache_manager

    async def get_scaled_overlay(
        self, src_path: Path, scale: float, alpha_threshold: Optional[int] = 128
    ) -> Path:
        """
        Return path to a cached, pre-scaled (and optionally alpha-hard-thresholded)
        PNG derived from src_path.
        """
        p = Path(src_path)
        st = p.stat()
        key_data: Dict[str, Any] = {
            "src": str(p.resolve()),
            "mtime": int(st.st_mtime),
            "size": st.st_size,
            "scale": float(scale),
            "alpha_thr": int(alpha_threshold) if alpha_threshold is not None else None,
            "op": "face_overlay_scaled",
        }

        async def _creator(out_path: Path) -> Path:
            img = Image.open(p).convert("RGBA")
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

        return await self.cache.get_or_create(
            key_data=key_data,
            file_name="face_overlay",
            extension="png",
            creator_func=_creator,
        )

