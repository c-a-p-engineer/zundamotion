from __future__ import annotations

from typing import Any

from zundamotion.components.pipeline_phases.audio_phase_control import (
    build_non_speech_line,
    register_control_entry,
    take_pending_audio_overlay,
)


class StubTimeline:
    def __init__(self) -> None:
        self.bgm_events: list[tuple[str, str, Any]] = []
        self.topics: list[str] = []
        self.events: list[tuple[str, float, str | None]] = []

    def add_bgm_event(self, bgm_id: str, action: str, fade: Any = None) -> None:
        self.bgm_events.append((bgm_id, action, fade))

    def add_topic(self, topic: str) -> None:
        self.topics.append(topic)

    def add_event(self, title: str, duration: float, text: str | None = None) -> None:
        self.events.append((title, duration, text))


def test_register_control_entry_preserves_bgm_and_topic_payloads() -> None:
    timeline = StubTimeline()

    assert register_control_entry(
        {
            "entry_type": "bgm",
            "bgm_cfg": {"id": "main", "action": "start", "fade": 0.5},
        },
        timeline,  # type: ignore[arg-type]
    )
    assert register_control_entry(
        {"entry_type": "topic", "topic": "Chapter"},
        timeline,  # type: ignore[arg-type]
    )
    assert not register_control_entry(
        {"entry_type": "say"},
        timeline,  # type: ignore[arg-type]
    )

    assert timeline.bgm_events == [("main", "start", 0.5)]
    assert timeline.topics == ["Chapter"]


def test_build_non_speech_line_preserves_wait_and_l_cut_overlay() -> None:
    timeline = StubTimeline()
    overlay = {"path": "voice.wav", "duration": 0.2}

    result = build_non_speech_line(
        entry={
            "entry_type": "wait",
            "scene_id": "scene",
            "line_idx": 2,
            "line_id": "scene_2",
            "line": {"wait": {"duration": 0.75}},
        },
        timeline=timeline,  # type: ignore[arg-type]
        incoming_audio_overlays=take_pending_audio_overlay(overlay),
    )

    assert result is not None
    assert result.line_id == "scene_2"
    assert result.line_data["type"] == "wait"
    assert result.line_data["duration"] == 0.75
    assert result.line_data["extra_audio_overlays"] == [overlay]
    assert timeline.events == [("(Wait 0.75s)", 0.75, None)]


def test_build_non_speech_line_preserves_image_layer_shape() -> None:
    timeline = StubTimeline()
    line = {"image_layers": [{"show": "panel"}]}

    result = build_non_speech_line(
        entry={
            "entry_type": "image_layer",
            "scene_id": "scene",
            "line_idx": 3,
            "line_id": "scene_3",
            "line": line,
        },
        timeline=timeline,  # type: ignore[arg-type]
        incoming_audio_overlays=[],
    )

    assert result is not None
    assert result.line_data == {
        "type": "image_layer",
        "duration": 0.0,
        "line_config": line,
        "audio_path": None,
        "text": None,
        "extra_audio_overlays": [],
    }
    assert timeline.events == [("(Image Layer)", 0.0, None)]
