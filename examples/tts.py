# PYTHONPATH=. python ./examples/tts.py
from zundamotion.tts_client import generate_voice

generate_voice(
    text="これはテスト音声です。",
    speaker=1,
    out_path="voices/test.wav",
    speed=1.0,
    pitch=0.0,
)
