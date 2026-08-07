"""Video rendering components."""

from .renderer import VideoRenderer as _BaseVideoRenderer, _run_ffmpeg_async
from .overlays import OverlayMixin
from .subtitle_tail_safety import SubtitleTailSafetyMixin
from .subtitle_video_segments import SubtitleVideoSegmentMixin
from .face_overlay_cache import FaceOverlayCache


class VideoRenderer(
    SubtitleTailSafetyMixin,
    SubtitleVideoSegmentMixin,
    _BaseVideoRenderer,
):
    """Video renderer with frame-aware subtitle segment boundaries."""


__all__ = [
    "VideoRenderer",
    "OverlayMixin",
    "FaceOverlayCache",
    "_run_ffmpeg_async",
]
