from __future__ import annotations

import inspect
from pathlib import Path

from zundamotion.utils import ffmpeg_ops
from zundamotion.utils.ffmpeg_background import build_background_fit_steps
from zundamotion.utils.ffmpeg_concat import concat_videos_safe
from zundamotion.utils.ffmpeg_normalize import normalize_media
from zundamotion.utils.ffmpeg_transition import apply_transition, apply_transition_local


def _assert_modular_export(exported, suffix: str) -> None:
    assert exported.__module__.endswith(suffix), exported.__module__


def test_ffmpeg_ops_facade_reexports_modular_entrypoints() -> None:
    _assert_modular_export(ffmpeg_ops.build_background_fit_steps, ".ffmpeg_background")
    _assert_modular_export(ffmpeg_ops.concat_videos_safe, ".ffmpeg_concat")
    _assert_modular_export(ffmpeg_ops.normalize_media, ".ffmpeg_normalize")
    _assert_modular_export(ffmpeg_ops.apply_transition, ".ffmpeg_transition")
    _assert_modular_export(ffmpeg_ops.apply_transition_local, ".ffmpeg_transition")


def test_ffmpeg_ops_facade_remains_small() -> None:
    source_path = Path(ffmpeg_ops.__file__)
    assert len(source_path.read_text(encoding="utf-8").splitlines()) <= 120


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