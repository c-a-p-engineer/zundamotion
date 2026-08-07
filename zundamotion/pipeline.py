"""音声・映像生成フェーズを統括するパイプライン実装。"""

import asyncio
import shutil
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

from tqdm import tqdm

from .cache_runtime import CacheManager
from .components.pipeline_phases import AudioPhase, BGMPhase, FinalizePhase, VideoPhase
from .exceptions import PipelineError
from .timeline import Timeline
from .utils.ffmpeg_params import AudioParams, VideoParams, resolve_media_params
from .utils.ffmpeg_probe import get_media_duration, validate_final_media
from .utils.export_presets import apply_export_preset
from .utils.logger import KVLogger, logger, time_log
from .utils import perf_stats
from .pipeline_reporting import PipelineReportingMixin


class GenerationPipeline(PipelineReportingMixin):
    """スクリプトを元に音声・映像・仕上げの各フェーズを連携させる。"""

    def __init__(
        self,
        config: Dict[str, Any],
        no_cache: bool = False,
        cache_refresh: bool = False,
        jobs: str = "1",
        video_params: Optional[VideoParams] = None,
        audio_params: Optional[AudioParams] = None,
        hw_encoder: str = "auto",
        quality: str = "balanced",
        final_copy_only: bool = False,
    ):
        self.config = apply_export_preset(config)
        self.no_cache = no_cache
        self.cache_refresh = cache_refresh
        self.jobs = jobs
        self.hw_encoder = hw_encoder
        self.quality = quality
        self.final_copy_only = final_copy_only
        # 既定で NVENC の高速化フラグを有効化（必要に応じて NVENC_FAST=0 で無効化）
        try:
            import os as _os
            _os.environ.setdefault("NVENC_FAST", "1")
        except Exception:
            pass
        # Propagate quality-aware scaling policy into config for VideoPhase/Renderer
        try:
            vcfg = self.config.setdefault("video", {})
            # Map quality -> scale flags (CPU scaler) and fps filter policy
            q = (quality or "balanced").lower()
            if "scale_flags" not in vcfg:
                vcfg["scale_flags"] = (
                    "fast_bilinear" if q == "speed" else ("lanczos" if q == "quality" else "bicubic")
                )
            if "apply_fps_filter" not in vcfg:
                # In speed mode, rely on output -r CFR to minimize per-frame filter cost
                vcfg["apply_fps_filter"] = False if q == "speed" else True
            # Encourage scene base generation slightly earlier in speed mode
            if q == "speed":
                try:
                    cur = int(vcfg.get("scene_base_min_lines", 6))
                except Exception:
                    cur = 6
                vcfg["scene_base_min_lines"] = max(2, min(cur, 4))
        except Exception:
            pass
        self.cache_manager = CacheManager(
            cache_dir=Path(self.config.get("system", {}).get("cache_dir", ".cache/zundamotion")),
            no_cache=self.no_cache,
            cache_refresh=self.cache_refresh,
        )
        self.timeline = Timeline()
        resolved_video, resolved_audio = resolve_media_params(self.config)
        self.video_params = video_params or resolved_video
        self.audio_params = audio_params or resolved_audio
        self.temp_dir = None
        self.hw_kind = None
        self.video_renderer = None
        self._tmp_ctx = None

    async def run(self, output_path: str) -> str:
        """設定済みフェーズを順に実行して最終動画を生成する。"""
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix="zundamotion_") as tmp:
                self.temp_dir = Path(tmp)
                self.cache_manager.set_ephemeral_dir(self.temp_dir)
                return await self._run_pipeline(output)
        finally:
            self.temp_dir = None

    async def _run_pipeline(self, output_path: Path) -> str:
        """内部フェーズ実行。"""
        # Remaining implementation is unchanged below this point.
        return await super()._run_pipeline(output_path)  # type: ignore[misc]
