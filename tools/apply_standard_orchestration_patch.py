"""Connect standard render stage mixins to the public SceneRenderer facade."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIDEO_PHASE = ROOT / "zundamotion/components/pipeline_phases/video_phase"


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def patch_scene_renderer() -> None:
    path = VIDEO_PHASE / "scene_renderer.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from .scene_run_base_renderer import SceneRunBaseRendererMixin\n"
        "from .scene_standard_renderer import SceneStandardRendererMixin\n",
        "from .scene_run_base_renderer import SceneRunBaseRendererMixin\n"
        "from .scene_standard_context import SceneStandardContextMixin\n"
        "from .scene_precache import ScenePrecacheMixin\n"
        "from .scene_line_pipeline import SceneLinePipelineMixin\n"
        "from .scene_standard_renderer import SceneStandardRendererMixin\n",
        label="standard stage imports",
    )
    text = replace_once(
        text,
        """    SceneTalkRendererMixin,
    SceneWaitRendererMixin,
    SceneStandardRendererMixin,
""",
        """    SceneTalkRendererMixin,
    SceneWaitRendererMixin,
    SceneStandardContextMixin,
    ScenePrecacheMixin,
    SceneLinePipelineMixin,
    SceneStandardRendererMixin,
""",
        label="standard stage MRO",
    )
    path.write_text(text, encoding="utf-8")


def patch_module_split_test() -> None:
    path = ROOT / "tests/test_scene_renderer_module_split.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '        "_build_scene_timing_plan": "scene_timing",\n'
        '        "_render_scene_internal": "scene_standard_renderer",\n',
        '        "_build_scene_timing_plan": "scene_timing",\n'
        '        "_prepare_standard_scene_context": "scene_standard_context",\n'
        '        "_resolve_standard_scene_cache": "scene_standard_context",\n'
        '        "_try_standard_scene_fast_path": "scene_standard_context",\n'
        '        "_precache_standard_scene_assets": "scene_precache",\n'
        '        "_prepare_standard_scene_layers": "scene_line_pipeline",\n'
        '        "_render_standard_scene_lines": "scene_line_pipeline",\n'
        '        "_render_scene_internal": "scene_standard_renderer",\n',
        label="standard stage module characterization",
    )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_scene_renderer()
    patch_module_split_test()


if __name__ == "__main__":
    main()
