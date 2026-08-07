from __future__ import annotations

from zundamotion.components.pipeline_phases.video_phase.scene_run_base_safety import (
    SceneRunBaseSafetyMixin,
)


class _Subject(SceneRunBaseSafetyMixin):
    def __init__(self, config):
        self.config = config


def test_legacy_run_base_is_disabled_by_default() -> None:
    subject = _Subject({"video": {}})

    assert subject._effective_scene_copy_for_run_base_safety(
        {"id": "scene"},
        False,
    ) is True


def test_existing_scene_copy_true_remains_true() -> None:
    subject = _Subject({"video": {}})

    assert subject._effective_scene_copy_for_run_base_safety(
        {"id": "scene"},
        True,
    ) is True


def test_legacy_path_can_be_explicitly_reenabled_for_rollback() -> None:
    subject = _Subject({"video": {"legacy_run_base_enabled": True}})

    assert subject._effective_scene_copy_for_run_base_safety(
        {"id": "scene"},
        False,
    ) is False


def test_safety_mixin_does_not_own_standard_render_orchestration() -> None:
    assert "_render_scene_internal" not in SceneRunBaseSafetyMixin.__dict__
