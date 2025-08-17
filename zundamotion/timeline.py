import csv
from pathlib import Path
from typing import Any, Dict, List


def format_timestamp(seconds: float) -> str:
    """Converts seconds to HH:MM:SS format."""
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{int(h):02}:{int(m):02}:{int(s):02}"


class Timeline:
    def __init__(self):
        self.events: List[Dict[str, Any]] = []
        self.current_time: float = 0.0

    def add_event(self, description: str, duration: float):
        """Adds a new event to the timeline."""
        self.events.append(
            {
                "start_time": self.current_time,
                "duration": duration,
                "description": description,
            }
        )
        self.current_time += duration

    def add_scene_change(self, scene_id: str, bg: str):
        """Adds a scene change event."""
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
        """Saves the timeline as a Markdown file."""
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("# Video Timeline\n\n")
            for event in self.events:
                timestamp = format_timestamp(event["start_time"])
                f.write(f"- {timestamp} - {event['description']}\n")

    def save_as_csv(self, output_path: Path):
        """Saves the timeline as a CSV file."""
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
