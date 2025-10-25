from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zundamotion.components.script.loader import load_script_and_config


def test_voice_layers_inherit_character_defaults(tmp_path):
    default_config_path = tmp_path / "default.yaml"
    default_config_path.write_text(
        yaml.safe_dump(
            {
                "script": {"scenes": []},
                "defaults": {},
            }
        ),
        encoding="utf-8",
    )

    script_path = tmp_path / "script.yaml"
    script_path.write_text(
        yaml.safe_dump(
            {
                "meta": {"title": "test", "version": 3},
                "defaults": {
                    "characters": {
                        "alice": {"speaker_id": 1, "speed": 1.2},
                        "bob": {"speaker_id": 2},
                    }
                },
                "scenes": [
                    {
                        "id": "scene",
                        "bg": str((Path.cwd() / "assets/bg/room.png").resolve()),
                        "lines": [
                            {
                                "text": "合わせて挨拶",
                                "voice_layers": [
                                    {"speaker_name": "alice"},
                                    {"speaker_name": "bob", "speed": 0.9},
                                ],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    config = load_script_and_config(str(script_path), str(default_config_path))
    line = config["script"]["scenes"][0]["lines"][0]

    assert "voice_layers" in line
    voice_layers = line["voice_layers"]
    assert voice_layers[0]["speaker_id"] == 1
    assert voice_layers[0]["speed"] == 1.2
    assert voice_layers[1]["speaker_id"] == 2
    # Explicit overrides on the layer should be preserved
    assert voice_layers[1]["speed"] == 0.9
