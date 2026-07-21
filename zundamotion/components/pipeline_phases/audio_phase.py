import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

from zundamotion.cache import CacheManager
from zundamotion.components.audio import AudioGenerator
from zundamotion.utils.subtitle_text import (
    is_effective_subtitle_text,
    normalize_subtitle_text,
)
from zundamotion.utils.ffmpeg_params import AudioParams
from zundamotion.utils.ffmpeg_audio import (
    AUDIO_MIX_VERSION,
    INTERMEDIATE_AUDIO_FORMAT_VERSION,
    apply_audio_filter,
)
from zundamotion.utils.face_anim import (
    compute_mouth_timeline,
    generate_blink_timeline,
    deterministic_seed_from_text,
)

from .audio_phase_run import AudioPhaseRunMixin


class AudioPhase(AudioPhaseRunMixin):
    def __init__(
        self,
        config: Dict[str, Any],
        temp_dir: Path,
        cache_manager: CacheManager,
        audio_params: AudioParams,
    ):
        self.config = config
        self.temp_dir = temp_dir
        self.cache_manager = cache_manager
        self.audio_params = audio_params
        self.audio_gen = AudioGenerator(
            self.config, self.temp_dir, audio_params, self.cache_manager
        )  # cache_managerを渡す
        self.video_extensions = self.config.get("system", {}).get(
            "video_extensions",
            [".mp4", ".mov", ".webm", ".avi", ".mkv"],
        )
        self.used_voicevox_info: List[Tuple[int, str]] = (
            []
        )  # Initialize list to store (speaker_id, text)
        self.audio_workers = self._determine_audio_workers()

    def _determine_audio_workers(self) -> int:
        voice_cfg = self.config.get("voice", {}) if isinstance(self.config, dict) else {}
        raw = os.getenv(
            "ZUNDAMOTION_AUDIO_WORKERS",
            voice_cfg.get("parallel_workers", "auto"),
        )
        try:
            if isinstance(raw, str):
                normalized = raw.strip().lower()
                if normalized in {"", "auto", "0"}:
                    cpu_count = os.cpu_count() or 2
                    return max(1, min(2, cpu_count))
                return max(1, int(normalized))
            return max(1, int(raw))
        except Exception:
            return 2

    @staticmethod
    def _is_face_anim_target_hidden(line: Dict[str, Any], target_name: str) -> bool:
        """Return true when the line explicitly hides the animation target."""
        for character in line.get("characters", []) or []:
            if not isinstance(character, dict):
                continue
            if character.get("name") == target_name and character.get("visible") is False:
                return True
        return False

    @staticmethod
    def _cut_duration(line: Dict[str, Any], key: str) -> float:
        cfg = line.get(key)
        raw: Any = 0.0
        if isinstance(cfg, dict):
            raw = cfg.get("duration", 0.0)
        elif cfg is not None:
            raw = cfg
        try:
            return max(0.0, float(raw or 0.0))
        except Exception:
            return 0.0
