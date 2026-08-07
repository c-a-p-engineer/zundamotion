from zundamotion.components.pipeline_phases.video_phase.scene_fast_path_eligibility import (
    FastPathEligibility,
    FastPathLineEligibility,
    evaluate_fast_path_eligibility,
)


def _line(**overrides) -> FastPathLineEligibility:
    values = {
        "index": 1,
        "line_type": "talk",
        "has_complex_media": False,
        "has_voice_layers": False,
        "has_effects": False,
        "has_video_filter": False,
        "background_fit": "stretch",
        "has_background": True,
        "background_is_video": False,
        "has_start_time": True,
        "character_error": None,
    }
    values.update(overrides)
    return FastPathLineEligibility(**values)


def _facts(**overrides) -> FastPathEligibility:
    values = {
        "has_hw_encoder": True,
        "generate_no_sub_video": False,
        "scene_background_is_static_image": True,
        "has_foreground_overlays": False,
        "scene_duration": 1.0,
        "subtitle_mode": "ass",
        "lines": (_line(),),
    }
    values.update(overrides)
    return FastPathEligibility(**values)


def test_fast_path_eligibility_accepts_legacy_simple_gpu_scene() -> None:
    assert evaluate_fast_path_eligibility(_facts()) == (True, "ok")


def test_fast_path_eligibility_keeps_cpu_rejection_first() -> None:
    facts = _facts(
        has_hw_encoder=False,
        generate_no_sub_video=True,
        lines=(_line(line_type="wait"),),
    )
    assert evaluate_fast_path_eligibility(facts) == (False, "cpu_encoder")


def test_fast_path_eligibility_keeps_first_line_failure_reason() -> None:
    facts = _facts(
        lines=(
            _line(index=1),
            _line(index=2, has_effects=True),
            _line(index=3, has_complex_media=True),
        )
    )
    assert evaluate_fast_path_eligibility(facts) == (False, "effects:2")
