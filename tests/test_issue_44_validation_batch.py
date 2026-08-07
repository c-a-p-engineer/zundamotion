"""Integration-seam checks for the 2026-08-07 performance/diagnostic batch.

These tests intentionally stay lightweight.  Their main purpose is to make the
pull-request workflows import the newly composed facades and verify the MRO and
compatibility boundaries that are otherwise easy to break during refactoring.
"""

from __future__ import annotations

from zundamotion.components.pipeline_phases.audio_duration_cache import (
    AudioDurationCacheProxy,
)
from zundamotion.components.pipeline_phases.audio_worker_policy import (
    resolve_audio_worker_policy,
)
from zundamotion.components.pipeline_phases.video_phase.scene_cache_latency import (
    SceneCacheLatencyProxy,
)
from zundamotion.components.pipeline_phases.video_phase.scene_renderer import (
    SceneRenderer,
)
from zundamotion.components.pipeline_phases.video_phase.scene_run_base_plan import (
    SceneRunBasePlanMixin,
)
from zundamotion.components.pipeline_phases.video_phase.scene_run_base_safety import (
    SceneRunBaseSafetyMixin,
)
from zundamotion.components.subtitles import SubtitleGenerator
from zundamotion.components.subtitles.generator import (
    SubtitleGenerator as BaseSubtitleGenerator,
)
from zundamotion.components.video.face_overlay_cache import FaceOverlayCache


def test_instrumented_subtitle_generator_preserves_base_contract() -> None:
    assert issubclass(SubtitleGenerator, BaseSubtitleGenerator)
    assert callable(SubtitleGenerator.resolve_render_mode_for_subtitles)


def test_scene_renderer_composes_planner_before_safety_guard() -> None:
    mro = SceneRenderer.__mro__
    assert SceneRunBasePlanMixin in mro
    assert SceneRunBaseSafetyMixin in mro
    assert mro.index(SceneRunBasePlanMixin) < mro.index(SceneRunBaseSafetyMixin)


def test_new_proxies_and_policies_remain_importable() -> None:
    assert callable(resolve_audio_worker_policy)
    assert callable(AudioDurationCacheProxy)
    assert callable(SceneCacheLatencyProxy)
    assert callable(FaceOverlayCache)
