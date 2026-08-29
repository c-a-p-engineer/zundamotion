import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

from zundamotion.cache import CacheManager
from zundamotion.components.audio import create_audio_generator
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
from zundamotion.utils.logger import logger

from .audio_duration_cache import AudioDurationCacheProxy
from .audio_phase_run import AudioPhaseRunMixin
from .audio_worker_policy import AudioWorkerPolicy, resolve_audio_worker_policy


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
        self.cache_manager = AudioDurationCacheProxy(cache_manager)
        self.audio_params = audio_params
        self.audio_gen = create_audio_generator(
            self.config, self.temp_dir, audio_params, self.cache_manager
        )
        self.video_extensions = self.config.get("system", {}).get(
            "video_extensions",
            [".mp4", ".mov", ".webm", ".avi", ".mkv"],
        )
        # Kept for backward-compatible VOICEVOX reporting. Other providers do
        # not fabricate numeric speaker IDs and therefore leave this list empty.
        self.used_voicevox_info: List[Tuple[int, str]] = []
        policy = self._resolve_audio_worker_policy()
        self.audio_workers = max(1, int(self._determine_audio_workers()))
        if self.audio_workers != policy.resolved:
            policy = AudioWorkerPolicy(
                requested=policy.requested,
                resolved=self.audio_workers,
                source="compatibility_override",
                automatic=False,
                fallback_reason="determine_audio_workers_override",
            )
        self.audio_worker_policy = policy
        logger.info(
            "[AudioConcurrency] requested=%s resolved=%d source=%s automatic=%s fallback=%s",
            self.audio_worker_policy.requested,
            self.audio_worker_policy.resolved,
            self.audio_worker_policy.source,
            str(self.audio_worker_policy.automatic).lower(),
            self.audio_worker_policy.fallback_reason or "none",
        )

    def _resolve_audio_worker_policy(self) -> AudioWorkerPolicy:
        voice_cfg = self.config.get("voice", {}) if isinstance(self.config, dict) else {}
        return resolve_audio_worker_policy(
            voice_cfg,
            os.environ,
            cpu_count=os.cpu_count(),
        )

    def _determine_audio_workers(self) -> int:
        """Compatibility helper retained for tests and external monkeypatches."""
        return self._resolve_audio_worker_policy().resolved

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
