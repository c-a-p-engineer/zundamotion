"""Video rendering components."""

from .renderer import VideoRenderer as _BaseVideoRenderer, _run_ffmpeg_async
from .overlays import OverlayMixin
from .subtitle_tail_safety import SubtitleTailSafetyMixin
from .face_overlay_cache import FaceOverlayCache


class VideoRenderer(SubtitleTailSafetyMixin, _BaseVideoRenderer):
    """Video renderer with frame-aware subtitle segment boundaries."""


__all__ = ["VideoRenderer", "OverlayMixin", "FaceOverlayCache", "_run_ffmpeg_async"]
