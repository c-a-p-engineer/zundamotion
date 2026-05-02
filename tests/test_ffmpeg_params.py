from zundamotion.utils.ffmpeg_params import VideoParams, normalize_preset_for_encoder


def test_normalize_preset_for_encoder_maps_x264_speed_to_nvenc():
    assert normalize_preset_for_encoder("ultrafast", "nvenc") == "p1"
    assert normalize_preset_for_encoder("veryfast", "nvenc") == "p2"
    assert normalize_preset_for_encoder("medium", "nvenc") == "medium"


def test_video_params_does_not_pass_x264_preset_to_nvenc():
    opts = VideoParams(preset="veryfast").to_ffmpeg_opts("nvenc")

    assert "-preset" in opts
    assert opts[opts.index("-preset") + 1] == "p2"


def test_video_params_maps_nvenc_preset_to_x264_when_cpu():
    opts = VideoParams(preset="p1").to_ffmpeg_opts(None)

    assert "-preset" in opts
    assert opts[opts.index("-preset") + 1] == "ultrafast"
