from typing import Dict, List, Tuple

from zundamotion.components.voicevox_client import get_speakers_info


def generate_voice_report(
    used_voices: List[Tuple[int, str]],  # (speaker_id, text) のリスト
    output_filepath: str,
    voicevox_url: str = "http://127.0.0.1:50021",
):
    """
    Generates a Markdown report of used VOICEVOX information.

    Args:
        used_voices (List[Tuple[int, str]]): A list of tuples, where each tuple contains
                                             (speaker_id, text) for each generated voice.
        output_filepath (str): The path to save the voice report Markdown file.
        voicevox_url (str): The base URL of the VOICEVOX engine.
    """
    speaker_info = get_speakers_info(voicevox_url)

    report_lines = ["# 📋 VOICEVOX 使用情報レポート\n", "---\n"]

    # 使用されたVOICEVOX情報をユニークに収集
    # {speaker_id: (is_unknown, char_name, voice_name, original_speaker_id)}
    unique_voice_entries: Dict[int, Tuple[bool, str, str, int]] = {}
    for speaker_id, _ in used_voices:
        if speaker_id in speaker_info:
            speaker_data = speaker_info[speaker_id]
            char_name = speaker_data.get("speaker_name", "不明なキャラ")
            voice_name = speaker_data.get("name", "不明なボイス")
            unique_voice_entries[speaker_id] = (
                False,
                char_name,
                voice_name,
                speaker_id,
            )
        else:
            unique_voice_entries[speaker_id] = (
                True,
                "不明なキャラ",
                f"不明なボイス (ID: {speaker_id})",
                speaker_id,
            )

    # ソートキーの定義
    def sort_key(item):
        speaker_id, (is_unknown, char_name, voice_name, original_speaker_id) = item
        return (is_unknown, char_name, original_speaker_id)

    # ソートしてレポート行を生成
    for speaker_id, (is_unknown, char_name, voice_name, original_speaker_id) in sorted(
        unique_voice_entries.items(), key=sort_key
    ):
        if is_unknown:
            report_lines.append(f"* 不明なスピーカーID: {original_speaker_id}\n")
        else:
            report_lines.append(f"*VOICEVOX: {char_name} - {voice_name}\n")

    with open(output_filepath, "w", encoding="utf-8") as f:
        f.writelines(report_lines)

    print(f"VOICEVOX使用情報レポートを '{output_filepath}' に生成しました。")
