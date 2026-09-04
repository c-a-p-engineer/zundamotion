# レンダー後の Output QA

このガイドは、生成済み MP4 を **実測値で検査し、目視確認へ渡す** post-render QA 契約を扱います。
入力 provenance の Render Lock、レンダー前の `validate` / `compile`、出力再現性の framemd5 / audio PCM 検査とは責務を分けます。

## 目的

`zundamotion inspect` は次の2つを分離して扱います。

1. **Machine checks**: ffprobe で観測できる duration / stream / resolution / fps / audio parameter の検査
2. **Visual review**: FFmpeg で代表フレームを抽出した contact sheet を、人間または画像を見られる Agent が実際に確認する工程

`machine_valid: true` は visual review の成功を意味しません。contact sheet を生成しても `visual_review.status` は `pending_review` のままです。

## 基本コマンド

メディアとして読めるかだけを確認:

```bash
zundamotion inspect output/sample.mp4
zundamotion inspect output/sample.mp4 --json
```

元の台本から canonical output settings を再解決して照合:

```bash
zundamotion inspect output/sample.mp4 \
  --script scripts/sample.yaml \
  --json
```

export preset と照合:

```bash
zundamotion inspect output/shorts.mp4 \
  --preset shorts_1080x1920 \
  --json
```

代表フレームを1枚の PNG にまとめる:

```bash
zundamotion inspect output/sample.mp4 \
  --script scripts/sample.yaml \
  --contact-sheet \
  --samples 5 \
  --json
```

`--contact-sheet` にパスを省略すると `<video_stem>_contact_sheet.png` を動画の隣へ作成します。
明示パスも指定できます。

```bash
zundamotion inspect output/sample.mp4 \
  --contact-sheet build/qa/sample.png
```

## Machine checks

常に次を確認します。

- ファイルが存在し空でない
- video stream がある
- audio stream がある
- format duration が正の値

`--script` を指定した場合は、通常 render と同じ loader / resolver / defaults / export preset 適用後の canonical config から次を比較します。

- width
- height
- fps
- audio codec
- audio sample rate
- audio channels

`--preset` では既存 `EXPORT_PRESETS` が宣言する次を比較します。

- width
- height
- fps
- audio sample rate
- audio channels

`--script` と `--preset` は同時指定できません。台本側の明示 override を含めて検査したい場合は `--script` を使います。

## 終了コード

| code | 意味 |
| --- | --- |
| `0` | machine checks がすべて pass |
| `1` | machine checks に mismatch がある |
| `2` | 引数、入力、ffprobe / FFmpeg、contact sheet 生成等の実行エラー |

終了コード `0` は **映像表現の総合合格ではありません**。

## JSON contract v1

`--json` は `zundamotion.output-inspection` v1 を返します。

```json
{
  "format": "zundamotion.output-inspection",
  "format_version": 1,
  "zundamotion_version": "0.1.0",
  "path": "/work/output/sample.mp4",
  "size_bytes": 1234567,
  "media": {
    "duration": 12.34,
    "video": {
      "codec_name": "h264",
      "width": 1920,
      "height": 1080,
      "pix_fmt": "yuv420p",
      "r_frame_rate": "30/1",
      "fps": 30.0
    },
    "audio": {
      "codec_name": "aac",
      "sample_rate": 48000,
      "channels": 2,
      "channel_layout": "stereo"
    }
  },
  "expected": {
    "width": 1920,
    "height": 1080,
    "fps": 30,
    "audio_codec": "aac",
    "audio_sample_rate": 48000,
    "audio_channels": 2
  },
  "checks": [],
  "machine_valid": true,
  "visual_review": {
    "status": "pending_review",
    "contact_sheet": "/work/output/sample_contact_sheet.png",
    "timestamps": [0.62, 3.39, 6.17, 8.95, 11.72],
    "note": "Inspect the contact sheet for crop, subtitle, overlay, colour, and transition problems."
  }
}
```

`checks` の各項目は `id / status / actual` を持ち、期待値がある検査は `expected` も持ちます。
JSON key の意味を破壊的に変更する場合は `format_version` を上げます。

## Contact sheet の意味

既定では動画 duration の 5%〜95% の範囲から均等に代表点を選びます。exact start/end を避け、冒頭や終端だけの黒フレームに QA が偏ることを避けます。

これは **広域サンプリング** であり、scene 境界や transition の瞬間を自動で保証するものではありません。
transition、move、pan/zoom、J-cut/L-cut など特定時刻の挙動を検証するときは、[video_direction_and_qa.md](./video_direction_and_qa.md) の代表状態・境界前後確認を追加します。

contact sheet では最低限次を確認します。

- 字幕が画面外や人物の顔へ不自然に被っていない
- character / overlay / badge が意図した領域にいる
- crop / contain / cover が主要被写体を欠落させていない
- 色が白飛び、黒潰れ、意図しない色変換になっていない
- 代表点で背景、立ち絵、字幕の破綻がない

## AI / CI の推奨ループ

```text
capabilities --json
        ↓
validate --json
        ↓
compile
        ↓
lock / verify-lock（必要時）
        ↓
render
        ↓
inspect --script ... --contact-sheet --json
        ↓
machine_valid を確認
        ↓
contact sheet を実際に見る
        ↓
必要なら特定 scene / 境界を追加確認
```

Agent が画像を閲覧できない実行環境では contact sheet の生成までを自動化し、visual review は `pending_review` として引き継ぎます。

## 非目標

`inspect` は次を置き換えません。

- Render Lock による入力 provenance
- framemd5 / audio PCM による出力同等性
- transition 境界や scene 内 motion の時刻指定 E2E characterization
- 視聴者としての演出・テンポ・読みやすさの判断
- 音声内容そのものの聴感確認

probe の成功や contact sheet の生成だけを「動画が正しい」の証拠にしません。
