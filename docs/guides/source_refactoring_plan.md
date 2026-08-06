# ソースリファクタリング計画

Zundamotion の既存 Python コードを `python_coding_rules.md` に沿って段階的に分割する計画。
挙動、YAML、CLI、FFmpeg 出力、cache key を変えず、AI / Codex が変更時に読む範囲を小さくすることを目的とする。

## 0. 現在の結論（2026-08-06）

- 基準: `master` `d56a83a0b52dadc8907c256123346f238a885ef3`
- Phase 0 の自動計測、Phase 1 の設定 validation、Phase 2 の Pipeline / AudioPhase 第一バッチは完了
- `audio_phase_run.py` は 500 行超・80 行超関数の一覧から外れた
- 次に実施する領域は **Phase 6A: `scene_standard_renderer.py` の段階分割**
- 最初の PR は FFmpeg 処理方式を変えず、タイミング計画と保護テストだけを分離する
- Phase 番号は領域識別子として維持し、実際の実施順は本書の「優先順位」に従う

## 1. 現行コードの計測結果

PR #18 の CI で `scripts/report_source_metrics.py` を実行した結果:

- Python ファイル: 177
- 500 行超: 19 ファイル
  - 本体 `zundamotion/`: 17 ファイル
  - tests: 2 ファイル
- 80 行超関数: 73 件
  - 本体 `zundamotion/`: 59 件

テストファイルの行数超過は本体の責務分割と分けて扱う。
本体の 500 行超ファイルは次のとおり。

| 優先 | 対象 | 行数 | 最長関数 | 関数行数 | 判断 |
| ---: | --- | ---: | --- | ---: | --- |
| 1 | `utils/ffmpeg_ops.py` | 1539 | `normalize_media` | 359 | 低レベル共通処理。影響範囲が広いため先に呼び出し側を整理する |
| 1 | `video_phase/scene_standard_renderer.py` | 1264 | `_render_scene_internal` | 1240 | 単一関数へ標準 scene 描画が集中。次フェーズ |
| 2 | `components/video/overlays.py` | 1212 | `apply_subtitle_overlays` | 293 | 字幕計画・filter・実行が混在 |
| 2 | `cache.py` | 1005 | `get_or_create_normalized_video` | 128 | probe・metadata・生成 cache が混在 |
| 2 | `components/video/clip_renderer.py` | 979 | `render_clip` | 915 | clip 入力・graph・実行が単一関数に集中 |
| 2 | `components/subtitles/png.py` | 968 | `_render_subtitle_png` | 171 | style・描画・metadata・worker が混在 |
| 3 | `utils/ffmpeg_capabilities.py` | 939 | `smoke_test_cuda_filters` | 94 | capability probe と smoke が混在 |
| 2 | `components/video/scene_renderer.py` | 793 | `render_wait_clip` | 414 | wait/background/base 描画が集中 |
| 2 | `video_phase/scene_fast_path.py` | 724 | `_render_simple_scene_fast` | 428 | 適用判定・graph 構築・実行が混在 |
| 4 | `components/video/clip/effects/resolve.py` | 695 | `_resolve_screen_shake` | 84 | ファイルは大きいが関数超過は小さい |
| 4 | `components/markdown/pipeline.py` | 654 | `_markdown_render_config` | 110 | Markdown 解決と描画設定が混在 |
| 3 | `pipeline_phases/finalize_phase.py` | 604 | `FinalizePhase.run` | 228 | transition・timeline shift・concat・cache が混在 |
| 3 | `utils/ffmpeg_runner.py` | 592 | `run_ffmpeg_async` | 270 | subprocess・監視・ログ・診断が集中 |
| 2 | `components/video/clip/characters.py` | 582 | `build_character_overlays` | 255 | character 状態と filter graph が集中 |
| 2 | `components/subtitles/generator.py` | 556 | `build_subtitle_overlay` | 139 | style 解決と overlay 構築が混在 |
| 2 | `video_phase/scene_preparation.py` | 537 | `_precache_face_overlays` | 137 | 背景・badge・顔・画像 layer 準備が混在 |
| 3 | `video_phase/main.py` | 527 | `VideoPhase.run` | 146 | phase 構築・scene 並列制御・結果集約が混在 |

