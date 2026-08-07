from zundamotion.components.pipeline_phases.video_phase.scene_renderer import (
    SceneRenderer,
)


def test_scene_renderer_public_facade_keeps_internal_responsibilities() -> None:
    method_modules = {
        "_resolve_background_layout": "scene_preparation",
        "_render_simple_scene_fast": "scene_fast_path",
        "_scene_base_cache_data": "scene_cache",
        "_assemble_scene_media": "scene_assembly",
        "_store_scene_result_cache": "scene_result_cache",
        "_complete_scene_render": "scene_completion",
        "_build_scene_base_plan": "scene_base_plan",
        "_prepare_scene_base": "scene_base_renderer",
        "_build_scene_line_context": "scene_line_context",
        "_execute_scene_lines": "scene_line_executor",
        "_record_talk_line_metrics": "scene_line_metrics",
        "_maybe_retune_line_workers": "scene_line_metrics",
        "_render_wait_line": "scene_wait_renderer",
        "_build_scene_talk_plan": "scene_talk_plan",
        "_render_talk_line": "scene_talk_renderer",
        "_prepare_run_bases": "scene_run_base_renderer",
        "_build_scene_timing_plan": "scene_timing",
        "_render_scene_internal": "scene_standard_renderer",
    }

    for method_name, expected_module in method_modules.items():
        method = getattr(SceneRenderer, method_name)
        assert method.__module__.endswith(expected_module)


def test_fast_path_overlay_expression_helper_remains_static() -> None:
    assert SceneRenderer._escape_overlay_expr("if(a,b,c)") == "if(a\\,b\\,c)"
