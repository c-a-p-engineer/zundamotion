"""Add explicit video-only mode to subtitle burn execution once."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OVERLAYS = ROOT / "zundamotion/components/video/overlays.py"


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    text = OVERLAYS.read_text(encoding="utf-8")
    method_start = text.index("    async def _apply_subtitle_overlays_full(\n")
    method_text = text[method_start:]
    method_text = replace_once(
        method_text,
        """        scene_id: Optional[str] = None,
        chunk_index: Optional[int] = None,
    ) -> Path:
""",
        """        scene_id: Optional[str] = None,
        chunk_index: Optional[int] = None,
        video_only: bool = False,
    ) -> Path:
""",
        label="video-only subtitle burn parameter",
    )
    method_text = replace_once(
        method_text,
        """        cmd.extend(["-filter_complex", filter_complex, "-map", prev_stream, "-map", "0:a?"])
        cmd.extend(self._subtitle_burn_video_opts(subtitle_mode))
        cmd.extend(["-c:a", "copy"])
""",
        """        cmd.extend(["-filter_complex", filter_complex, "-map", prev_stream])
        if video_only:
            cmd.append("-an")
        else:
            cmd.extend(["-map", "0:a?"])
        cmd.extend(self._subtitle_burn_video_opts(subtitle_mode))
        if not video_only:
            cmd.extend(["-c:a", "copy"])
""",
        label="video-only subtitle burn mapping",
    )
    text = text[:method_start] + method_text
    OVERLAYS.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
