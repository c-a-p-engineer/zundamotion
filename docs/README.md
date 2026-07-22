# Zundamotion docs

このディレクトリは、Zundamotion 本体の設計資料、機能一覧、利用ガイド、性能検証メモを置く場所です。  
AI / Codex 向けの常時ルールはリポジトリ直下の `AGENTS.md`、低トークン実装規約は `guides/ai_coding_rules.md` を正とします。

## 入口

- [`../README.md`](../README.md): 利用者向けの概要、セットアップ、主要機能
- [`../AGENTS.md`](../AGENTS.md): AI / Codex が作業する際の運用ルール
- [`guides/ai_coding_rules.md`](./guides/ai_coding_rules.md): AI / Codex がコードや CLI を触るときの低トークン実装規約
- [`guides/python_coding_rules.md`](./guides/python_coding_rules.md): Python 実装の構成、命名、分割、AI 向け低トークン規約
- [`../scripts/script_cheatsheet.md`](../scripts/script_cheatsheet.md): 台本 YAML の早見表
- [`features.md`](./features.md): 実装済み機能と計画中機能の一覧
- [`script_samples.md`](./script_samples.md): 同梱サンプル台本のカタログ

## Guides

- [`guides/setup_and_runtime.md`](./guides/setup_and_runtime.md): セットアップ、CLI 実行、ログ形式、GPU/NVENC 確認
- [`guides/runtime_version_policy.md`](./guides/runtime_version_policy.md): runtime lock、digest、固定値更新、ロールバック
- [`guides/reproducibility_contract.md`](./guides/reproducibility_contract.md): 入力・メディア意味・byte 一致の再現性契約と検証
- [`guides/github_pages_feature_demo.md`](./guides/github_pages_feature_demo.md): `master`を正本に、実生成動画付き機能デモサイトを構築・公開するAI向け運用規約
- [`guides/project_structure.md`](./guides/project_structure.md): 技術スタックとリポジトリ構成
- [`guides/python_coding_rules.md`](./guides/python_coding_rules.md): Python コード規約と AI 向け分割基準
- [`guides/source_refactoring_plan.md`](./guides/source_refactoring_plan.md): P0第一段階の完了範囲と、既存 Python ソースを後続で段階分割する計画
- [`guides/refactoring_check.md`](./guides/refactoring_check.md): リファクタリング後のテスト、台本ロード、動画生成確認
- [`guides/performance_tuning.md`](./guides/performance_tuning.md): 高速化オプションと上級者向け運用メモ
- [`guides/submodule.md`](./guides/submodule.md): 利用側プロジェクトへ git submodule として取り込む手順
- [`guides/song_mode_rejected.md`](./guides/song_mode_rejected.md): 歌唱機能 (`song`) の検証結果と不採用判断の記録
- [`guides/performance_regression_ledger.md`](./guides/performance_regression_ledger.md): 高速化の履歴、採用/却下判断、再計測時の注意
- `guides/performance_logs/`: 性能検証ログの個別メモ
- [`guides/character_assets.md`](./guides/character_assets.md): 立ち絵・表情差分素材を作るときのメモ

## Design

- [`design/yaml_schema_draft.md`](./design/yaml_schema_draft.md): YAML スキーマ草案
- [`design/parser_and_builder.md`](./design/parser_and_builder.md): YAML から IR / filter_complex 生成への設計メモ
- [`design/ffmpeg_filter_mapping.md`](./design/ffmpeg_filter_mapping.md): FFmpeg フィルタ対応表
- [`design/effects_extensibility_plan.md`](./design/effects_extensibility_plan.md): エフェクト拡張方針
- [`design/markdown_input_pipeline_plan.md`](./design/markdown_input_pipeline_plan.md): Markdown 入力パイプライン計画

## Notes

- [`issues_pending.md`](./issues_pending.md): 未確定の課題とP0対象外の後続リファクタリング
- [`user_simple_plugin.md`](./user_simple_plugin.md): ユーザープラグイン例
