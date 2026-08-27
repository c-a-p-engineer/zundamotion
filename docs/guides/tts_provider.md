# TTS Provider contract

Zundamotion の音声合成 backend を、timeline / cache / mix の責務から分離するための境界です。
現時点で実装済み provider は `voicevox` だけです。多言語 provider を追加したことを意味しません。

## 責務境界

`TTSProvider` が担当するもの:

- provider ID
- provider capability の宣言
- speaker 一覧取得
- engine version 取得
- speech synthesis

`TTSProvider` が担当しないもの:

- scene / line timeline
- speech cache policy
- BGM / SE mix
- lip-sync 用 layer metadata
- silent fallback
- FFmpeg audio format normalization

これらは既存 `AudioGenerator` / AudioPhase / FFmpeg utility の責務を維持します。

## 現在の provider

### `voicevox`

`VoicevoxTTSProvider` は既存の VOICEVOX HTTP client を provider contract に適合させます。
従来の `get_speakers_info()` / `get_engine_version()` / `generate_voice()` は compatibility wrapper として残り、既存 `AudioGenerator` の呼び出し契約を変更しません。

公開 capability:

```json
{
  "provider_id": "voicevox",
  "languages": ["ja"],
  "supports_speed": true,
  "supports_pitch": true,
  "supports_speaker_listing": true,
  "supports_engine_version": true,
  "supports_word_alignment": false
}
```

`zundamotion capabilities --json` では `tts.provider_capabilities.voicevox` から同じ情報を取得できます。

## 将来 provider を追加するとき

新しい provider は `TTSProvider` の通信境界へ実装し、VOICEVOX 固有の speaker ID、URL、retry 設定を共通 timeline model へ漏らさないようにします。
provider が対応しない機能は capability で `false` とし、未対応値を暗黙に無視しません。

多言語対応では別途、次を確定する必要があります。

- YAML の provider / voice / language 選択契約
- font fallback
- reading text と display text の関係
- provider ごとの cache identity
- alignment を持たない provider の lip-sync 契約

この文書は provider 境界の正本であり、多言語仕様そのものの完成を宣言するものではありません。
