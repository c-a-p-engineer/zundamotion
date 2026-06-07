"""タイムライン情報を管理しレポートや字幕ファイルを生成するモジュール。"""

import csv
from pathlib import Path
from typing import Any, Dict, List, Optional

import pysubs2

from zundamotion.utils.subtitle_text import (
    is_effective_subtitle_text,
    normalize_subtitle_text,
)


def format_timestamp(seconds: float) -> str:
    """秒数を HH:MM:SS 形式の文字列に変換する。"""
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{int(h):02}:{int(m):02}:{int(s):02}"


class Timeline:
    """動画イベントを記録しタイムラインや字幕を出力する。"""

    def __init__(self):
        self.events: List[Dict[str, Any]] = []
        self.bgm_events: List[Dict[str, Any]] = []
        self.topics: List[Dict[str, Any]] = []
        self.current_time: float = 0.0

    def add_event(self, description: str, duration: float, text: Optional[str] = None):
        """タイムラインに新しいイベントを追加する。"""
        effective_text: Optional[str]
        if is_effective_subtitle_text(text):
            effective_text = normalize_subtitle_text(text)
        else:
            effective_text = None
        self.events.append(
            {
                "start_time": self.current_time,
                "duration": duration,
                "description": description,
                "text": effective_text,
            }
        )
        self.current_time += duration

    def add_scene_change(self, scene_id: str, bg: str):
        """シーン切り替えイベントを追加する。"""
        self.events.append(
            {
                "start_time": self.current_time,
                "duration": 0,
                "description": f"Scene Change (Background: {bg})",
                "type": "scene_change",
                "scene_id": scene_id,
            }
        )

    def add_bgm_event(self, bgm_id: str, action: str, fade: Optional[float] = None):
        """BGMイベントをタイムラインに追加する（時間は進めない）。"""
        self.bgm_events.append(
            {
                "time": float(self.current_time),
                "id": bgm_id,
                "action": action,
                "fade": float(fade) if fade is not None else None,
            }
        )

    def add_topic(self, title: str):
        """トピック（チャプター）を現在時刻で記録する。"""
        record = {"time": float(self.current_time), "title": title}
        if self.topics and abs(self.topics[-1]["time"] - record["time"]) < 1e-6:
            self.topics[-1] = record
        else:
            self.topics.append(record)

    def get_scene_start_time(self, scene_id: str) -> Optional[float]:
        """指定したシーンIDの開始時刻を返す。"""
        for event in self.events:
            if (
                event.get("type") == "scene_change"
                and event.get("scene_id") == scene_id
            ):
                return float(event.get("start_time", 0.0))
        return None

    def get_topics(self) -> List[Dict[str, Any]]:
        """収集したトピック一覧を返す。"""
        return list(self.topics)

    @staticmethod
    def _derive_scene_items(scene: Dict[str, Any]) -> List[Dict[str, Any]]:
        """AudioPhase と同じ規則で scene から処理順の items を取り出す。"""
        items = scene.get("items")
        if isinstance(items, list):
            return items

        lines = scene.get("lines")
        if not isinstance(lines, list):
            return []

        derived_items: List[Dict[str, Any]] = []
        for line in lines:
            if not isinstance(line, dict):
                continue
            if "wait" in line:
                derived_items.append({"wait": line})
            elif "text" in line or line.get("image_layers") is None:
                derived_items.append({"say": line})
            else:
                derived_items.append({"image_layers": line})
        return derived_items

    @staticmethod
    def format_chapter_timestamp(seconds: float) -> str:
        """YouTubeチャプター向けの時刻表現に変換する。"""
        total = max(0, int(seconds))
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        if h > 0:
            return f"{h:02}:{m:02}:{s:02}"
        return f"{m:02}:{s:02}"

    def save_chapters(self, output_path: Path) -> None:
        """チャプター一覧を保存する。"""
        with open(output_path, "w", encoding="utf-8") as f:
            for topic in self.topics:
                stamp = self.format_chapter_timestamp(topic["time"])
                f.write(f"{stamp} {topic['title']}\n")

    def resync_with_scene_durations(
        self,
        scenes: List[Dict[str, Any]],
        line_data_map: Dict[str, Dict[str, Any]],
    ) -> None:
        """最終レンダー尺に合わせてイベント、トピック、BGM時刻を再同期する。"""
        timed_events = [
            event for event in self.events if event.get("type") != "scene_change"
        ]
        scene_change_events = {
            str(event.get("scene_id")): event
            for event in self.events
            if event.get("type") == "scene_change" and event.get("scene_id") is not None
        }
        event_idx = 0
        bgm_idx = 0
        topic_idx = 0
        cursor = 0.0

        for scene in scenes:
            scene_id = str(scene.get("id", ""))
            scene_change = scene_change_events.get(scene_id)
            if scene_change is not None:
                scene_change["start_time"] = cursor

            line_idx = 0
            for item in self._derive_scene_items(scene):
                if not isinstance(item, dict):
                    continue

                if "bgm" in item:
                    if bgm_idx < len(self.bgm_events):
                        self.bgm_events[bgm_idx]["time"] = cursor
                    bgm_idx += 1
                    continue

                if "topic" in item:
                    if topic_idx < len(self.topics):
                        self.topics[topic_idx]["time"] = cursor
                    topic_idx += 1
                    continue

                if "say" in item:
                    line = item.get("say")
                    if not isinstance(line, dict):
                        line = {"text": str(line or "")}
                elif "wait" in item:
                    line = item.get("wait")
                    if isinstance(line, dict) and "wait" in line:
                        line = line
                    else:
                        line = {"wait": line}
                elif "image_layers" in item:
                    line = item.get("image_layers")
                    if not isinstance(line, dict):
                        line = {"image_layers": line}
                else:
                    continue

                line_idx += 1
                line_id = f"{scene_id}_{line_idx}"
                line_data = line_data_map.get(line_id)
                if line_data is None or event_idx >= len(timed_events):
                    continue

                duration = float(line_data.get("duration", 0.0) or 0.0)
                pre_duration = float(line_data.get("pre_duration", 0.0) or 0.0)
                post_duration = float(line_data.get("post_duration", 0.0) or 0.0)
                timed_events[event_idx]["start_time"] = cursor
                timed_events[event_idx]["duration"] = duration
                timed_events[event_idx]["subtitle_start_time"] = cursor + pre_duration
                timed_events[event_idx]["subtitle_end_time"] = max(
                    cursor + pre_duration,
                    cursor + duration - post_duration,
                )
                cursor += duration
                event_idx += 1

        self.current_time = cursor

    def insert_gap(
        self,
        gap_start: float,
        duration: float,
        description: Optional[str] = None,
        text: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """指定時刻以降のイベントを後ろへずらし、ギャップイベントを挿入する。"""

        if duration <= 0:
            return

        adjusted_start = max(0.0, gap_start)
        for event in self.events:
            if event.get("start_time", 0.0) >= adjusted_start:
                event["start_time"] = float(event.get("start_time", 0.0)) + duration
        for topic in self.topics:
            if topic.get("time", 0.0) >= adjusted_start:
                topic["time"] = float(topic.get("time", 0.0)) + duration

        new_event: Optional[Dict[str, Any]] = None
        if description or metadata:
            gap_text: Optional[str]
            if is_effective_subtitle_text(text):
                gap_text = normalize_subtitle_text(text)
            else:
                gap_text = None
            new_event = {
                "start_time": adjusted_start,
                "duration": duration,
                "description": description or "",
                "text": gap_text,
            }
            if metadata:
                new_event.update(metadata)

        if new_event:
            insert_idx = len(self.events)
            threshold = adjusted_start + duration - 1e-9
            for idx, event in enumerate(self.events):
                if float(event.get("start_time", 0.0)) >= threshold:
                    insert_idx = idx
                    break
            self.events.insert(insert_idx, new_event)

        self.current_time += duration

    def shift_from(
        self,
        start_time: float,
        delta: float,
        *,
        include_at_start: bool = True,
    ) -> None:
        """指定時刻以降のイベントとチャプターをまとめてずらす。"""

        if abs(delta) <= 1e-9:
            return

        threshold = max(0.0, start_time)

        def should_shift(value: float) -> bool:
            if include_at_start:
                return value >= threshold
            return value > threshold

        for event in self.events:
            current = float(event.get("start_time", 0.0))
            if should_shift(current):
                event["start_time"] = max(0.0, current + delta)

        for topic in self.topics:
            current = float(topic.get("time", 0.0))
            if should_shift(current):
                topic["time"] = max(0.0, current + delta)

        self.current_time = max(0.0, self.current_time + delta)

    def save_as_md(self, output_path: Path):
        """タイムラインを Markdown 形式で保存する。"""
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("# Video Timeline\n\n")
            for event in self.events:
                timestamp = format_timestamp(event["start_time"])
                f.write(f"- {timestamp} - {event['description']}\n")

    def save_as_csv(self, output_path: Path):
        """タイムラインを CSV 形式で保存する。"""
        with open(output_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["start_time", "duration", "description"])
            for event in self.events:
                writer.writerow(
                    [
                        format_timestamp(event["start_time"]),
                        event["duration"],
                        event["description"],
                    ]
                )

    def save_subtitles(
        self,
        output_path: Path,
        format: str,
        offset_seconds: float = 0.0,
    ):
        """字幕ファイルを SRT または ASS 形式で保存する。"""
        subs = pysubs2.SSAFile()
        target_format = (format or "srt").lower()
        offset_ms = int(round(float(offset_seconds or 0.0) * 1000))
        for event in self.events:
            text = event.get("text")
            if not is_effective_subtitle_text(text):
                continue
            subtitle_start = float(
                event.get("subtitle_start_time", event["start_time"])
            )
            subtitle_end = float(
                event.get(
                    "subtitle_end_time",
                    float(event["start_time"]) + float(event["duration"]),
                )
            )
            start_time = max(0, int(subtitle_start * 1000) + offset_ms)
            end_time = max(
                start_time + 1,
                int(subtitle_end * 1000) + offset_ms,
            )
            payload = normalize_subtitle_text(str(text))
            if target_format == "ass":
                payload = payload.replace("\n", r"\N")
            line = pysubs2.SSAEvent(start=start_time, end=end_time, text=payload)
            subs.append(line)
        subs.save(str(output_path), format=target_format)
