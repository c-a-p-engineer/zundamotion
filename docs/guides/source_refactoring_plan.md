# ソースリファクタリング計画

Zundamotion の既存 Python コードを `python_coding_rules.md` に沿って段階的に分割する計画。
挙動、YAML、CLI、FFmpeg 出力を変えず、AI / Codex が変更時に読む範囲を小さくすることを目的とする。

## 1. 現状

2026-06-07 時点では、Python コード規約の上限 500 行を超えるファイルが 16 個ある。

優先して扱う対象:

| 対象 | 行数 | 最長関数 | 主な問題 |
| --- | ---: | ---: | --- |
| `components/pipeline_phases/video_phase/scene_renderer.py` | 2579 | 1174 | scene 準備、cache、line render、字幕、結合が混在 |
| `utils/ffmpeg_ops.py` | 1296 | 359 | 背景、concat、transition、normalize が混在 |
| `components/video/overlays.py` | 1160 | 258 | overlay 計画、字幕分割、filter 生成、実行が混在 |
| `components/config/validate.py` | 1155 | 450 | 全設定領域の validation が集中 |
| `components/subtitles/png.py` | 968 | 171 | style 解決、描画、metadata、worker 管理が混在 |
| `components/video/clip_renderer.py` | 875 | 832 | clip 描画全体が単一関数に集中 |
| `cache.py` | 874 | 128 | 複数種類の cache 責務が集中 |
| `pipeline.py` | 733 | 299 | フェーズ順序以外の設定、temp、集計責務が混在 |
| `components/pipeline_phases/audio_phase.py` | 630 | 557 | 音声フェーズ全体が単一関数に集中 |

現行テストは 30 ファイル、約 140 test function がある。ただし、設定 validation、pipeline、clip renderer の直接的な保護が不足している。
現在の環境では `pytest` コマンドが未導入のため、テストベースラインは未取得。

## 2. 全体方針

- 1 PR では 1 責務だけを分割する
- public API、import path、YAML、CLI、cache key、FFmpeg コマンドの意味を維持する
- 移動前に characterization test を追加し、現行挙動を固定する
- 元モジュールは薄い入口として残し、既存 import の互換性を維持する
- 性能経路を触る PR では `performance_regression_ledger.md` に従って前後比較する
- 各 PR 後に行数と長関数を再計測し、改善値を記録する

## 3. 完了条件

- 対象ファイルは原則 500 行以下、目安 200〜400 行に収める
- 対象関数は原則 80 行以下、目安 20〜40 行に収める
- `GenerationPipeline` はフェーズ順序制御を主責務とする
- FFmpeg コマンド生成と実行を別関数または別モジュールに分ける
- 既存テストと追加した characterization test が通る
- 代表 YAML の生成結果と A/V sync に意図しない変更がない
- 性能経路の変更では、同一条件ベンチマークに有意な悪化がない

## 4. フェーズ計画

### Phase 0: ベースラインと保護テスト

目的:

- リファクタリング前の挙動、テスト、性能、コード規模を固定する

作業:

- Dev Container または開発依存入り環境で `pytest -q` を実行する
- 行数、80 行超関数、500 行超ファイルの一覧を記録する
- validation、pipeline、clip renderer の characterization test を追加する
- 代表 YAML の no-voice 短尺レンダーと性能ベースラインを記録する

完了条件:

- 全テストの初期結果が記録されている
- 後続フェーズで比較する代表入力と確認項目が固定されている

進捗:

- 2026-06-07: 設定 validation 用 characterization test とチェック台本を追加
- 全テストは 149 件中 145 件成功。残り 4 件は FFmpeg / ffprobe と IPA フォント未導入による環境依存失敗

### Phase 1: 設定 validation の分割

対象:

- `components/config/validate.py`

分割案:

- `components/config/validate.py`: `validate_config` の入口と共通処理
- `components/config/validate_background.py`
- `components/config/validate_overlays.py`
- `components/config/validate_badges.py`
- `components/config/validate_layers.py`
- `components/config/validate_plugins.py`

理由:

- 純粋な検証処理が中心で、描画や性能経路より回帰範囲を限定しやすい
- 先に validation の直接テストを追加すれば、安全に責務分割できる

進捗:

- 2026-06-07: 完了
- `validate.py` を入口へ縮小し、background、overlay、badge、image layer、script traversal を分離
- 設定 validation 配下は全ファイル 500 行以下、全関数 80 行以下

