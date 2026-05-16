# 2026-05-16 PNG 字幕高速化ログ

このファイルは `performance_regression_ledger.md` から分離した詳細ログ。ledger 側には最新判断と主要数値だけを残す。

## P0 診断ログ追加

対象:
- PNG 字幕のリッチ表現を維持する前提で、ASS/libass、subtitle-only transparent video、transparent video chunk、talk_fast、GPU overlay / CUDA overlay、scene-unit 巨大 filter graph、static slide fast path は採用しない。
- 長時間レンダリングに張り付かず、既存の長尺ログを baseline として記録し、次回同一台本で比較できる診断ログを追加した。

baseline:
- total: `2995.87s`
- output duration: `975.77s`
- realtime ratio: 約 `3.07x`
- `AudioPhase`: `192.77s`
- `VideoPhase`: `2526.82s`
- `FinalizePhase`: `259.13s`
- subtitle PNG unique: `149`
- face overlay PNG unique: `6`
- `subtitle_render_mode_png`
- `CPU path: RGBA overlays detected`

追加した診断ログ:
- `[SubtitlePNG]`: `text_hash`, PNG size, alpha bbox, transparent margin L/T/R/B, full canvas 判定, render_ms, cache hit/miss
- `[SubtitleChunk]`: subtitle count, chunk_size, chunk_count, density, total gap, longest continuous zone, chunk duration, subtitles per chunk, gap_copy_before, ffmpeg_ms
- `[SubtitleGap]`: gap start/end/duration, copy/reencode 集計, copy 失敗理由
- `[SubtitleInput]`: unique subtitle PNG, FFmpeg input count, duplicated input count, duplicate reason
- `[FaceOverlay]`: unique face assets, FFmpeg input count, overlay filter count, duplicated input count
- `[SceneCache]`: base/sub hit/miss に短縮 cache key と miss reason を追加
- `[FilterGraph]`: target, input count, overlay count, filter_complex length, enable expression count, FFmpeg time

検証:
- Host: `python3 -m py_compile zundamotion/components/subtitles/png.py zundamotion/components/video/overlays.py zundamotion/components/video/clip/face.py zundamotion/components/pipeline_phases/video_phase/scene_renderer.py`
- Docker app container:
  - `python -m py_compile zundamotion/components/subtitles/png.py zundamotion/components/video/overlays.py zundamotion/components/video/clip/face.py zundamotion/components/pipeline_phases/video_phase/scene_renderer.py`
  - `python -m pytest -q tests/test_overlay_alpha_preservation.py tests/test_scene_renderer_subtitle_flow.py tests/test_face_overlay_fallback.py`: `11 passed in 1.84s`

## P1 bounded 実装

対象:
- P1-1 `subtitle.png_chunk_size=auto` を字幕密度、gap duration、longest continuous subtitle zone も見る方式へ拡張した。
- P1-7 PNG 保存設定に `subtitle.png_compress_level` / `subtitle.png_optimize` を追加し、既定を `png_compress_level=1`, `png_optimize=false` にした。

bounded 実測:

```text
CHUNK baseline_90_534 count=90 duration=534.25 chunk_size=15 expected_chunks=6
CHUNK dense_149_975 count=149 duration=975.77 chunk_size=22 expected_chunks=7
CHUNK sparse_gap_90_534 count=90 duration=534.25 chunk_size=18 expected_chunks=5

PNG cl1_opt0 avg_ms=23.23 p95_ms=27.80 avg_size=40805
PNG cl3_opt0 avg_ms=27.56 p95_ms=40.11 avg_size=39074
PNG cl6_opt0 avg_ms=39.67 p95_ms=54.66 avg_size=41112
PNG cl6_opt1 avg_ms=102.52 p95_ms=113.81 avg_size=40533
```

