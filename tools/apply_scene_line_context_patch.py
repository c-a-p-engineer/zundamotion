"""Apply the SceneLineContext extraction to large orchestration files once."""

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
    process_start = text.index(
        "        async def process_one(idx: int, line: Dict[str, Any]):"
    )
    start = text.index('                line_id = f"{scene_id}_{idx}"', process_start)
    end = text.index('                if line_data["type"] == "image_layer":', start)
    replacement = """                context = self._build_scene_line_context(
                    scene_id=scene_id,
                    line_index=idx,
                    line=line,
                    scene_background=str(bg_image),
                    scene_base_path=scene_base_path,
                    normalized_background_path=normalized_bg_path,
                    start_time_by_index=start_time_by_idx,
                    run_bases=run_bases,
                    image_layers_by_line=image_layers_by_line,
                )
                line_id = context.line_id
                line_data = context.line_data
                duration = context.duration
                pre_dur = context.pre_duration
                line_config = context.line_config
                extra_audio_overlays = list(context.extra_audio_overlays)
                bg_layout = context.background_layout
                line_bg_image = context.background_source
                line_is_bg_video = context.background_is_video
                run_base = context.run_base
                background_config = context.background_config
                line_image_layers = list(context.image_layer_overlays)

"""
    text = text[:start] + replacement + text[end:]
    text = replace_once(
        text,
        'if line_data["type"] == "image_layer":',
        'if context.line_type == "image_layer":',
        label="image layer type",
    )
    text = replace_once(
        text,
        'if line_data["type"] == "wait":',
        'if context.line_type == "wait":',
        label="wait type",
    )
    text = replace_once(
        text,
        "                    line_image_layers = image_layers_by_line.get(idx, [])\n",
        "",
        label="wait image layers",
    )
    text = replace_once(
        text,
        '                text = line_data["text"]\n'
        '                audio_path = line_data["audio_path"]\n',
        "                text = context.text\n"
        "                audio_path = context.audio_path\n",
        label="talk text and audio",
    )
    text = replace_once(
        text,
        "                line_image_layers = image_layers_by_line.get(idx, [])\n",
        "",
        label="talk image layers",
    )
    if len(text.splitlines()) >= 850:
        raise RuntimeError("scene_standard_renderer.py did not shrink below 850 lines")
    if text.count("_build_scene_line_context(") != 1:
        raise RuntimeError("SceneLineContext is not connected exactly once")
    path.write_text(text, encoding="utf-8")


def patch_scene_renderer() -> None:
    path = VIDEO_PHASE / "scene_renderer.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from .scene_fast_path import SceneFastPathMixin\n",
        "from .scene_fast_path import SceneFastPathMixin\n"
        "from .scene_line_context import SceneLineContextMixin\n",
        label="SceneLineContext import",
    )
    text = replace_once(
        text,
        """    SceneBaseRendererMixin,
    SceneRunBasePlanMixin,
""",
        """    SceneBaseRendererMixin,
    SceneLineContextMixin,
    SceneRunBasePlanMixin,
""",
        label="SceneLineContext MRO",
    )
    path.write_text(text, encoding="utf-8")


def patch_module_split_test() -> None:
    path = ROOT / "tests/test_scene_renderer_module_split.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '        "_prepare_scene_base": "scene_base_renderer",\n',
        '        "_prepare_scene_base": "scene_base_renderer",\n'
        '        "_build_scene_line_context": "scene_line_context",\n',
        label="module split SceneLineContext",
    )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_standard_renderer()
    patch_scene_renderer()
    patch_module_split_test()


if __name__ == "__main__":
    main()