優先欄は「直ちに着手する順番」ではなく、分割効果と依存関係を合わせた分類。
`ffmpeg_ops.py` は最大ファイルだが、多数の描画経路から利用されるため最初には触らない。

## 2. 完了済み

### Phase 0: ベースラインと保護

- `scripts/report_source_metrics.py` を追加
- AST で 500 行超ファイルと 80 行超関数を JSON / Markdown 出力
- CI 成果物として計測結果を保存
- 単体、FFmpeg 統合、CPU smoke、no-voice 再現性を比較可能にした
- 完了 PR: #14

### Phase 1: 設定 validation

- `validate.py` を入口へ縮小
- background、overlay、badge、image layer、script traversal を分離
- validation 配下は 500 行以下・80 行以下を達成
- 完了日: 2026-06-07

### Phase 2: Pipeline / AudioPhase 第一バッチ

Pipeline:

- reporting を `pipeline_reporting.py` へ分離
- 高レベル entry を `pipeline_entry.py` へ分離
- public import を維持

AudioPhase:

- `audio_phase_entries.py`: scene / item 正規化、読み・表示・TTS 文字列、task 準備
- `audio_phase_face_anim.py`: 口パク、まばたき、voice layer 別 face animation
- `audio_phase_speech.py`: 音声 cache、filter、duration、L カット、timeline 登録
- `audio_phase_control.py`: BGM、topic、wait、image layer
- `audio_phase_run.py`: ordered entry の順序制御
- `audio_phase.py`: 公開互換層

完了 PR:

- #15 入力計画
- #16 顔 animation 計画
- #17 発話処理
- #18 非発話制御と orchestration 縮小

維持した契約:

- public import
- YAML / CLI
- timeline 順序
- line data 形式
- VOICEVOX 呼び出し単位
- cache key
- mouth timeline monkeypatch seam
- CPU smoke / no-voice 再現性

## 3. 実施優先順位

| 実施順 | 領域 | 理由 |
| ---: | --- | --- |
| 1 | Phase 6A: scene standard renderer | 1240 行の単一関数と 416 行の nested line renderer が最大の変更集中点 |
| 2 | Phase 6B: scene fast path / preparation | standard path の境界確定後なら責務を安全に分けやすい |
| 3 | Phase 5: clip renderer / character / face | scene 側の入力契約を固定してから clip 内部を分割する |
| 4 | Phase 3: subtitle PNG / overlays | scene assembly と clip contract 固定後に字幕経路を分割する |
| 5 | Phase 4: FFmpeg utility / cache | 最も共有範囲が広く、上位呼び出し側の整理後に着手する |
| 6 | Phase 7: Finalize / runner / Markdown / 残存超過 | 独立度と回帰リスクを見て小 PR で処理する |

## 4. 次フェーズ: Phase 6A scene standard renderer

### 4.1 現在集中している責務

`SceneStandardRendererMixin._render_scene_internal` には次が混在している。

- enter / leave / J カットによる line duration 補正
- scene duration、line 開始時刻、badge marker、subtitle entry の計算
- scene base / subtitle cache lookup
- subtitle / face overlay precache
- 静的 character・insert の共通部分検出
- scene base、run base、background normalize の選択と生成
- wait / talk / image layer の行別描画
- line clip cache payload 構築
- clip worker semaphore と順序維持
- performance sampling と auto tune
- scene concat、foreground overlay、subtitle burn
- base / subtitle / no-sub cache 保存
- 一時 base の cleanup

nested `process_one` だけで 416 行あり、wait と talk の cache / 描画 / 計測が同じ関数に入っている。

### 4.2 完了条件

Phase 6A 全体の完了条件:

- `scene_standard_renderer.py` を 500 行以下にする
- `_render_scene_internal` を 80 行以下の順序制御へ縮小する
- 新規ファイルは原則 200〜400 行、各関数 80 行以下
- `SceneRenderer` の public import、constructor、呼び出し方を維持する
- line data、scene cache payload、subtitle timing、FFmpeg 呼び出し順を変えない
- wait / talk / image layer の出力順を変えない
- line clip 並列度、結果順序、PerfSummary、auto tune の意味を変えない
- CPU smoke と no-voice 再現性を通す
- 性能比較で有意な悪化がない

