from zundamotion.components.pipeline_phases.video_phase.scene_renderer import (
    SceneRenderer,
)


def test_scene_renderer_public_facade_keeps_internal_responsibilities() -> None:
    method_modules = {
        "_resolve_background_layout": "scene_preparation",
        "_render_simple_scene_fast": "scene_fast_path",
        "_scene_base_cache_data": "scene_cache",
        "_render_scene_internal": "scene_standard_renderer",
    }

    for method_name, expected_module in method_modules.items():
        method = getattr(SceneRenderer, method_name)
        assert method.__module__.endswith(expected_module)


def test_fast_path_overlay_expression_helper_remains_static() -> None:
    assert SceneRenderer._escape_overlay_expr("if(a,b,c)") == "if(a\\,b\\,c)"
