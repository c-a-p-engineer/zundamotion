from __future__ import annotations

import inspect
from pathlib import Path

from zundamotion.components.pipeline_phases.video_phase.execution import (
    VideoPhaseExecutionMixin,
)
from zundamotion.components.pipeline_phases.video_phase.main import VideoPhase as BaseVideoPhase


def test_base_video_phase_uses_execution_mixin() -> None:
    assert issubclass(BaseVideoPhase, VideoPhaseExecutionMixin)


def test_video_phase_main_is_below_file_limit() -> None:
    path = Path(inspect.getsourcefile(BaseVideoPhase) or "")
    assert len(path.read_text(encoding="utf-8").splitlines()) <= 500


def test_video_phase_run_and_execution_entrypoints_are_bounded() -> None:
    for target in (
        BaseVideoPhase.run,
        VideoPhaseExecutionMixin._run_video_phase,
        VideoPhaseExecutionMixin._render_one_scene,
        VideoPhaseExecutionMixin._render_parallel_scenes,
        VideoPhaseExecutionMixin._render_serial_scenes,
    ):
        lines, _ = inspect.getsourcelines(target)
        assert len(lines) <= 80, (target.__module__, target.__name__, len(lines))