### 4.3 タスク一覧

#### 6A-0: 保護テスト追加

- [ ] enter / leave / J カット後の duration と start time を固定する
- [ ] `wait` / `talk` / `image_layer` の結果順を固定する
- [ ] base cache hit 時に line clip を生成せず subtitle burn だけ行う経路を固定する
- [ ] static character / common insert による base 選択条件を固定する
- [ ] line background override 時に scene base を使わない条件を固定する
- [ ] scene concat → foreground overlay → subtitle burn → cache 保存の順序を固定する
- [ ] `generate_no_sub_video` の保存先と source path を固定する
- [ ] line clip cache payload の主要キーを snapshot する
- [ ] auto tune の sample 収集と retune 条件を単体テスト可能な形で固定する

#### 6A-1: タイミングと scene context の分離

候補:

- `scene_timing.py`
- `SceneTimingPlan` / `SceneRenderContext` dataclass

分離する処理:

- line duration padding
- scene duration
- `start_time_by_idx`
- badge line markers
- subtitle entries
- subtitle timing key
- base / subtitle cache component keys

制約:

- この PR では FFmpeg を呼ぶコードを移動しない
- line data の mutation 順序を維持する
- cache key の JSON 内容を変更しない

#### 6A-2: scene base 計画と生成の分離

候補:

- `scene_base_plan.py`: 純粋な判定と入力データ
- `scene_base_renderer.py`: normalize / render の I/O

分離する処理:

- static character の共通部分
- common insert image / video
- `should_generate_base`
- normalized background
- run base の区間計画
- run 内 offset

制約:

- scene base の採用条件を変更しない
- 新しい高速化を同時に導入しない
- normalize / render の失敗時 fallback を維持する

#### 6A-3: line clip 描画の分離

候補:

- `scene_line_renderer.py`
- `SceneLineRenderRequest`
- `SceneLineRenderResult`

分離する処理:

- background config 選択
- wait clip cache / render
- talk clip cache payload
- effective character / insert 解決
- clip render
- foreground overlay
- performance sample
- semaphore と結果順序

内部ではさらに次へ分ける。

- `render_wait_line`
- `render_talk_line`
- `build_line_background_config`
- `build_talk_clip_cache_data`
- `record_line_clip_metrics`

制約:

- `process_one` をそのまま別ファイルへ移すだけで完了扱いにしない
- cache hit / miss の計測定義を変えない
- image layer は clip を生成しない

#### 6A-4: scene assembly と cache 保存の分離

候補:

- `scene_assembly.py`

分離する処理:

- line clip concat
- scene foreground overlay
- base cache store
- subtitle burn
- subtitle cache store
- no-sub cache store
- temporary scene base cleanup

制約:

- concat、foreground、subtitle の順序を維持する
- base cache と subtitle cache の source path を取り違えない
- cache store は生成成功後だけ行う

#### 6A-5: orchestration 縮小

- [ ] `_render_scene_internal` を context 作成、cache short-circuit、fast path、base 準備、line 描画、assembly の呼び出しだけにする
- [ ] `scene_standard_renderer.py` を 500 行以下にする
- [ ] `tests/test_scene_renderer_module_split.py` の責務マッピングを更新する
- [ ] `project_structure.md` と `refactoring_check.md` の導線を更新する
- [ ] source metrics の前後値を PR に記録する

### 4.4 最初に行う PR

最初の実装 PR は **6A-0 と 6A-1 のみ**とする。

変更対象の目安:

- `scene_standard_renderer.py`
- 新規 `scene_timing.py`
- `tests/test_scene_renderer_timing.py`
- 必要最小限の module split test
- `source_refactoring_plan.md` の進捗

この PR では次を行わない。

- scene base 判定変更
- line clip 描画移動
- FFmpeg command 変更
- cache key version 更新
- performance tuning
- fast path 変更

## 5. 後続フェーズ

