"""Compatibility aggregate for the simple-scene fast path.

Character calculation and eligibility are composed separately by SceneRenderer.
This aggregate contains semantic planning, FFmpeg graph construction, and execution.
"""

from __future__ import annotations

from .scene_fast_path_executor import SceneFastPathExecutorMixin
from .scene_fast_path_graph import SceneFastPathGraphMixin
from .scene_fast_path_plan import SceneFastPathPlanMixin


class SceneFastPathMixin(
    SceneFastPathPlanMixin,
    SceneFastPathGraphMixin,
    SceneFastPathExecutorMixin,
):
    """Aggregate fast-path planning, graph construction, and execution."""
