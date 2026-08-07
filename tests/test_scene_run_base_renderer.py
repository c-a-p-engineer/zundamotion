from __future__ import annotations

import asyncio
from pathlib import Path

from zundamotion.components.pipeline_phases.video_phase.scene_run_base_plan import (
    RunBasePlan,
)
from zundamotion.components.pipeline_phases.video_phase.scene_run_base_renderer import (
    SceneRunBaseRendererMixin,
)


class _VideoRenderer:
    def __init__(self, tmp_path: Path, *, fail: bool = False) -> None:
        self.tmp_path = tmp_path
        self.fail = fail
        self.calls = []

    async def render_scene_base_composited(
        self, background, duration, output_name, overlays
    ):
        self.calls.append((background, duration, output_name, overlays))
        if self.fail:
            raise RuntimeError("render failed")
        path = self.tmp_path / f"{output_name}.mp4"
        path.write_bytes(b"video")
        return path


class _Subject(SceneRunBaseRendererMixin):
    def __init__(self, tmp_path: Path, plans, *, fail: bool = False) -> None:
        self.plans = plans
        self.video_renderer = _VideoRenderer(tmp_path, fail=fail)

    def _build_run_base_plans(self, scene_id):
        self.requested_scene_id = scene_id
        return self.plans


def _plan() -> RunBasePlan:
    return RunBasePlan(
        start_line=3,
        end_line=4,
        duration=1.25,
        overlays=({"path": "character.png"},),
        character_keys=frozenset({"character-key"}),
        has_insert_image=False,
        offsets={3: 0.0, 4: 0.5},
    )


def test_prepare_run_bases_preserves_original_indexes_and_offsets(tmp_path: Path) -> None:
    subject = _Subject(tmp_path, [_plan()])

    rendered = asyncio.run(
        subject._prepare_run_bases(
            scene_id="demo",
            background="background.png",
            is_background_video=False,
            scene_base_path=None,
            scene_copy=False,
            has_line_background_override=False,
        )
    )

    assert subject.requested_scene_id == "demo"
    assert len(rendered) == 1
    assert rendered[0].start_line == 3
    assert rendered[0].end_line == 4
    assert rendered[0].offsets == {3: 0.0, 4: 0.5}
    assert rendered[0].character_keys == frozenset({"character-key"})
    assert subject.video_renderer.calls == [
        (
            {"type": "image", "path": "background.png"},
            1.25,
            "scene_base_demo_run_3_4",
            [{"path": "character.png"}],
        )
    ]


def test_prepare_run_bases_skips_ineligible_scene(tmp_path: Path) -> None:
    cases = (
        {
            "scene_base_path": tmp_path / "base.mp4",
            "scene_copy": False,
            "has_line_background_override": False,
        },
        {
            "scene_base_path": None,
            "scene_copy": True,
            "has_line_background_override": False,
        },
        {
            "scene_base_path": None,
            "scene_copy": False,
            "has_line_background_override": True,
        },
    )
    for kwargs in cases:
        subject = _Subject(tmp_path, [_plan()])
        rendered = asyncio.run(
            subject._prepare_run_bases(
                scene_id="demo",
                background="background.png",
                is_background_video=False,
                **kwargs,
            )
        )
        assert rendered == []
        assert subject.video_renderer.calls == []


def test_failed_plan_is_omitted(tmp_path: Path) -> None:
    subject = _Subject(tmp_path, [_plan()], fail=True)

    rendered = asyncio.run(
        subject._prepare_run_bases(
            scene_id="demo",
            background="background.mp4",
            is_background_video=True,
            scene_base_path=None,
            scene_copy=False,
            has_line_background_override=False,
        )
    )

    assert rendered == []


def test_find_run_base_uses_original_line_range(tmp_path: Path) -> None:
    subject = _Subject(tmp_path, [_plan()])
    rendered = asyncio.run(
        subject._prepare_run_bases(
            scene_id="demo",
            background="background.png",
            is_background_video=False,
            scene_base_path=None,
            scene_copy=False,
            has_line_background_override=False,
        )
    )

    assert subject._find_run_base(rendered, 2) is None
    assert subject._find_run_base(rendered, 3) is rendered[0]
    assert subject._find_run_base(rendered, 4) is rendered[0]
    assert subject._find_run_base(rendered, 5) is None
