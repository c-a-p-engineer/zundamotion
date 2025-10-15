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

    def get_scene_start_time(self, scene_id: str) -> Optional[float]:
        """指定したシーンIDの開始時刻を返す。"""
        for event in self.events:
            if (
                event.get("type") == "scene_change"
                and event.get("scene_id") == scene_id
            ):
                return float(event.get("start_time", 0.0))
        return None

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

    def save_subtitles(self, output_path: Path, format: str):
        """字幕ファイルを SRT または ASS 形式で保存する。"""
        subs = pysubs2.SSAFile()
        target_format = (format or "srt").lower()
        for event in self.events:
            text = event.get("text")
            if not is_effective_subtitle_text(text):
                continue
            start_time = int(event["start_time"] * 1000)
            end_time = int((event["start_time"] + event["duration"]) * 1000)
            payload = normalize_subtitle_text(str(text))
            if target_format == "ass":
                payload = payload.replace("\n", r"\N")
            line = pysubs2.SSAEvent(start=start_time, end=end_time, text=payload)
            subs.append(line)
        subs.save(str(output_path), format=target_format)