### Phase 6B: scene fast path / preparation

対象:

- `scene_fast_path.py`
- `scene_preparation.py`
- public facade の `scene_renderer.py`

主な分割:

- fast path eligibility
- character interval / movement expression
- filter graph plan
- command execution
- background layout / source
- badge overlay
- face precache
- image layer state
- character / background persistence

注意:

- fast path の適用条件を広げない
- scene-unit 巨大 filter graph 化は行わない
- `scene_renderer.py` の `render_scene` も 80 行以下を目標にする

### Phase 5: clip renderer

対象:

- `components/video/clip_renderer.py`
- `components/video/clip/characters.py`
- `components/video/clip/face.py`
- `components/video/clip/effects/resolve.py`

主な分割:

- input collection
- character / face state
- filter graph plan
- command generation
- command execution
- result validation

### Phase 3: subtitle PNG / overlay

対象:

- `components/subtitles/png.py`
- `components/video/overlays.py`
- `components/subtitles/generator.py`

主な分割:

- style / background
- PNG draw / metadata
- executor lifecycle
- subtitle chunk / range plan
- overlay filter plan
- overlay execution

### Phase 4: FFmpeg utility / cache

対象:

- `utils/ffmpeg_ops.py`
- `utils/ffmpeg_capabilities.py`
- `cache.py`

主な分割:

- background filters
- concat / transition
- media normalize
- capability probe / smoke
- media metadata / probe cache / normalized media cache

### Phase 7: 残存超過

対象候補:

- `pipeline_phases/finalize_phase.py`
- `utils/ffmpeg_runner.py`
- `components/video/scene_renderer.py`
- `components/markdown/pipeline.py`
- `video_phase/main.py`
- その他 80 行超関数

FinalizePhase は 2026-08-05 に cache self-healing と transition wait の修正が入った直後のため、
回帰テストを安定させてから transition plan、cache、concat へ分ける。

## 6. 全体方針

- 1 PR は 1 責務
- public API、import path、YAML、CLI、cache key、FFmpeg の意味を維持
- 移動前に characterization test を追加
- 元の入口は薄い facade / orchestration として残す
- pure plan と I/O を分離
- `Dict[str, Any]` を新モジュール内へ無制限に広げず、必要なら dataclass を使う
- 性能経路では `performance_regression_ledger.md` に従って前後比較
- 各 PR 後に source metrics を記録
- 例外を握りつぶす範囲を増やさない
- リファクタリングと新機能・高速化を同じ PR に混ぜない

## 7. PR ごとの検証

最低限:

```bash
git diff --check
python3 -m compileall -q zundamotion tests
python3 -m pytest -q -s \
  tests/test_scene_renderer_module_split.py \
  tests/test_scene_renderer_subtitle_flow.py \
  tests/test_scene_cache_fingerprint.py \
  tests/test_scene_cache_invalidation_diagnostics.py \
  tests/test_character_movement.py
python3 -m pytest -q -s
python3 scripts/report_source_metrics.py \
  --json-output output/source-metrics.json \
  --markdown-output output/source-metrics.md
```

FFmpeg とフォントがある環境:

```bash
python3 -m zundamotion.main scripts/refactor_validation_check.yaml \
  -o output/refactor_validation_check.mp4 \
  --no-voice \
  --no-cache \
  --hw-encoder cpu \
  --quality speed \
  --debug-log
```

CI 必須:

- unit tests
- FFmpeg integration
- wheel / sdist
- clean wheel install
- CPU render smoke
- no-voice reproducibility
- source metrics artifact

性能経路を移動した PR:

- 同一 YAML
- 同一 runtime lock
- 同一 cache 条件
- `VideoPhase`
- line clip total / p90
- `scene_concat_ms`
- cache hit / miss
- FFmpeg / ffprobe call count

を前後比較する。

## 8. 非対象

- YAML schema 変更
- CLI 仕様変更
- FFmpeg 処理方式の変更
- cache key の意図的な変更
- fast path の適用範囲拡大
- 巨大 filter graph 化
- Formatter / mypy の導入
- 複数の巨大モジュールを同時に分割する PR
