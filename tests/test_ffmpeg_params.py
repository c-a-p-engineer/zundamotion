from zundamotion.utils.ffmpeg_params import AudioParams, VideoParams, normalize_preset_for_encoder


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


def test_audio_params_use_requested_aac_codec():
    opts = AudioParams(codec="aac").to_ffmpeg_opts()
    assert opts[opts.index("-c:a") + 1] == "aac"
    assert opts[opts.index("-profile:a") + 1] == "aac_low"


def test_audio_params_use_requested_mp3_codec():
    opts = AudioParams(codec="libmp3lame").to_ffmpeg_opts()
    assert opts[opts.index("-c:a") + 1] == "libmp3lame"


def test_pcm_audio_omits_bitrate_and_intermediate_is_pcm():
    intermediate = AudioParams(
        codec="aac", sample_rate=44100, channels=1
    ).for_intermediate()
    opts = intermediate.to_ffmpeg_opts()
    assert intermediate.codec == "pcm_s16le"
    assert (intermediate.sample_rate, intermediate.channels) == (44100, 1)
    assert "-b:a" not in opts
