from zundamotion.components.pipeline_phases.video_phase.character_tracker import CharacterTracker


def _by_name(snapshot, name="copetan"):
    return next(item for item in snapshot if item["name"] == name)


def test_expression_changes_keep_scale_position_and_face_overlay_transform():
    tracker = CharacterTracker(1920, 1080)
    tracker.apply([{"name": "copetan", "scale": 0.7, "position": {"x": 10, "y": -20}}])
    tracker.snapshot()

    for expression in ("smile", "angry"):
        tracker.apply([{"name": "copetan", "expression": expression}])
        state = _by_name(tracker.snapshot())
        assert state["scale"] == 0.7
        assert state["position"] == {"x": 10, "y": -20}
        assert state["expression"] == expression


def test_explicit_scale_and_move_target_replace_previous_state_without_persisting_move():
    tracker = CharacterTracker(1920, 1080)
    tracker.apply([{"name": "copetan", "scale": 0.7, "position": {"x": 0, "y": 0}}])
    tracker.snapshot()
    tracker.apply(
        [{"name": "copetan", "scale": 0.9, "position": {"x": 100, "y": 5}, "move": {"duration": 0.2}}]
    )
    moved = _by_name(tracker.snapshot())
    assert moved["scale"] == 0.9
    assert moved["position"] == {"x": 100, "y": 5}
    assert moved["move"]["from"] == {"x": 0, "y": 0, "scale": 0.7}

    tracker.apply([{"name": "copetan", "expression": "smile"}])
    after = _by_name(tracker.snapshot())
    assert after["scale"] == 0.9
    assert after["position"] == {"x": 100, "y": 5}
    assert "move" not in after


def test_scene_defaults_priority_reset_and_new_scene_isolation():
    global_defaults = {"copetan": {"scale": 0.8, "position": {"x": -10, "y": 0}}}
    scene_defaults = {"copetan": {"scale": 1.2, "position": {"x": 0, "y": -20}}}
    tracker = CharacterTracker(1920, 1080, global_defaults, scene_defaults)
    tracker.apply([{"name": "copetan", "scale": 0.7}])
    assert _by_name(tracker.snapshot())["scale"] == 0.7

    tracker.reset()
    tracker.apply([{"name": "copetan", "expression": "serious"}])
    reset = _by_name(tracker.snapshot())
    assert reset["scale"] == 1.2
    assert reset["position"] == {"x": 0, "y": -20}

    next_scene = CharacterTracker(1920, 1080, global_defaults, {})
    next_scene.apply([{"name": "copetan", "expression": "default"}])
    assert _by_name(next_scene.snapshot())["scale"] == 0.8


def test_non_persistent_mode_remains_a_renderer_choice():
    tracker = CharacterTracker(1920, 1080)
    tracker.apply([{"name": "copetan", "scale": 0.7}])
    assert _by_name(tracker.snapshot())["scale"] == 0.7
    # SceneRenderer does not instantiate/apply this tracker when characters_persist is false.
