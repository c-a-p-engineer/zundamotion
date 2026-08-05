from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from zundamotion.components.pipeline_phases.audio_phase_entries import (
    prepare_audio_entries,
)


class StubTimeline:
    def __init__(self) -> None:
        self.scene_changes: list[tuple[str, str | None]] = []

    def add_scene_change(self, scene_id: str, background: str | None) -> None:
        self.scene_changes.append((scene_id, background))


def test_prepare_audio_entries_preserves_item_order_and_eager_tasks() -> None:
    async def _run() -> None:
        calls: list[tuple[str, dict[str, Any], str]] = []

        async def generate_audio(
            read_text: str,
            line: dict[str, Any],
            line_id: str,
        ):
            calls.append((read_text, line, line_id))
            return Path(f"{line_id}.wav"), [], []

        speech_line = {"text": "漢字", "reading": "かんじ"}
        timeline = StubTimeline()
        entries = prepare_audio_entries(
            scenes=[
                {
                    "id": "scene",
                    "bg": "assets/bg/room.png",
                    "items": [
                        {"topic": "Chapter"},
                        {"bgm": {"id": "main", "action": "start"}},
                        {"say": speech_line},
                        {"wait": 0.5},
                        {"image_layers": {"image_layers": [{"show": "panel"}]}},
                    ],
                }
            ],
            config={"subtitle": {"reading_display": "none"}},
            timeline=timeline,  # type: ignore[arg-type]
            generate_line_audio=generate_audio,
        )

        assert timeline.scene_changes == [("scene", "assets/bg/room.png")]
        assert [entry["entry_type"] for entry in entries] == [
            "topic",
            "bgm",
            "say",
            "wait",
            "image_layer",
        ]
        assert entries[2]["line_id"] == "scene_1"
        assert entries[3]["line_id"] == "scene_2"
        assert entries[4]["line_id"] == "scene_3"
        assert entries[2]["read_text"] == "かんじ"
        assert entries[2]["display_text"] == "漢字"

        result = await entries[2]["audio_task"]
        assert result[0] == Path("scene_1.wav")
        assert calls == [("かんじ", speech_line, "scene_1")]

    asyncio.run(_run())


def test_prepare_audio_entries_derives_legacy_lines_without_reordering() -> None:
    async def _run() -> None:
        async def generate_audio(read_text: str, line: dict[str, Any], line_id: str):
            return Path(f"{line_id}.wav"), [], []

        timeline = StubTimeline()
        entries = prepare_audio_entries(
            scenes=[
                {
                    "id": "legacy",
                    "lines": [
                        {"text": "hello"},
                        {"wait": 0.25},
                        {"image_layers": [{"show": "panel"}]},
                    ],
                }
            ],
            config={"background": {"default": "assets/bg/default.png"}},
            timeline=timeline,  # type: ignore[arg-type]
            generate_line_audio=generate_audio,
        )

        assert timeline.scene_changes == [("legacy", "assets/bg/default.png")]
        assert [entry["entry_type"] for entry in entries] == [
            "say",
            "wait",
            "image_layer",
        ]
        assert [entry["line_id"] for entry in entries] == [
            "legacy_1",
            "legacy_2",
            "legacy_3",
        ]
        await entries[0]["audio_task"]

    asyncio.run(_run())
