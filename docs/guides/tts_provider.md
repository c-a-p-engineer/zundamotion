# TTS Provider contract

Zundamotion の音声合成 backend を、timeline / cache / mix の責務から分離するための境界です。
現在の provider は `voicevox` と `chatterbox` です。既定値は後方互換のため `voicevox` のままです。

## 責務境界

`TTSProvider` が担当するもの:

- provider ID / capability
- 対応言語
- engine version
- speech synthesis
- provider 固有の voice cloning / expression option

`TTSProvider` が担当しないもの:

- scene / line timeline
- BGM / SE mix
- lip-sync layer metadata
- silent fallback
- 最終 FFmpeg audio normalization

speech cache は provider ID、model/version、言語、参照音声 hash、provider option を含めて AudioGenerator 側で管理します。

## provider 一覧

### `voicevox`

既存の日本語デフォルトです。`speaker_id`、`speed`、`pitch` を利用します。
従来の `get_speakers_info()` / `get_engine_version()` / `generate_voice()` は compatibility wrapper として維持します。

### `chatterbox`

Resemble AI Chatterbox Multilingual V3 を optional runtime として利用します。
通常の Zundamotion / VOICEVOX install へ PyTorch を必須依存させず、Chatterbox を実際に合成するときだけ runtime を import します。

対応言語は 23 言語です。

`ar`, `da`, `de`, `el`, `en`, `es`, `fi`, `fr`, `he`, `hi`, `it`, `ja`, `ko`, `ms`, `nl`, `no`, `pl`, `pt`, `ru`, `sv`, `sw`, `tr`, `zh`

主な capability:

```json
{
  "provider_id": "chatterbox",
  "languages": ["ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi", "it", "ja", "ko", "ms", "nl", "no", "pl", "pt", "ru", "sv", "sw", "tr", "zh"],
  "supports_speed": false,
  "supports_pitch": false,
  "supports_voice_cloning": true,
  "supports_exaggeration": true,
  "supports_cfg_weight": true,
  "output_watermarked": true,
  "optional_runtime": true
}
```

Chatterbox の生成音声には upstream の Perth watermark が入ります。

## Chatterbox runtime

2026-08-29 時点の検証対象 package は `chatterbox-tts==0.1.7` です。Zundamotion では optional extra として固定します。

Repository checkout:

```bash
python -m pip install -e ".[chatterbox]"
```

配布 package:

```bash
python -m pip install "zundamotion[chatterbox]"
```

`chatterbox` extra は **通常依存には含めません**。Chatterbox は PyTorch / model download を伴うため、既定のVOICEVOX runtimeから分離します。

Dev Containerでは、必要なときだけChatterbox overrideを追加します。通常のComposeへこのoverrideを重ねると、標準Dockerfileとは別の`.devcontainer/Dockerfile.chatterbox`を使い、packageを専用imageへ導入し、初回取得したモデルを名前付きvolumeへ保持します。Python 3.14でPyPIのCUDA依存を誤って取り込まないよう、CPU版`torch==2.11.0+cpu`と`torchaudio==2.11.0+cpu`をPyTorch公式CPU indexから先に導入します。モデル取得は長時間のXet/CAS転送失敗を避けるため、専用override内で`HF_HUB_DISABLE_XET=1`を設定して通常HTTP経路を使います。

生成波形のWAV保存には`SoundFile`を使います。Torchaudio 2.11の保存APIが別途要求する`torchcodec`は、Chatterbox専用imageへ追加しません。

```bash
docker compose -f .devcontainer/docker-compose.yml \
  -f .devcontainer/docker-compose.chatterbox.yml \
  up -d --build app
```
最初の `from_pretrained()` では upstream model cache が必要になる場合があります。Render Lock v1 はこの remote model 内容を固定しないため、現段階では Chatterbox runtime を optional / experimental と扱います。
このoverrideは`voice.device: cpu`専用です。CUDA経路はwheel/runtime/実機smokeを固定するまで正式サポートしません。

## YAML

最小例:

```yaml
voice:
  provider: chatterbox
  language: en
  model: v3
  device: cpu
  exaggeration: 0.5
  cfg_weight: 0.5

scenes:
  - id: intro
    lines:
      - text: Hello from Zundamotion.
```

`language` は行単位でも上書きできます。

```yaml
lines:
  - text: Hello from Zundamotion.
    language: en
  - text: Hola desde Zundamotion.
    language: es
  - text: Bonjour depuis Zundamotion.
    language: fr
  - text: こんにちは。ずんだもーしょんです。
    language: ja
```

zero-shot voice cloning:

```yaml
voice:
  provider: chatterbox
  language: en
  model: v3
  device: cuda
  reference_audio: assets/voice/reference.wav
```

`reference_audio`、`language`、`exaggeration`、`cfg_weight` は行 / voice layer でも上書きできます。参照音声は cache identity に SHA-256 で含めます。

### 設定値

| 項目 | 値 | 既定 | 説明 |
| --- | --- | --- | --- |
| `voice.provider` | `voicevox` / `chatterbox` | `voicevox` | TTS backend |
| `voice.language` | 上記23 code | `en` (Chatterbox) | 発話言語。行単位上書き可 |
| `voice.model` | `v3` | `v3` | `chatterbox-tts==0.1.7` の固定 Multilingual runtime を表す Zundamotion 側の別名 |
| `voice.device` | `cpu` / `cuda` / `mps` | `cpu` | 明示 runtime device。再現性のため `auto` は使わない |
| `voice.reference_audio` | file path | なし | zero-shot voice cloning |
| `voice.exaggeration` | 0以上の数値 | `0.5` | 表現強度 |
| `voice.cfg_weight` | 0〜1 | `0.5` | reference / generation guidance |

Chatterbox は現在 `speed` / `pitch` capability を公開しません。既存の VOICEVOX 用 `speed` / `pitch` を Chatterbox の調整値として解釈しません。

## サンプル

Repository sample:

- `scripts/sample_chatterbox_multilingual.yaml`: English / Spanish / French / German / Japanese を1本で切り替える例

upstream の音声を先に確認したい場合:

- Chatterbox examples: https://resemble-ai.github.io/chatterbox_demopage/
- Chatterbox repository: https://github.com/resemble-ai/chatterbox

## AI / CI

runtime をインストールしなくても次は利用できます。

```bash
zundamotion capabilities --json
zundamotion validate scripts/sample_chatterbox_multilingual.yaml --json
zundamotion compile scripts/sample_chatterbox_multilingual.yaml --pretty
```

`capabilities` は Chatterbox package / model を import・downloadしません。

## 今後の固定事項

- Chatterbox model artifact / transitive dependency の runtime lock
- Arabic / Hindi 等を含む font fallback
- provider-neutral voice usage report
- real model を使った CPU/GPU benchmark と音声 characterization
- optional runtime の Docker sidecar 化を採用するかの比較

Provider を追加するときは provider 固有 ID / URL / model option を timeline model へ漏らさず、unsupported capability は `false` として機械可読にします。
