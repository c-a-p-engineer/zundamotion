"""Apply the scene result cache extraction once."""

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
    start = text.index("        if assembly is not None:\n")
    cleanup = text.index(
        "        if (\n"
        "            scene_base_path\n",
        start,
    )
    replacement = """        if assembly is not None:
            scene_results.append(
                self._store_scene_result_cache(
                    scene_id=scene_id,
                    assembly=assembly,
                    cache_scene_base_video=cache_scene_base_video,
                    subtitle_entries=subtitle_entries,
                    generate_no_sub_video=generate_no_sub_video,
                    scene_hash_data=scene_hash_data,
                    scene_base_hash_data=scene_base_hash_data,
                    scene_sub_hash_data=scene_sub_hash_data,
                    subtitle_timing_key=subtitle_timing_key,
                )
            )

"""
    text = text[:start] + replacement + text[cleanup:]
    if "self.cache_manager.cache_file(\n" in text[start:cleanup]:
        raise RuntimeError("legacy inline scene result cache remains")
    if len(text.splitlines()) >= 410:
        raise RuntimeError("scene_standard_renderer.py did not shrink below 410 lines")
    path.write_text(text, encoding="utf-8")


def patch_scene_renderer() -> None:
    path = VIDEO_PHASE / "scene_renderer.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from .scene_assembly import SceneAssemblyMixin\n",
        "from .scene_assembly import SceneAssemblyMixin\n"
        "from .scene_result_cache import SceneResultCacheMixin\n",
        label="scene result cache import",
    )
    text = replace_once(
        text,
        """    SceneCacheMixin,
    SceneAssemblyMixin,
    SceneBasePlanMixin,
""",
        """    SceneCacheMixin,
    SceneAssemblyMixin,
    SceneResultCacheMixin,
    SceneBasePlanMixin,
""",
        label="scene result cache MRO",
    )
    path.write_text(text, encoding="utf-8")


def patch_module_split_test() -> None:
    path = ROOT / "tests/test_scene_renderer_module_split.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '        "_assemble_scene_media": "scene_assembly",\n',
        '        "_assemble_scene_media": "scene_assembly",\n'
        '        "_store_scene_result_cache": "scene_result_cache",\n',
        label="module split scene result cache",
    )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_standard_renderer()
    patch_scene_renderer()
    patch_module_split_test()


if __name__ == "__main__":
    main()
