"""Face overlay precache preparation for SceneRenderer.

Internal mixin. It preserves the existing FACE_* environment and cache semantics.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List

from ....utils.logger import logger
from ...video.clip.face import _resolve_face_asset
from ...video.clip.characters import is_horizontal_flip_enabled, is_vertical_flip_enabled


class SceneFacePrecacheMixin:
    """Warm scaled mouth/eye overlay PNGs before clip rendering."""

    async def _precache_face_overlays(
        self,
        *,
        scene_id: str,
        scene: Dict[str, Any],
        line_data_map: Dict[str, Dict[str, Any]],
    ) -> None:
        if os.environ.get("FACE_CACHE_DISABLE", "0") == "1":
            return

        vcfg = self.config.get("video", {}) or {}
        if vcfg.get("precache_face_overlays", True) is False:
            return

        try:
            thr_env = os.environ.get("FACE_ALPHA_THRESHOLD")
            alpha_threshold = int(thr_env) if (thr_env and thr_env.isdigit()) else 128
        except Exception:
            alpha_threshold = 128

        specs: Dict[str, Dict[str, Any]] = {}
        for idx, _line in enumerate(scene.get("lines", []) or [], start=1):
            data = line_data_map.get(f"{scene_id}_{idx}") or {}
            line_config = data.get("line_config") or {}
            face_anim_raw = data.get("face_anim")
            if isinstance(face_anim_raw, list):
                face_anims = [item for item in face_anim_raw if isinstance(item, dict)]
            elif isinstance(face_anim_raw, dict):
                face_anims = [face_anim_raw]
            else:
                face_anims = []
            if not face_anims:
                continue

            characters = line_config.get("characters") or []
            char_by_name = {
                str(ch.get("name")): ch
                for ch in characters
                if isinstance(ch, dict) and ch.get("name")
            }

            for face_anim in face_anims:
                target_name = str(face_anim.get("target_name") or "")
                if not target_name:
                    continue
                char_cfg = char_by_name.get(target_name, {})
                try:
                    scale = float(char_cfg.get("scale", 1.0))
                except Exception:
                    scale = 1.0
                expression = str(char_cfg.get("expression", "default"))
                asset_name = str(char_cfg.get("asset_name") or target_name)
                flip_x = is_horizontal_flip_enabled(char_cfg)
                flip_y = is_vertical_flip_enabled(char_cfg)
                base_dir = Path(f"assets/characters/{asset_name}")

                candidates: List[Path] = []
                eyes_segments = face_anim.get("eyes") or []
                if isinstance(eyes_segments, list) and eyes_segments:
                    candidates.append(
                        _resolve_face_asset(base_dir, expression, "eyes", "close.png")
                    )

                mouth_segments = face_anim.get("mouth") or []
                if isinstance(mouth_segments, list) and mouth_segments:
                    states = {str(seg.get("state") or "") for seg in mouth_segments}
                    if "half" in states:
                        candidates.append(
                            _resolve_face_asset(base_dir, expression, "mouth", "half.png")
                        )
                    if "open" in states:
                        candidates.append(
                            _resolve_face_asset(base_dir, expression, "mouth", "open.png")
                        )

                for path in candidates:
                    if not path.exists():
                        continue
                    try:
                        stat = path.stat()
                    except Exception:
                        continue
                    key = json.dumps(
                        {
                            "path": str(path.resolve()),
                            "mtime": int(stat.st_mtime),
                            "size": stat.st_size,
                            "scale": scale,
                            "alpha_threshold": alpha_threshold,
                            "flip_x": flip_x,
                            "flip_y": flip_y,
                        },
                        sort_keys=True,
                        default=str,
                    )
                    specs.setdefault(
                        key,
                        {
                            "path": path,
                            "scale": scale,
                            "alpha_threshold": alpha_threshold,
                            "flip_x": flip_x,
                            "flip_y": flip_y,
                        },
                    )

        if not specs:
            return

        tasks = [
            self.video_renderer.face_cache.get_scaled_overlay(
                spec["path"],
                spec["scale"],
                spec["alpha_threshold"],
                horizontal_flip=spec["flip_x"],
                vertical_flip=spec["flip_y"],
            )
            for spec in specs.values()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        failures = sum(1 for result in results if isinstance(result, Exception))
        if failures:
            logger.warning(
                "Precached %d/%d face overlay PNG(s) for scene '%s' (%d failed)",
                len(specs) - failures,
                len(specs),
                scene_id,
                failures,
            )
        else:
            logger.info(
                "Precached %d face overlay PNG(s) for scene '%s'",
                len(specs),
                scene_id,
            )
