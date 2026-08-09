# プロジェクト構造

このガイドは、現在の Zundamotion の主要コンポーネントと責務境界をまとめます。
現在の完了状況や次タスクは [`project_status.md`](./project_status.md) を参照してください。

## 技術スタック

- 言語: CPython 3.14 系
- 主要ライブラリ: PyYAML / requests / httpx / tenacity / pysubs2 / Pillow
- 外部ツール: FFmpeg / ffprobe / VOICEVOX Engine

## リポジトリ全体

```text
.
├── assets/                 # 背景、立ち絵、BGM、SE
├── docs/                   # 利用ガイド、設計、判断・性能履歴
├── output/                 # 生成物
├── scripts/                # サンプル台本、YAMLチートシート
├── site/                   # GitHub Pages機能デモ
├── tests/                  # unit / integration / characterization
├── tools/                  # benchmark、検証、補助CLI
└── zundamotion/            # 本体
```

## `zundamotion/` の主要責務

```text
zundamotion/
├── main.py                 # CLI entry
├── pipeline.py             # GenerationPipeline facade / orchestration
├── pipeline_entry.py       # 高レベル実行入口
├── pipeline_reporting.py   # pipeline report / summary
├── cache.py                # CacheManager public compatibility facade
├── cache_runtime.py        # generic cache runtime
├── cache_media.py          # media probe cache
├── cache_lifecycle.py      # TTL / eviction / cleanup
├── cache_observability.py  # cache diagnostics
├── components/
│   ├── audio/              # VOICEVOX、音声生成・mix
│   ├── config/             # YAML設定とvalidation
│   ├── markdown/           # Markdown input pipeline
│   ├── pipeline_phases/    # Audio / Video / Finalize / BGM
│   ├── script/             # include / vars / script resolution
│   ├── subtitles/          # PNG / ASS subtitle generation
│   └── video/              # clip renderer、overlay、effect
├── plugins/                # built-in / drop-in plugin registry
├── reporting/              # reporting helpers
├── templates/              # package default config
└── utils/                  # FFmpeg、probe、runtime、logging
```

## Pipeline

`GenerationPipeline` はフェーズ順序制御を担当し、詳細処理を抱え込みません。

```text
AudioPhase
  ↓
VideoPhase
  ↓
FinalizePhase
  ↓
BGMPhase
  ↓
final output / sidecars
```

設定解決、reporting、cache、各フェーズ内部の処理は専用モジュールへ分離されています。

## Audio

主な責務:

- `components/audio/`: VOICEVOX client、speech生成、cache、複数音声mix
- `pipeline_phases/audio_phase*.py`: line entry、speech、face animation、control、ordered execution
- `utils/ffmpeg_audio.py`: FFmpeg audio primitive

現在は VOICEVOX が音声合成実装の中心です。将来の TTS Provider 抽象化は `project_status.md` の後続タスクとして扱います。

## VideoPhase / SceneRenderer

公開入口は `components/pipeline_phases/video_phase/scene_renderer.py` の `SceneRenderer` です。
外部コードは隣接する mixin を直接利用せず、この facade 経由で扱います。

| 責務 | 主なモジュール |
| --- | --- |
| scene facade / persistent state | `scene_renderer.py` |
| standard orchestration | `scene_standard_renderer.py` |
| context / timing | `scene_standard_context.py`, `scene_timing.py` |
| precache / preparation | `scene_precache.py`, `scene_preparation.py`, `scene_*_preparation.py` |
| scene base / run base | `scene_base_*.py`, `scene_run_base_*.py` |
| line plan / wait / talk / executor | `scene_line_*.py`, `scene_wait_renderer.py`, `scene_talk_*.py` |
| assembly / result cache | `scene_assembly.py`, `scene_result_cache.py` |
| fast path | `scene_fast_path*.py` |

大規模な standard renderer 分割は完了済みです。`scene_standard_renderer.py` は名前付きstageの呼出を中心とする orchestration です。

## ClipRenderer

公開入口は `components/video/clip_renderer.py::render_clip` です。
内部は次へ分離されています。

- input collection
- background / overlay / subtitle / video / audio graph
- backend policy
- FFmpeg command generation
- process execution / fallback
- pipeline orchestration

`clip_renderer.py` 自体は public compatibility wrapper として扱います。

## Subtitle

字幕は PNG / ASS / auto を扱います。

- `components/subtitles/png_*.py`: style、metadata、text、draw、executor、renderer
- `components/video/subtitle_segment_*.py`: segment planning / execution / video-only processing
- `components/video/subtitle_overlay_*.py`: overlay runtime / graph / FFmpeg execution

字幕segment性能変更では `performance_regression_ledger.md` と専用benchmarkを先に確認します。

## FFmpeg utility

共有FFmpeg責務は用途別に分離されています。

- `ffmpeg_background.py`
- `ffmpeg_concat.py`
- `ffmpeg_transition.py`
- `ffmpeg_normalize.py`
- `ffmpeg_capability_listing.py`
- `ffmpeg_encoder_capabilities.py`
- `ffmpeg_filter_smoke.py`
- `ffmpeg_threading.py`
- `ffmpeg_progress.py`
- `ffmpeg_diagnostics.py`
- `ffmpeg_process.py`
- `ffmpeg_runner.py`

`ffmpeg_ops.py`、`ffmpeg_capabilities.py`、`ffmpeg_runner.py` には compatibility facade として残る責務があります。行数だけを理由に再分割しません。

## Cache

public API は `zundamotion.cache.CacheManager` を維持します。
内部では generic runtime、media probe、lifecycle、observability、signature memo を分離しています。
historical compatibility base が残っていても、active public dispatch を基準に判断します。

## Markdown / Plugin

- `components/markdown/`: frontmatter parse、line model、render config resolution
- `plugins/`: built-in registry と drop-in plugin discovery、allow/deny policy

## 関連資料

- 現在状態: [`project_status.md`](./project_status.md)
- YAML: [`../../scripts/script_cheatsheet.md`](../../scripts/script_cheatsheet.md)
- 機能一覧: [`../features.md`](../features.md)
- Python規約: [`python_coding_rules.md`](./python_coding_rules.md)
- 性能判断: [`performance_regression_ledger.md`](./performance_regression_ledger.md)
- 大規模分割の履歴: [`source_refactoring_plan.md`](./source_refactoring_plan.md)
