from types import SimpleNamespace

from zundamotion.components.pipeline_phases.video_phase.scene_fast_path_eligibility import (
    FastPathEligibility,
    FastPathLineEligibility,
    SceneFastPathEligibilityMixin,
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


def test_cpu_short_circuit_does_not_resolve_character_assets() -> None:
    class _Renderer(SceneFastPathEligibilityMixin):
        hw_kind = None
        scene = {"id": "demo", "lines": [{"characters": [{"name": "missing"}]}]}
        line_data_map = {"demo_1": {"type": "talk", "line_config": {}}}
        video_extensions = {".mp4"}
        video_renderer = SimpleNamespace(
            subtitle_gen=SimpleNamespace(subtitle_render_mode=lambda: "ass")
        )

        def _extract_simple_character_state(self, _line):
            raise AssertionError("CPU rejection must happen before character asset resolution")

        def _resolve_background_layout(self, _line_config):
            raise AssertionError("CPU rejection must happen before line layout resolution")

        def _resolve_background_source(self, _line_config, _bg_image):
            raise AssertionError("CPU rejection must happen before line background resolution")

    renderer = _Renderer()
    result = renderer._can_use_simple_scene_fast_path(
        scene_duration=1.0,
        bg_image="assets/bg/default.png",
        generate_no_sub_video=False,
        start_time_by_idx={1: 0.0},
    )
    assert result == (False, "cpu_encoder")