### Phase 2: Pipeline と AudioPhase の分割

対象:

- `pipeline.py`
- `components/pipeline_phases/audio_phase.py`

分割案:

- pipeline の品質設定解決、temp directory 選択、最終 summary を専用モジュールへ移す
- `GenerationPipeline.run` は phase 作成、順序制御、結果受け渡しを中心にする
- AudioPhase の line 準備、音声生成、voice layer 解決、timeline 更新を分ける

注意:

- stats、timeline、cache、VOICEVOX 呼び出し回数を変えない
- 環境変数読み取りを設定解決箇所へ局所化する

### Phase 3: 字幕 PNG と overlay 計画の分割

対象:

- `components/subtitles/png.py`
- `components/video/overlays.py`
- `components/subtitles/generator.py`

分割案:

- subtitle style/background 解決
- PNG 描画と metadata 管理
- worker/executor 管理
- subtitle range/chunk 計画
- overlay filter 生成
- overlay 実行

注意:

- PNG サイズ、背景、alpha、字幕 timing、chunk 分割結果を固定する
- `test_subtitle_png.py`、`test_overlay_alpha_preservation.py`、`test_subtitle_ass.py` を保護テストとして使う

### Phase 4: FFmpeg utility の責務分割

対象:

- `utils/ffmpeg_ops.py`
- `utils/ffmpeg_capabilities.py`
- `cache.py`

分割案:

- 背景 filter 生成
- concat / transition
- media normalize
- capability probe / smoke test
- cache metadata / media probe cache / normalized media cache

注意:

- filter label、A/V sync、cache key、DEBUG ログからのコマンド再現性を維持する
- transition と normalize はコマンド生成と実行を分離する
- 性能ベースラインを前後比較する

### Phase 5: Clip renderer の分割

対象:

- `components/video/clip_renderer.py`
- `components/video/clip/characters.py`
- `components/video/clip/face.py`
- `components/video/clip/effects/resolve.py`

分割案:

- clip 入力収集
- character / face 状態解決
- filter graph 計画
- FFmpeg command 生成
- command 実行と結果確認

注意:

- `render_clip` の既存シグネチャを入口として維持する
- 先に代表的な character、face、effect 組み合わせの characterization test を追加する

### Phase 6: Scene renderer の段階分割

対象:

- `components/pipeline_phases/video_phase/scene_renderer.py`

分割案:

- `scene_preparation.py`: background、character、badge、line 状態の準備
- `scene_cache.py`: scene base / subtitle cache key と lookup
- `scene_fast_path.py`: simple scene fast path
- `scene_line_renderer.py`: line clip の生成と並列実行
- `scene_assembly.py`: scene base、字幕、最終結合
- `scene_renderer.py`: 上記を順番に呼ぶ入口

進め方:

1. 純粋な cache key と状態準備を抽出する
2. fast path を抽出して専用テストを追加する
3. line 処理を抽出する
4. scene assembly を抽出する
5. 最後に `_render_scene_internal` を薄い順序制御へ置き換える

注意:

- このフェーズは複数 PR に分ける
- scene cache hit、subtitle cache、character persistence、background persistence、A/V sync を毎回確認する
- 巨大 filter graph 化や処理経路の統合は行わない

### Phase 7: 残存する規約超過の整理

対象候補:

- `components/video/scene_renderer.py`
- `components/markdown/pipeline.py`
- `components/pipeline_phases/video_phase/main.py`
- `components/video/clip/effects/resolve.py`
- その他 500 行超ファイル

作業:

- 残った 500 行超ファイルと 80 行超関数を再計測する
- 責務とテスト保護状況に応じて、小さな PR に分けて対応する
- 例外的に上限超過を維持する場合は、理由と再検討条件を記録する

## 5. PR ごとの確認項目

- 読んだファイルと読まなかった理由を説明できるか
- 変更対象の public API と import path を維持しているか
- 変更対象ファイルと関数の行数が改善しているか
- pure function と I/O が分離されているか
- 既存テストと追加テストが通るか
- FFmpeg、cache、timeline、stats、docs への影響を確認したか
- 性能経路なら同一条件の前後比較を実施したか

## 6. 非対象

- YAML スキーマ変更
- CLI 仕様変更
- FFmpeg 処理方式の変更
- cache key の意図的な変更
- Formatter、mypy、CI の新規導入
- 複数の巨大モジュールを同時に分割する大規模 PR
