"""Apply the talk renderer extraction to large orchestration files once."""

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
        """                line_id = context.line_id
                line_data = context.line_data
                duration = context.duration
                pre_dur = context.pre_duration
                line_config = context.line_config
                extra_audio_overlays = list(context.extra_audio_overlays)
                bg_layout = context.background_layout
                line_bg_image = context.background_source
                line_is_bg_video = context.background_is_video
                background_config = context.background_config
                line_image_layers = list(context.image_layer_overlays)
""",
        """                line_id = context.line_id
                line_is_bg_video = context.background_is_video
""",
        label="line aliases",
    )

    process_start = text.index(
        "        async def process_one(idx: int, line: Dict[str, Any]):"
    )
    start = text.index("                audio_cache_key_data = {", process_start)
    end = text.index(
        "                # Collect lightweight samples for auto-tune",
        start,
    )
    replacement = """                talk_plan = self._build_scene_talk_plan(
                    context=context,
                    static_character_keys=static_char_keys,
                    static_insert_in_base=static_insert_in_base,
                    scene_level_insert_video=scene_level_insert_video,
                )
                render_outcome = await self._render_talk_line(
                    context=context,
                    plan=talk_plan,
                    static_character_keys=static_char_keys,
                    static_insert_in_base=static_insert_in_base,
                )
                clip_path = render_outcome.path
                total_ms = (
                    render_outcome.finished_at - line_total_started
                ) * 1000.0
                cache_status = render_outcome.cache_status
                cache_lookup_ms = render_outcome.cache_lookup_ms
                cache_store_ms = render_outcome.cache_store_ms
                render_ms = render_outcome.render_ms
                prepare_ms = max(
                    0.0,
                    (
                        render_outcome.cache_started_at - line_total_started
                    )
                    * 1000.0,
                )
                has_subtitle = talk_plan.has_subtitle
                any_chars = talk_plan.has_visible_characters
                insert_is_image = talk_plan.insert_is_image
                has_move = talk_plan.has_move
                has_effect = talk_plan.has_effect
                face_anim_list = list(talk_plan.face_animations)
"""
    text = text[:start] + replacement + text[end:]

    if len(text.splitlines()) >= 650:
        raise RuntimeError("scene_standard_renderer.py did not shrink below 650 lines")
    if "video_cache_data =" in text or "clip_creator_func" in text:
        raise RuntimeError("legacy inline talk renderer remains")
    path.write_text(text, encoding="utf-8")


def patch_scene_renderer() -> None:
    path = VIDEO_PHASE / "scene_renderer.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from .scene_talk_plan import SceneTalkPlanMixin\n",
        "from .scene_talk_plan import SceneTalkPlanMixin\n"
        "from .scene_talk_renderer import SceneTalkRendererMixin\n",
        label="talk renderer import",
    )
    text = replace_once(
        text,
        """    SceneTimingMixin,
    SceneTalkPlanMixin,
    SceneWaitRendererMixin,
""",
        """    SceneTimingMixin,
    SceneTalkPlanMixin,
    SceneTalkRendererMixin,
    SceneWaitRendererMixin,
""",
        label="talk renderer MRO",
    )
    path.write_text(text, encoding="utf-8")


def patch_module_split_test() -> None:
    path = ROOT / "tests/test_scene_renderer_module_split.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '        "_build_scene_talk_plan": "scene_talk_plan",\n',
        '        "_build_scene_talk_plan": "scene_talk_plan",\n'
        '        "_render_talk_line": "scene_talk_renderer",\n',
        label="module split talk renderer",
    )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_standard_renderer()
    patch_scene_renderer()
    patch_module_split_test()


if __name__ == "__main__":
    main()
