"""Apply the scene media assembly extraction once."""

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
    start = text.index("        # 順序維持で集約\n")
    cleanup = text.index(
        "        if (\n"
        "            scene_base_path\n",
        start,
    )
    replacement = """        assembly = await self._assemble_scene_media(
            scene_id=scene_id,
            line_results=results,
            scene=scene,
            badge_line_markers=badge_line_markers,
            subtitle_entries=subtitle_entries,
        )
        if assembly is not None:
            scene_output_no_sub_path = assembly.no_sub_path
            scene_output_path = assembly.final_path
            if cache_scene_base_video:
                self.cache_manager.cache_file(
                    source_path=scene_output_no_sub_path,
                    key_data=scene_base_hash_data,
                    file_name=f"scene_{scene_id}_base",
                    extension="mp4",
                )
                logger.info(
                    "[SceneCache] scene=%s layer=base STORE key=%s subtitle_timing_key=%s file_name=scene_%s_base.mp4",
                    scene_id,
                    self._cache_key_short(scene_base_hash_data),
                    subtitle_timing_key,
                    scene_id,
                )
            if subtitle_entries:
                self.cache_manager.cache_file(
                    source_path=scene_output_path,
                    key_data=scene_sub_hash_data,
                    file_name=f"scene_{scene_id}_sub",
                    extension="mp4",
                )
                logger.info(
                    "[SceneCache] scene=%s layer=sub STORE key=%s subtitle_timing_key=%s subtitles=%d",
                    scene_id,
                    self._cache_key_short(scene_sub_hash_data),
                    subtitle_timing_key,
                    len(subtitle_entries),
                )
                if generate_no_sub_video:
                    self.cache_manager.cache_file(
                        source_path=scene_output_no_sub_path,
                        key_data=scene_hash_data,
                        file_name=f"scene_{scene_id}",
                        extension="mp4",
                    )
                    self.cache_manager.cache_file(
                        source_path=scene_output_path,
                        key_data=scene_hash_data,
                        file_name=f"scene_{scene_id}_sub",
                        extension="mp4",
                    )
            else:
                self.cache_manager.cache_file(
                    source_path=scene_output_path,
                    key_data=scene_hash_data,
                    file_name=f"scene_{scene_id}",
                    extension="mp4",
                )
            scene_results.append(scene_output_path)

"""
    text = text[:start] + replacement + text[cleanup:]
    if "concat_started =" in text or "Applied foreground overlays" in text:
        raise RuntimeError("legacy inline scene assembly remains")
    if len(text.splitlines()) >= 450:
        raise RuntimeError("scene_standard_renderer.py did not shrink below 450 lines")
    path.write_text(text, encoding="utf-8")


def patch_scene_renderer() -> None:
    path = VIDEO_PHASE / "scene_renderer.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from .scene_cache import SceneCacheMixin\n",
        "from .scene_cache import SceneCacheMixin\n"
        "from .scene_assembly import SceneAssemblyMixin\n",
        label="scene assembly import",
    )
    text = replace_once(
        text,
        """    SceneFastPathMixin,
    SceneCacheMixin,
    SceneBasePlanMixin,
""",
        """    SceneFastPathMixin,
    SceneCacheMixin,
    SceneAssemblyMixin,
    SceneBasePlanMixin,
""",
        label="scene assembly MRO",
    )
    path.write_text(text, encoding="utf-8")


def patch_module_split_test() -> None:
    path = ROOT / "tests/test_scene_renderer_module_split.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '        "_scene_base_cache_data": "scene_cache",\n',
        '        "_scene_base_cache_data": "scene_cache",\n'
        '        "_assemble_scene_media": "scene_assembly",\n',
        label="module split scene assembly",
    )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_standard_renderer()
    patch_scene_renderer()
    patch_module_split_test()


if __name__ == "__main__":
    main()
