from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional, Dict, Any

from PIL import Image, ImageOps

from zundamotion.cache import CacheManager
from zundamotion.utils import perf_stats


class FaceOverlayCache:
    """
    Cache for preprocessed face overlay PNGs (eyes/ mouth states) scaled to a
    specific factor and optionally alpha-thresholded to reduce edge thickening.
    """

    def __init__(self, cache_manager: CacheManager):
        self.cache = cache_manager
        self._run_memo: Dict[tuple[Any, ...], Path] = {}
        self._run_inflight: Dict[tuple[Any, ...], asyncio.Task[Path]] = {}
        self._run_lock = asyncio.Lock()

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

    @staticmethod
    def _run_memo_key(
        *,
        source: Path,
        scale: float,
        alpha_threshold: Optional[int],
        horizontal_flip: bool,
        vertical_flip: bool,
    ) -> tuple[Any, ...]:
        stat = source.stat()
        return (
            str(source.resolve()),
            stat.st_mtime_ns,
            stat.st_size,
            float(scale),
            int(alpha_threshold) if alpha_threshold is not None else None,
            bool(horizontal_flip),
            bool(vertical_flip),
        )

    async def _resolve_scaled_overlay(
        self,
        *,
        source: Path,
        scale: float,
        alpha_threshold: Optional[int],
        horizontal_flip: bool,
        vertical_flip: bool,
    ) -> Path:
        stat = source.stat()
        key_data: Dict[str, Any] = {
            "src": str(source.resolve()),
            "mtime": int(stat.st_mtime),
            "size": stat.st_size,
            "scale": float(scale),
            "alpha_thr": int(alpha_threshold) if alpha_threshold is not None else None,
            "horizontal_flip": bool(horizontal_flip),
            "vertical_flip": bool(vertical_flip),
            "op": "face_overlay_scaled",
        }

        async def _creator(out_path: Path) -> Path:
            return await asyncio.to_thread(
                self._render_scaled_overlay,
                src_path=source,
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

    async def get_scaled_overlay(
        self,
        src_path: Path,
        scale: float,
        alpha_threshold: Optional[int] = 128,
        horizontal_flip: bool = False,
        vertical_flip: bool = False,
    ) -> Path:
        """Return a persistent cache path with run-local lookup de-duplication."""
        source = Path(src_path)
        memo_key = self._run_memo_key(
            source=source,
            scale=scale,
            alpha_threshold=alpha_threshold,
            horizontal_flip=horizontal_flip,
            vertical_flip=vertical_flip,
        )

        async with self._run_lock:
            cached = self._run_memo.get(memo_key)
            if cached is not None and cached.exists():
                perf_stats.incr("face_overlay_run_memo_hit")
                return cached
            existing = self._run_inflight.get(memo_key)
            if existing is None:
                perf_stats.incr("face_overlay_run_memo_miss")
                task = asyncio.create_task(
                    self._resolve_scaled_overlay(
                        source=source,
                        scale=scale,
                        alpha_threshold=alpha_threshold,
                        horizontal_flip=horizontal_flip,
                        vertical_flip=vertical_flip,
                    )
                )
                self._run_inflight[memo_key] = task
            else:
                perf_stats.incr("face_overlay_run_memo_wait")
                task = existing

        try:
            result = await task
            async with self._run_lock:
                self._run_memo[memo_key] = result
            return result
        finally:
            async with self._run_lock:
                if self._run_inflight.get(memo_key) is task:
                    self._run_inflight.pop(memo_key, None)
