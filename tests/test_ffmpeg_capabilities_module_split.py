from __future__ import annotations

import inspect

from zundamotion.utils import ffmpeg_capabilities as caps
from zundamotion.utils import ffmpeg_capability_listing as listing
from zundamotion.utils import ffmpeg_encoder_capabilities as encoder
from zundamotion.utils import ffmpeg_filter_smoke as smoke
from zundamotion.utils import ffmpeg_threading as threading


def test_capabilities_facade_exports_modular_entrypoints() -> None:
    expected = {
        "get_ffmpeg_version": ".ffmpeg_capability_listing",
        "is_nvenc_available": ".ffmpeg_encoder_capabilities",
        "get_encoder_options": ".ffmpeg_encoder_capabilities",
        "smoke_test_cuda_filters": ".ffmpeg_filter_smoke",
        "get_filter_diagnostics": ".ffmpeg_filter_smoke",
        "_threading_flags": ".ffmpeg_threading",
    }
    for name, suffix in expected.items():
        exported = getattr(caps, name)
        assert exported.__module__.endswith(suffix), (name, exported.__module__)


def test_capability_entrypoints_are_bounded() -> None:
    targets = [
        listing.get_ffmpeg_version,
        listing.get_preferred_cuda_scale_filter,
        encoder.is_nvenc_available,
        encoder.get_hardware_encoder_kind,
        encoder.get_encoder_options,
        encoder.get_hw_encoder_kind_for_video_params,
        smoke.smoke_test_cuda_filters,
        smoke.smoke_test_cuda_scale_only,
        smoke.smoke_test_opencl_filters,
        smoke.smoke_test_opencl_scale_only,
        smoke.get_filter_diagnostics,
        threading._threading_flags,
    ]
    for target in targets:
        lines, _ = inspect.getsourcelines(target)
        assert len(lines) <= 80, (target.__module__, target.__name__, len(lines))
