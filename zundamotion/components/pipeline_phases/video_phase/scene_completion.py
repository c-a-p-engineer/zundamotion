"""Finalize per-scene temporary resources and progress state."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ....utils.logger import logger


class SceneCompletionMixin:
    """Apply the legacy scene-base cleanup and progress-update contract."""

    def _complete_scene_render(self, scene_base_path: Optional[Path]) -> None:
        """Clean an external temporary base, then advance scene progress once."""
        if (
            scene_base_path
            and scene_base_path.exists()
            and self.cache_manager.cache_dir.resolve()
            not in scene_base_path.resolve().parents
        ):
            try:
                scene_base_path.unlink()
                logger.debug(
                    "Cleaned up temporary scene base video -> %s",
                    scene_base_path.name,
                )
            except Exception:
                pass
        self.pbar_scenes.update(1)
