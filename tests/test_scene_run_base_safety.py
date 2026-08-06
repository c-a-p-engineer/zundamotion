from __future__ import annotations

import asyncio

from zundamotion.components.pipeline_phases.video_phase.scene_run_base_safety import (
    SceneRunBaseSafetyMixin,
)


class _NextRenderer:
    async def _render_scene_internal(
        self,
        scene,
        scene_cp,
        bg_default,
        scene_hash_data,
    ):
        self.forwarded_scene_cp = scene_cp
        return ["result"]


class _Subject(SceneRunBaseSafetyMixin, _NextRenderer):
    def __init__(self, config):
        self.config = config
        self.forwarded_scene_cp = None


def test_legacy_run_base_is_disabled_by_default() -> None:
    subject = _Subject({"video": {}})

    result = asyncio.run(
        subject._render_scene_internal({"id": "scene"}, False, "bg.png", {})
    )

    assert result == ["result"]
    assert subject.forwarded_scene_cp is True


def test_existing_scene_copy_true_remains_true() -> None:
    subject = _Subject({"video": {}})

    asyncio.run(subject._render_scene_internal({"id": "scene"}, True, "bg.png", {}))

    assert subject.forwarded_scene_cp is True


def test_legacy_path_can_be_explicitly_reenabled_for_rollback() -> None:
    subject = _Subject({"video": {"legacy_run_base_enabled": True}})

    asyncio.run(subject._render_scene_internal({"id": "scene"}, False, "bg.png", {}))

    assert subject.forwarded_scene_cp is False
