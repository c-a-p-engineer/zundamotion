"""Apply the scene completion extraction once."""

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
    start = text.index(
        "        if (\n"
        "            scene_base_path\n"
    )
    return_line = text.index("        return scene_results\n", start)
    removed = text[start:return_line]
    if "scene_base_path.unlink()" not in removed or "pbar_scenes.update(1)" not in removed:
        raise RuntimeError("legacy scene completion block changed unexpectedly")
    replacement = "        self._complete_scene_render(scene_base_path)\n"
    text = text[:start] + replacement + text[return_line:]
    if "scene_base_path.unlink()" in text:
        raise RuntimeError("legacy inline scene-base cleanup remains")
    if len(text.splitlines()) >= 400:
        raise RuntimeError("scene_standard_renderer.py did not shrink below 400 lines")
    path.write_text(text, encoding="utf-8")


def patch_scene_renderer() -> None:
    path = VIDEO_PHASE / "scene_renderer.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from .scene_result_cache import SceneResultCacheMixin\n",
        "from .scene_result_cache import SceneResultCacheMixin\n"
        "from .scene_completion import SceneCompletionMixin\n",
        label="scene completion import",
    )
    text = replace_once(
        text,
        """    SceneAssemblyMixin,
    SceneResultCacheMixin,
    SceneBasePlanMixin,
""",
        """    SceneAssemblyMixin,
    SceneResultCacheMixin,
    SceneCompletionMixin,
    SceneBasePlanMixin,
""",
        label="scene completion MRO",
    )
    path.write_text(text, encoding="utf-8")


def patch_module_split_test() -> None:
    path = ROOT / "tests/test_scene_renderer_module_split.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '        "_store_scene_result_cache": "scene_result_cache",\n',
        '        "_store_scene_result_cache": "scene_result_cache",\n'
        '        "_complete_scene_render": "scene_completion",\n',
        label="module split scene completion",
    )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_standard_renderer()
    patch_scene_renderer()
    patch_module_split_test()


if __name__ == "__main__":
    main()
