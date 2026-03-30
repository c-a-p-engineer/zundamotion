import asyncio
from pathlib import Path

from zundamotion.components.video.clip.face import apply_face_overlays


class _StubFaceCache:
    async def get_scaled_overlay(self, path: Path, _scale: float, _thr: int) -> Path:
        return path


class _StubRenderer:
    def __init__(self) -> None:
        self.face_cache = _StubFaceCache()


def test_apply_face_overlays_uses_line_character_fallback_when_char_is_baked_into_base(
    monkeypatch, tmp_path: Path
) -> None:
    async def _run() -> None:
        character_root = tmp_path / "assets" / "characters" / "hero" / "default"
        mouth_dir = character_root / "mouth"
        eyes_dir = character_root / "eyes"
        mouth_dir.mkdir(parents=True)
        eyes_dir.mkdir(parents=True)
        (mouth_dir / "half.png").write_bytes(b"half")
        (mouth_dir / "open.png").write_bytes(b"open")
        (eyes_dir / "close.png").write_bytes(b"close")

        monkeypatch.chdir(tmp_path)

        cmd: list[str] = []
        input_layers: list[dict[str, object]] = []
        filter_complex_parts: list[str] = []
        overlay_streams: list[str] = []
        overlay_filters: list[str] = []

        await apply_face_overlays(
            renderer=_StubRenderer(),
            face_anim={
                "target_name": "hero",
                "mouth": [{"start": 0.0, "end": 0.3, "state": "half"}],
                "eyes": [{"start": 0.4, "end": 0.45, "state": "close"}],
            },
            subtitle_line_config={
                "characters": [
                    {
                        "name": "hero",
                        "visible": True,
                        "expression": "default",
                        "anchor": "bottom_center",
                        "position": {"x": 0, "y": -20},
                        "scale": 0.85,
                    }
                ]
            },
            char_overlay_placement={},
            duration=1.0,
            cmd=cmd,
            input_layers=input_layers,
            filter_complex_parts=filter_complex_parts,
            overlay_streams=overlay_streams,
            overlay_filters=overlay_filters,
            audio_delay=0.1,
        )

        assert len(overlay_streams) == 2
        assert any("enable='between(t,0.400,0.450)'" in item for item in overlay_filters)
        assert any("enable='between(t,0.100,0.400)'" in item for item in overlay_filters)

    asyncio.run(_run())
