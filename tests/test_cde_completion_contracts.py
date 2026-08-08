from __future__ import annotations

from pathlib import Path

from zundamotion.cache import CacheManager
from zundamotion.cache_lifecycle import CacheLifecycleMixin
from zundamotion.cache_media import CacheMediaProbeMixin
from zundamotion.cache_runtime import CacheManager as RuntimeCacheManager
from zundamotion.components.pipeline_phases.video_phase.main import VideoPhase as BaseVideoPhase
from zundamotion.components.video import VideoRenderer
from zundamotion.components.video.subtitle_overlay_runtime import SubtitleOverlayRuntimeMixin
from zundamotion.components.video.wait_clip_runtime import WaitClipRuntimeMixin
from zundamotion.utils import ffmpeg_runner


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_phase_c_refactoring_facades_remain_bounded() -> None:
    assert _line_count(Path(ffmpeg_runner.__file__)) <= 180
    video_phase_path = Path(BaseVideoPhase.__module__.replace(".", "/") + ".py")
    assert _line_count(video_phase_path) <= 500
    assert _line_count(Path("zundamotion/components/markdown/pipeline.py")) <= 500


def test_phase_d_public_video_runtime_bypasses_legacy_subtitle_and_wait_paths() -> None:
    assert (
        VideoRenderer.apply_subtitle_overlays
        is SubtitleOverlayRuntimeMixin.apply_subtitle_overlays
    )
    assert VideoRenderer.render_wait_clip is WaitClipRuntimeMixin.render_wait_clip
    assert VideoRenderer.render_scene_base is WaitClipRuntimeMixin.render_scene_base


def test_phase_d_cache_facade_keeps_modular_runtime_over_compatibility_base() -> None:
    assert issubclass(CacheManager, CacheLifecycleMixin)
    assert issubclass(CacheManager, CacheMediaProbeMixin)
    assert issubclass(CacheManager, RuntimeCacheManager)
