from pathlib import Path


TARGET = Path(
    "zundamotion/components/pipeline_phases/video_phase/scene_standard_renderer.py"
)
START = "        # シーンベース映像（背景のみ）を事前生成（動画/静止画どちらでも）\n"
END = "        if should_generate_base:\n"
REPLACEMENT = '''        base_plan = self._build_scene_base_plan(
            scene=scene,
            scene_copy=scene_cp,
            is_background_video=is_bg_video,
            has_line_background_override=has_line_bg_override,
        )
        if base_plan.detection_error is not None:
            logger.debug(
                "Static overlay detection failed on scene %s: %s",
                scene_id,
                base_plan.detection_error,
            )
        static_overlays = base_plan.static_overlays
        static_char_keys = base_plan.static_character_keys
        static_insert_in_base = base_plan.static_insert_in_base
        scene_level_insert_video: Optional[Path] = None
        if base_plan.common_insert_video_path is not None:
            try:
                scene_level_insert_video = await normalize_media(
                    input_path=base_plan.common_insert_video_path,
                    video_params=self.video_params,
                    audio_params=self.audio_params,
                    cache_manager=self.cache_manager,
                )
                logger.info(
                    "Scene %s: pre-normalized common insert video -> %s",
                    scene_id,
                    scene_level_insert_video.name,
                )
                if base_plan.scene_copy:
                    scene_level_insert_video = None
            except Exception as error:
                logger.warning(
                    "Scene %s: failed to pre-normalize common insert video %s: %s",
                    scene_id,
                    base_plan.common_insert_video_path.name,
                    error,
                )

        scene_base_path: Optional[Path] = None
        normalized_bg_path: Optional[Path] = None
        total_lines_in_scene = base_plan.total_lines
        min_lines_for_base = base_plan.minimum_lines
        should_generate_base = base_plan.should_generate_base
        base_bg_layout = base_plan.base_background_layout

'''


def main() -> None:
    source = TARGET.read_text(encoding="utf-8")
    if "base_plan = self._build_scene_base_plan(" in source:
        return
    start = source.index(START)
    end = source.index(END, start)
    TARGET.write_text(
        source[:start] + REPLACEMENT + source[end:],
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
