from __future__ import annotations

import inspect

from zundamotion.utils import ffmpeg_ops
from zundamotion.utils.ffmpeg_background import build_background_fit_steps
from zundamotion.utils.ffmpeg_concat import concat_videos_safe
from zundamotion.utils.ffmpeg_normalize import normalize_media
from zundamotion.utils.ffmpeg_transition import apply_transition, apply_transition_local


def test_ffmpeg_ops_facade_reexports_modular_entrypoints() -> None:
    assert ffmpeg_ops.build_background_fit_steps is build_background_fit_steps
    assert ffmpeg_ops.concat_videos_safe is concat_videos_safe
    assert ffmpeg_ops.normalize_media is normalize_media
    assert ffmpeg_ops.apply_transition is apply_transition
    assert ffmpeg_ops.apply_transition_local is apply_transition_local


def test_modular_ffmpeg_entrypoints_are_bounded() -> None:
    for target in (
        build_background_fit_steps,
        concat_videos_safe,
        normalize_media,
        apply_transition,
        apply_transition_local,
    ):
        lines, _ = inspect.getsourcelines(target)
        assert len(lines) <= 80, (target.__module__, target.__name__, len(lines))
