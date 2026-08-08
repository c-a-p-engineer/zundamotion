"""Video rendering components."""

from .renderer import VideoRenderer as _BaseVideoRenderer, _run_ffmpeg_async
from .overlays import OverlayMixin
from .subtitle_overlay_runtime import SubtitleOverlayRuntimeMixin
from .subtitle_tail_safety import SubtitleTailSafetyMixin
from .subtitle_segment_executor import SubtitleSegmentExecutorMixin
from .subtitle_video_segments import SubtitleVideoSegmentMixin
from .wait_clip_runtime import WaitClipRuntimeMixin
from .face_overlay_cache import FaceOverlayCache


class VideoRenderer(
    WaitClipRuntimeMixin,
    SubtitleOverlayRuntimeMixin,
    SubtitleTailSafetyMixin,
    SubtitleSegmentExecutorMixin,
    SubtitleVideoSegmentMixin,
    _BaseVideoRenderer,
):
    """Video renderer with modular subtitle and finite wait-clip runtimes."""


__all__ = [
    "VideoRenderer",
    "OverlayMixin",
    "FaceOverlayCache",
    "_run_ffmpeg_async",
]
