"""Compatibility aggregate for SceneRenderer preparation responsibilities.

Background/badge, face precache, and image-layer preparation live in dedicated
modules. External callers continue to use scene_renderer.SceneRenderer.
"""

from __future__ import annotations

from .scene_background_preparation import SceneBackgroundPreparationMixin
from .scene_face_precache import SceneFacePrecacheMixin
from .scene_image_layer_preparation import SceneImageLayerPreparationMixin


class ScenePreparationMixin(
    SceneBackgroundPreparationMixin,
    SceneFacePrecacheMixin,
    SceneImageLayerPreparationMixin,
):
    """Aggregate preparation mixins without adding behavior."""
