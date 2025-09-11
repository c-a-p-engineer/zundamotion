"""タイムライン情報を管理しレポートや字幕ファイルを生成するモジュール。"""

import csv
from pathlib import Path
from typing import Any, Dict, List, Optional

import pysubs2


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
        self.events.append(
            {
                "start_time": self.current_time,
                "duration": duration,
                "description": description,
                "text": text,
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
        for event in self.events:
            if event.get("text"):
                start_time = int(event["start_time"] * 1000)
                end_time = int((event["start_time"] + event["duration"]) * 1000)
                line = pysubs2.SSAEvent(
                    start=start_time, end=end_time, text=event["text"]
                )
                subs.append(line)
        subs.save(str(output_path), format=format)