検証:
- Docker app container:
  - `python -m pytest -q tests/test_overlay_alpha_preservation.py tests/test_subtitle_png.py tests/test_scene_renderer_subtitle_flow.py tests/test_face_overlay_fallback.py`: `19 passed in 2.00s`

## `000_intro_channel-intro` P1 判定

対象ログ:
- `/workspace/logs/20260516_174940_014.log`
- 既存 `001_intro_channel-intro` との比較用に、出力名は意図的に `000_intro_channel-intro` とした。

実測:
- `Total execution time`: `578.96s`
- output duration: `193.41s`
- realtime ratio: 約 `2.99x`
- `AudioPhase`: `44.31s`
- `VideoPhase`: `475.94s`
- `FinalizePhase`: `50.46s`
- `subtitle_render_mode`: `png`
- subtitles: `60`
- base duration: `182.57s`
- `png_chunk_size`: `10`
- chunk count: `6`
- subtitle density: `0.329/s`
- total subtitle gap: `0.000s`
- longest continuous subtitle zone: `182.570s`
- subtitle chunk FFmpeg 合計: `95081.7ms`
- slowest subtitle chunk: `21150.1ms`
- filter graph length: `1114` から `1249`
- per chunk inputs: `11`
- per chunk overlays: `10`
- subtitle input duplicate total: `0`
- face overlay duplicate total: `0`
- subtitle PNG logs: `120` (`miss=60`, `hit=60`)
- subtitle PNG full alpha bbox: `120/120`

chunk 明細:

| chunk | subtitles | duration | ffmpeg_ms |
|---:|---:|---:|---:|
| 1 | 10 | 28.150s | 15211.4 |
| 2 | 10 | 33.330s | 17350.9 |
| 3 | 10 | 23.530s | 12977.7 |
| 4 | 10 | 28.880s | 15993.2 |
| 5 | 10 | 43.320s | 21150.1 |
| 6 | 10 | 25.360s | 12398.4 |

判定:

| タスク | 判定 | 実測 | 理由 |
|---|---|---:|---|
| P1-1 subtitle chunk auto 密度ベース調整 | 採用維持 | `60 subtitles`, `chunk_size=10`, `6 chunks` | 密な連続字幕を 10 overlay/chunk に抑え、filter graph length も `1249` 以下。巨大 graph 化は起きていない |
| P1-2 gap copy 最大化 | 却下 | `SubtitleGap count=0`, `total=0.000s` | この台本は字幕なし gap がなく、copy 最大化で削れる区間がない |
| P1-3 subtitle PNG tight bbox 化 | 却下 | `full alpha bbox=120/120`, PNG size は最大でも `1068x200` 程度 | PNG は動画フルキャンバスではなく字幕ボックス相当のサイズ。背景ボックスのため crop リスクが高い |
| P1-4 subtitle scale 事前固定 | 却下 | filter graph length `1114-1249`, scale 削減候補なし | 支配要因は scale ではなく overlay 再エンコード時間 |
| P1-5 subtitle PNG input 共有 | 却下 | `duplicated_total=0` | input count は減らない |
| P1-6 face overlay input 共有 | 却下 | `duplicated_total=0` | input count は減らない |
| P1-7 PNG compress_level 比較 | 採用維持 | bounded bench `cl1_opt0 avg_ms=23.23`, `cl6_opt0 avg_ms=39.67` | `optimize=true` を採用する理由はない |
| P1-8 CPU worker/thread 再調整 | 保留 | `clip_workers=2`, `scene_workers=2`, subtitle burn `filter_threads=4`, `filter_complex_threads=4` | 比較条件がない |

次の改善候補:
- この台本では subtitle chunk burn 合計が約 `95s`、VideoPhase が `475.94s` のため、残りの主因は字幕 input 重複ではなく line clip の CPU overlay と再エンコード時間。
- face/subtitle input 共有ではなく、CPU overlay 経路の worker/thread 比較、または clip 生成の再利用/cache hit 率改善を次に見る。
