"""Build bounded FFmpeg image inputs for one clip."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Union


def _number_text(value: Union[int, float]) -> str:
    return f"{float(value):.9f}".rstrip("0").rstrip(".")


def append_looped_image_input(
    cmd: List[str],
    path: Path,
    *,
    duration: Optional[float] = None,
    fps: Optional[float] = None,
    loop: str = "1",
) -> None:
    """Append a looped image input, bounded to the clip when timing is known.

    Finite image streams avoid intermittent FFmpeg framesync stalls near EOF in
    CPU overlay-heavy clips. Callers outside the per-clip path may omit timing
    to preserve their existing input contract.
    """

    cmd.extend(["-loop", str(loop)])
    if fps is not None and float(fps) > 0:
        cmd.extend(["-framerate", _number_text(fps)])
    if duration is not None and float(duration) > 0:
        cmd.extend(["-t", _number_text(duration)])
    cmd.extend(["-i", str(path)])
