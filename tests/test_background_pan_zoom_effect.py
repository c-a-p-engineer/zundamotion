from zundamotion.components.video.clip.effects.resolve import resolve_background_effects


def test_background_pan_zoom_resolves_to_zoompan_filter():
    snippet = resolve_background_effects(
        effects=[
            {
                "type": "bg:pan_zoom",
                "zoom": {"from": 1.0, "to": 1.2},
                "pan": {
                    "from": {"x": 0.2, "y": 0.5},
                    "to": {"x": 0.8, "y": 0.5},
                },
                "fps": 30,
            }
        ],
        input_label="[bg]",
        duration=4.0,
        width=1280,
        height=720,
    )

    assert snippet is not None
    assert snippet.output_label == "[bg_pan_zoom_1]"
    assert len(snippet.filter_chain) == 1
    assert "[bg]zoompan=" in snippet.filter_chain[0]
    assert "s=1280x720" in snippet.filter_chain[0]
    assert "fps=30.000[bg_pan_zoom_1]" in snippet.filter_chain[0]
