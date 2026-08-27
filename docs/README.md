# Zundamotion docs

このディレクトリは、Zundamotion の利用仕様、実装ガイド、設計記録、性能・判断履歴を置く場所です。
AI / Codex が常時読む最小ルールはリポジトリ直下の `AGENTS.md`、コード変更時の低トークン規約は `guides/ai_coding_rules.md` を正とします。

## まず読む

- [`../README.md`](../README.md): 利用者向け概要、セットアップ、主要機能
- [`../AGENTS.md`](../AGENTS.md): AI / Codex の最小運用ルール
- [`guides/project_status.md`](./guides/project_status.md): **現在状態、未完了事項、次の作業の正本**
- [`../scripts/script_cheatsheet.md`](../scripts/script_cheatsheet.md): YAML 台本仕様の利用者向け正本
- [`features.md`](./features.md): 機能一覧と実装状態

「次に何をするか」を調べる場合は、日付付き計画や過去ログではなく `guides/project_status.md` を優先してください。

## 実装・運用ガイド

| 文脈 | 資料 |
| --- | --- |
| AI / Codex 実装規約 | [`guides/ai_coding_rules.md`](./guides/ai_coding_rules.md) |
| Python 構造・分割規約 | [`guides/python_coding_rules.md`](./guides/python_coding_rules.md) |
| セットアップ、CLI、実行 | [`guides/setup_and_runtime.md`](./guides/setup_and_runtime.md) |
| AI / CI 向け validate / compile / capabilities | [`guides/compiler_interface.md`](./guides/compiler_interface.md) |
| TTS backend の provider 境界 | [`guides/tts_provider.md`](./guides/tts_provider.md) |
| project-level Render Lock / provenance | [`guides/render_lock.md`](./guides/render_lock.md) |
| runtime lock、更新・rollback | [`guides/runtime_version_policy.md`](./guides/runtime_version_policy.md) |
| 再現性、乱数、media比較、cache key | [`guides/reproducibility_contract.md`](./guides/reproducibility_contract.md) |
| GitHub Pages機能デモ | [`guides/github_pages_feature_demo.md`](./guides/github_pages_feature_demo.md) |
| プロジェクト構造 | [`guides/project_structure.md`](./guides/project_structure.md) |
| 性能チューニング | [`guides/performance_tuning.md`](./guides/performance_tuning.md) |
| 性能の採用・却下・回帰履歴 | [`guides/performance_regression_ledger.md`](./guides/performance_regression_ledger.md) |
| 立ち絵・表情差分素材 | [`guides/character_assets.md`](./guides/character_assets.md) |
| submodule 利用 | [`guides/submodule.md`](./guides/submodule.md) |

## 設計資料

- [`design/yaml_schema_draft.md`](./design/yaml_schema_draft.md): YAML schema 草案
- [`design/parser_and_builder.md`](./design/parser_and_builder.md): YAML → IR / filter graph の設計
- [`design/ffmpeg_filter_mapping.md`](./design/ffmpeg_filter_mapping.md): FFmpeg filter 対応表
- [`design/effects_extensibility_plan.md`](./design/effects_extensibility_plan.md): effect 拡張方針
- [`design/markdown_input_pipeline_plan.md`](./design/markdown_input_pipeline_plan.md): Markdown input 設計記録

## 利用者向け補助資料

- [`script_samples.md`](./script_samples.md): サンプル台本カタログ
- [`../site/README.md`](../site/README.md): GitHub Pages デモサイト運用
- [`user_simple_plugin.md`](./user_simple_plugin.md): ユーザープラグイン例

## 未確定・不採用判断

- [`issues_pending.md`](./issues_pending.md): 現在も未確定の事項と、再検討条件を持つ不採用判断
- [`guides/song_mode_rejected.md`](./guides/song_mode_rejected.md): `song` 不採用判断の詳細

## 履歴資料

以下は現在状態の正本ではありません。過去の判断根拠や比較条件を確認するときだけ参照します。

- [`guides/source_refactoring_plan.md`](./guides/source_refactoring_plan.md): 2026年の大規模責務分割の完了記録
- [`guides/current_task_plan_20260807.md`](./guides/current_task_plan_20260807.md): 2026-08-07 時点のタスク計画。現在は `project_status.md` に置換済み
- [`guides/render_log_analysis_20260806.md`](./guides/render_log_analysis_20260806.md): 2026-08-06 実レンダーログ解析。後続改善の根拠資料
- `guides/performance_logs/`: 個別性能検証ログ

## 文書の役割分担

- **現在状態・次タスク**: `guides/project_status.md`
- **利用仕様**: `scripts/script_cheatsheet.md`, `features.md`
- **作業規則**: `AGENTS.md`, `guides/ai_coding_rules.md`, `guides/python_coding_rules.md`
- **machine-readable authoring契約**: `guides/compiler_interface.md`
- **TTS backend 境界**: `guides/tts_provider.md`
- **入力 provenance**: `guides/render_lock.md`
- **性能判断**: `guides/performance_regression_ledger.md`
- **未確定・再検討条件**: `issues_pending.md`
- **履歴**: 日付付き計画、解析ログ、完了済みリファクタリング記録

同じ内容を複数資料へ複製せず、詳細は正本へ置き、他資料からリンクします。
