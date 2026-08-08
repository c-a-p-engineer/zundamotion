from __future__ import annotations

import inspect

from zundamotion.components.video import VideoRenderer
from zundamotion.components.video.subtitle_overlay_runtime import SubtitleOverlayRuntimeMixin
from zundamotion.components.video.subtitle_overlay_graph import build_subtitle_burn_command
from zundamotion.components.video.subtitle_overlay_execution import execute_subtitle_burn


def test_video_renderer_routes_subtitle_methods_through_runtime_mixin() -> None:
    assert VideoRenderer.apply_subtitle_overlays is SubtitleOverlayRuntimeMixin.apply_subtitle_overlays
    assert VideoRenderer._apply_subtitle_overlays_full is SubtitleOverlayRuntimeMixin._apply_subtitle_overlays_full


def test_extracted_subtitle_overlay_entrypoints_are_bounded() -> None:
    targets = [
        SubtitleOverlayRuntimeMixin.apply_subtitle_overlays,
        SubtitleOverlayRuntimeMixin._apply_subtitle_overlays_full,
        SubtitleOverlayRuntimeMixin._try_segment_pipeline,
        SubtitleOverlayRuntimeMixin._full_subtitle_burn,
        build_subtitle_burn_command,
        execute_subtitle_burn,
    ]
    for target in targets:
        lines, _ = inspect.getsourcelines(target)
        assert len(lines) <= 80, (target.__name__, len(lines))
