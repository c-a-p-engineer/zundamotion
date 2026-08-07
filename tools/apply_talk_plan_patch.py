"""Apply the SceneTalkPlan extraction to large orchestration files once."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIDEO_PHASE = ROOT / "zundamotion/components/pipeline_phases/video_phase"


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def patch_standard_renderer() -> None:
    path = VIDEO_PHASE / "scene_standard_renderer.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from ....utils.subtitle_text import is_effective_subtitle_text\n",
        "",
        label="unused subtitle import",
    )
    text = replace_once(
        text,
        "                run_base = context.run_base\n",
        "",
        label="run base alias",
    )

    process_start = text.index(
        "        async def process_one(idx: int, line: Dict[str, Any]):"
    )
    start = text.index(
        "                # 静的レイヤをベースに取り込んでいる場合、行側から該当項目のみ除去",
        process_start,
    )
    end = text.index("                video_cache_data = {", start)
    replacement = """                talk_plan = self._build_scene_talk_plan(
                    context=context,
                    static_character_keys=static_char_keys,
                    static_insert_in_base=static_insert_in_base,
                    scene_level_insert_video=scene_level_insert_video,
                )
                effective_characters = list(talk_plan.effective_characters)
                effective_insert = talk_plan.effective_insert
                face_anim_list = list(talk_plan.face_animations)
                anim_meta = talk_plan.animation_meta
                has_subtitle = talk_plan.has_subtitle
                any_chars = talk_plan.has_visible_characters
                insert_is_image = talk_plan.insert_is_image
                has_move = talk_plan.has_move
                has_effect = talk_plan.has_effect

"""
    text = text[:start] + replacement + text[end:]

    metrics_start = text.index(
        '                has_subtitle = is_effective_subtitle_text(line_data.get("text"))',
        start,
    )
    metrics_end = text.index(
        "                creator_started: Optional[float] = None",
        metrics_start,
    )
    text = text[:metrics_start] + text[metrics_end:]

    if len(text.splitlines()) >= 740:
        raise RuntimeError("scene_standard_renderer.py did not shrink below 740 lines")
    if "original_characters =" in text or "face_anim_raw =" in text:
        raise RuntimeError("legacy inline talk planning remains")
    path.write_text(text, encoding="utf-8")


def patch_scene_renderer() -> None:
    path = VIDEO_PHASE / "scene_renderer.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from .scene_timing import SceneTimingMixin\n",
        "from .scene_timing import SceneTimingMixin\n"
        "from .scene_talk_plan import SceneTalkPlanMixin\n",
        label="talk plan import",
    )
    text = replace_once(
        text,
        """    SceneRunBaseRendererMixin,
    SceneTimingMixin,
    SceneWaitRendererMixin,
""",
        """    SceneRunBaseRendererMixin,
    SceneTimingMixin,
    SceneTalkPlanMixin,
    SceneWaitRendererMixin,
""",
        label="talk plan MRO",
    )
    path.write_text(text, encoding="utf-8")


def patch_module_split_test() -> None:
    path = ROOT / "tests/test_scene_renderer_module_split.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '        "_render_wait_line": "scene_wait_renderer",\n',
        '        "_render_wait_line": "scene_wait_renderer",\n'
        '        "_build_scene_talk_plan": "scene_talk_plan",\n',
        label="module split talk plan",
    )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_standard_renderer()
    patch_scene_renderer()
    patch_module_split_test()


if __name__ == "__main__":
    main()
