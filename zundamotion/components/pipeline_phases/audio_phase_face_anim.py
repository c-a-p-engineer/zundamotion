"""Build mouth and blink timelines for AudioPhase line results."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from zundamotion.utils.face_anim import (
    deterministic_seed_from_text,
    generate_blink_timeline,
)
from zundamotion.utils.logger import logger


@dataclass(frozen=True)
class FaceAnimSettings:
    mouth_fps: int
    threshold_half: float
    threshold_open: float
    video_fps: int
    blink_min_interval: float
    blink_max_interval: float
    blink_close_frames: int

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "FaceAnimSettings":
        video_config = config.get("video", {}) or {}
        animation = video_config.get("face_anim", {}) or {}
        return cls(
            mouth_fps=int(animation.get("mouth_fps", 15)),
            threshold_half=float(animation.get("mouth_thr_half", 0.2)),
            threshold_open=float(animation.get("mouth_thr_open", 0.5)),
            video_fps=int(video_config.get("fps", 30)),
            blink_min_interval=float(animation.get("blink_min_interval", 2.0)),
            blink_max_interval=float(animation.get("blink_max_interval", 5.0)),
            blink_close_frames=int(animation.get("blink_close_frames", 2)),
        )

    def metadata(self) -> Dict[str, Any]:
        return {
            "mouth_fps": self.mouth_fps,
            "thr_half": self.threshold_half,
            "thr_open": self.threshold_open,
            "blink_min_interval": self.blink_min_interval,
            "blink_max_interval": self.blink_max_interval,
            "blink_close_frames": self.blink_close_frames,
        }


class MouthSegmentLoader:
    """Load and cache mouth timelines while preserving the public monkeypatch seam."""

    def __init__(self, phase: Any, line_id: str, settings: FaceAnimSettings) -> None:
        self.phase = phase
        self.line_id = line_id
        self.settings = settings
        self._memory_cache: Dict[str, List[Dict[str, Any]]] = {}

    async def load(self, audio_path: Path) -> List[Dict[str, Any]]:
        resolved = self._resolve_path(audio_path)
        cache_key = str(resolved)
        if cache_key in self._memory_cache:
            return self._memory_cache[cache_key]
        segments = await self._load_cached(audio_path, resolved)
        self._memory_cache[cache_key] = segments
        return segments

    @staticmethod
    def _resolve_path(audio_path: Path) -> Path:
        try:
            return audio_path.resolve(strict=False)
        except Exception:
            return audio_path.absolute()

    def _compute(self, audio_path: Path) -> List[Dict[str, Any]]:
        from . import audio_phase as audio_phase_module

        return audio_phase_module.compute_mouth_timeline(
            audio_path,
            fps=self.settings.mouth_fps,
            thr_half_ratio=self.settings.threshold_half,
            thr_open_ratio=self.settings.threshold_open,
        )

    async def _load_cached(
        self,
        audio_path: Path,
        resolved: Path,
    ) -> List[Dict[str, Any]]:
        try:
            stat = audio_path.stat()
            key_data = {
                "op": "mouth_timeline",
                "audio_path": str(resolved),
                "size": stat.st_size,
                "mtime": int(stat.st_mtime),
                "fps": self.settings.mouth_fps,
                "thr_half": self.settings.threshold_half,
                "thr_open": self.settings.threshold_open,
            }

            async def creator(output_path: Path) -> Path:
                output_path.write_text(
                    json.dumps(
                        {"segments": self._compute(audio_path)},
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                return output_path

            cache_path = await self.phase.cache_manager.get_or_create(
                key_data=key_data,
                file_name="face_mouth",
                extension="json",
                creator_func=creator,
            )
            payload = json.loads(cache_path.read_text(encoding="utf-8")) or {}
            return payload.get("segments", [])
        except Exception:
            try:
                return self._compute(audio_path)
            except Exception as exc:
                logger.debug(
                    "Mouth timeline computation failed for %s: %s",
                    self.line_id,
                    exc,
                )
                return []


def _blink_segments(
    *,
    duration: float,
    seed_text: str,
    settings: FaceAnimSettings,
) -> List[Dict[str, Any]]:
    return generate_blink_timeline(
        duration=duration,
        fps=settings.video_fps,
        min_interval_sec=settings.blink_min_interval,
        max_interval_sec=settings.blink_max_interval,
        close_frames=settings.blink_close_frames,
        seed=deterministic_seed_from_text(seed_text),
    )


def _default_target_name(
    line: Dict[str, Any],
    voice_layers: List[Dict[str, Any]],
) -> Optional[str]:
    target_name = line.get("speaker_name")
    if not target_name:
        for character in line.get("characters") or []:
            if not isinstance(character, dict):
                continue
            if character.get("visible", False) and character.get("name"):
                target_name = character.get("name")
                break
    if not target_name:
        for layer in voice_layers:
            if layer.get("speaker_name"):
                target_name = layer.get("speaker_name")
                break
    return str(target_name) if target_name else None


async def _layer_mouth_segments(
    *,
    layer_index: int,
    layer_config: Dict[str, Any],
    line_mouth_sync: bool,
    voice_layer_segments: List[Dict[str, Any]],
    loader: MouthSegmentLoader,
) -> List[Dict[str, Any]]:
    if not bool(layer_config.get("mouth_sync", line_mouth_sync)):
        return []
    combined: List[Dict[str, Any]] = []
    for segment_info in voice_layer_segments:
        if segment_info.get("layer_origin") != layer_index:
            continue
        raw_path = segment_info.get("audio_path")
        if not raw_path:
            continue
        try:
            audio_path = raw_path if isinstance(raw_path, Path) else Path(str(raw_path))
        except Exception:
            continue
        offset = float(segment_info.get("start_time", 0.0))
        for segment in await loader.load(audio_path):
            start = float(segment.get("start", 0.0)) + offset
            end = float(segment.get("end", 0.0)) + offset
            if end > start:
                combined.append(
                    {"start": start, "end": end, "state": segment.get("state")}
                )
    combined.sort(key=lambda item: item["start"])
    return combined


async def _build_layer_animations(
    *,
    phase: Any,
    line_id: str,
    line: Dict[str, Any],
    duration: float,
    voice_layers: List[Dict[str, Any]],
    voice_layer_segments: List[Dict[str, Any]],
    loader: MouthSegmentLoader,
    settings: FaceAnimSettings,
) -> List[Dict[str, Any]]:
    animations: List[Dict[str, Any]] = []
    line_mouth_sync = bool(line.get("mouth_sync", True))
    for index, layer in enumerate(voice_layers):
        target_name = layer.get("speaker_name")
        if not target_name or phase._is_face_anim_target_hidden(line, str(target_name)):
            continue
        if not any(
            segment.get("layer_origin") == index for segment in voice_layer_segments
        ):
            continue
        animations.append(
            {
                "target_name": target_name,
                "mouth": await _layer_mouth_segments(
                    layer_index=index,
                    layer_config=layer,
                    line_mouth_sync=line_mouth_sync,
                    voice_layer_segments=voice_layer_segments,
                    loader=loader,
                ),
                "eyes": _blink_segments(
                    duration=duration,
                    seed_text=f"{line_id}:{target_name}",
                    settings=settings,
                ),
                "meta": settings.metadata(),
            }
        )
    return animations


async def build_face_animation(
    *,
    phase: Any,
    line_id: str,
    line: Dict[str, Any],
    audio_path: Path,
    duration: float,
    voice_layer_segments: List[Dict[str, Any]],
) -> Optional[Any]:
    """Return per-layer or single-target face animation metadata."""
    settings = FaceAnimSettings.from_config(phase.config)
    loader = MouthSegmentLoader(phase, line_id, settings)
    voice_layers = [
        layer for layer in (line.get("voice_layers") or []) if isinstance(layer, dict)
    ]
    if voice_layers and voice_layer_segments:
        animations = await _build_layer_animations(
            phase=phase,
            line_id=line_id,
            line=line,
            duration=duration,
            voice_layers=voice_layers,
            voice_layer_segments=voice_layer_segments,
            loader=loader,
            settings=settings,
        )
        if animations:
            return animations

    target_name = _default_target_name(line, voice_layers)
    if not target_name or phase._is_face_anim_target_hidden(line, target_name):
        return None
    try:
        mouth = (
            await loader.load(audio_path) if bool(line.get("mouth_sync", True)) else []
        )
        return {
            "target_name": target_name,
            "mouth": mouth,
            "eyes": _blink_segments(
                duration=duration,
                seed_text=line_id,
                settings=settings,
            ),
            "meta": settings.metadata(),
        }
    except Exception as exc:
        logger.debug(
            "Face animation timeline generation failed for %s: %s",
            line_id,
            exc,
        )
        return None
