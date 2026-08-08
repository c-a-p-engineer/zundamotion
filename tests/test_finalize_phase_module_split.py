from __future__ import annotations

import inspect
from pathlib import Path

from zundamotion.components.pipeline_phases.finalize_cache import FinalizeCacheMixin
from zundamotion.components.pipeline_phases.finalize_concat import FinalizeConcatMixin
from zundamotion.components.pipeline_phases.finalize_phase import FinalizePhase
from zundamotion.components.pipeline_phases.finalize_transitions import FinalizeTransitionMixin


def test_finalize_phase_composes_explicit_responsibilities() -> None:
    assert issubclass(FinalizePhase, FinalizeTransitionMixin)
    assert issubclass(FinalizePhase, FinalizeConcatMixin)
    assert issubclass(FinalizePhase, FinalizeCacheMixin)


def test_finalize_run_is_bounded_orchestration() -> None:
    lines, _ = inspect.getsourcelines(FinalizePhase.run)
    assert len(lines) <= 80


def test_finalize_phase_facade_remains_small() -> None:
    path = Path(inspect.getsourcefile(FinalizePhase) or "")
    assert path.is_file()
    assert len(path.read_text(encoding="utf-8").splitlines()) <= 140


def test_finalize_responsibility_entrypoints_are_bounded() -> None:
    targets = [
        FinalizeCacheMixin._is_valid_finalize_cache,
        FinalizeCacheMixin._get_or_create_finalize_cache,
        FinalizeTransitionMixin._apply_one_transition,
        FinalizeTransitionMixin._apply_scene_transitions,
        FinalizeConcatMixin._concat_processed_paths,
        FinalizeConcatMixin._reencode_concat,
    ]
    for target in targets:
        lines, _ = inspect.getsourcelines(target)
        assert len(lines) <= 80, (target.__module__, target.__name__, len(lines))
