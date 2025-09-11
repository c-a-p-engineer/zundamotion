"""FFmpegエンコードパラメータのデータクラス群。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class VideoParams:
    """映像エンコードの設定値を保持する。"""

    width: int = 1920
    height: int = 1080
    fps: int = 30
    pix_fmt: str = "yuv420p"
    profile: str = "high"  # H.264/HEVC プロファイル
    level: str = "4.2"  # H.264/HEVC レベル
    preset: str = "medium"  # エンコーダプリセット
    bitrate_kbps: Optional[int] = None  # ビットレート (kbps)
    crf: Optional[int] = None  # CPUエンコーダ用CRF値
    cq: Optional[int] = None  # NVENC用CQ値
    global_quality: Optional[int] = None  # QSV用
    qp: Optional[int] = None  # VAAPI/AMF用

    def to_ffmpeg_opts(self, hw_kind: Optional[str] = None) -> List[str]:
        """現在の設定をFFmpegの引数へ変換する。"""
        opts: List[str] = []
        opts.extend(["-fps_mode", "cfr"])
        opts.extend(["-r", str(self.fps)])
        opts.extend(["-s", f"{self.width}x{self.height}"])
        opts.extend(["-pix_fmt", self.pix_fmt])
        opts.extend(["-profile:v", self.profile])
        opts.extend(["-level:v", self.level])

        if hw_kind == "nvenc":
            opts.extend(["-c:v", "h264_nvenc"])
            opts.extend(["-preset", self.preset])
            if self.cq is not None:
                opts.extend(["-cq", str(self.cq)])
            elif self.bitrate_kbps is not None:
                opts.extend(["-b:v", f"{self.bitrate_kbps}k"])
            else:
                opts.extend(["-cq", "23"])
            try:
                if os.getenv("NVENC_FAST", "0") == "1":
                    opts.extend(["-rc-lookahead", "0", "-bf", "0", "-spatial_aq", "0", "-temporal_aq", "0"])
            except Exception:
                pass
        elif hw_kind == "qsv":
            opts.extend(["-c:v", "h264_qsv"])
            if self.global_quality is not None:
                opts.extend(["-global_quality", str(self.global_quality)])
            elif self.bitrate_kbps is not None:
                opts.extend(["-b:v", f"{self.bitrate_kbps}k"])
            else:
                opts.extend(["-global_quality", "23"])
        elif hw_kind == "vaapi":
            opts.extend(["-c:v", "h264_vaapi"])
            if self.qp is not None:
                opts.extend(["-qp", str(self.qp)])
            elif self.bitrate_kbps is not None:
                opts.extend(["-b:v", f"{self.bitrate_kbps}k"])
            else:
                opts.extend(["-qp", "23"])
        elif hw_kind == "amf":
            opts.extend(["-c:v", "h264_amf"])
            if self.qp is not None:
                opts.extend(["-qp", str(self.qp)])
            elif self.bitrate_kbps is not None:
                opts.extend(["-b:v", f"{self.bitrate_kbps}k"])
            else:
                opts.extend(["-qp", "23"])
        elif hw_kind == "videotoolbox":
            opts.extend(["-c:v", "h264_videotoolbox"])
            if self.bitrate_kbps is not None:
                opts.extend(["-b:v", f"{self.bitrate_kbps}k"])
            else:
                opts.extend(["-b:v", "5M"])
        else:  # CPU
            opts.extend(["-c:v", "libx264"])
            preset = self.preset
            if isinstance(preset, str) and preset.startswith("p"):
                mapping = {
                    "p7": "ultrafast",
                    "p6": "veryfast",
                    "p5": "medium",
                    "p4": "slow",
                    "p3": "slower",
                    "p2": "veryslow",
                    "p1": "veryslow",
                }
                preset = mapping.get(preset, "medium")
            opts.extend(["-preset", preset])
            if self.crf is not None:
                opts.extend(["-crf", str(self.crf)])
            elif self.bitrate_kbps is not None:
                opts.extend(["-b:v", f"{self.bitrate_kbps}k"])
            else:
                opts.extend(["-crf", "23"])

        return opts


@dataclass
class AudioParams:
    """音声エンコードの設定値を保持する。"""

    sample_rate: int = 48000
    channels: int = 2
    codec: str = "libmp3lame"
    bitrate_kbps: int = 192

    def to_ffmpeg_opts(self) -> List[str]:
        """現在の設定をFFmpegの引数へ変換する。"""
        opts: List[str] = []
        opts.extend(["-c:a", "libmp3lame"])
        opts.extend(["-b:a", f"{self.bitrate_kbps}k"])
        opts.extend(["-ar", str(self.sample_rate)])
        opts.extend(["-ac", str(self.channels)])
        return opts
