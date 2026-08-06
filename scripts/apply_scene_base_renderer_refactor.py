from pathlib import Path


TARGET = Path(
    "zundamotion/components/pipeline_phases/video_phase/scene_standard_renderer.py"
)
START = "        static_overlays = base_plan.static_overlays\n"
END = "        # 連続行で静的レイヤが不変な“ラン”のベース（行ブロック前処理）を検討\n"
REPLACEMENT = '''        base_result = await self._prepare_scene_base(
            scene_id=scene_id,
            background=bg_image,
            is_background_video=is_bg_video,
            scene_duration=scene_duration,
            plan=base_plan,
        )
        static_overlays = base_plan.static_overlays
        static_char_keys = base_plan.static_character_keys
        static_insert_in_base = base_plan.static_insert_in_base
        scene_level_insert_video = base_result.scene_level_insert_video
        scene_base_path = base_result.scene_base_path
        normalized_bg_path = base_result.normalized_background_path

'''


def main() -> None:
    source = TARGET.read_text(encoding="utf-8")
    if "base_result = await self._prepare_scene_base(" in source:
        return
    start = source.index(START)
    end = source.index(END, start)
    source = source[:start] + REPLACEMENT + source[end:]
    source = source.replace(
        "from ....utils.ffmpeg_ops import normalize_media\n",
        "",
        1,
    )
    TARGET.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
