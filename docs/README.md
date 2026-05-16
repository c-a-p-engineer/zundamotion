# Zundamotion docs

このディレクトリは、Zundamotion 本体の設計資料、機能一覧、利用ガイド、性能検証メモを置く場所です。  
AI / Codex 向けの作業ルールはリポジトリ直下の `AGENTS.md` を正とします。

## 入口

- `../README.md`: 利用者向けの概要、セットアップ、主要機能
- `../AGENTS.md`: AI / Codex が作業する際の運用ルール
- `../scripts/script_cheatsheet.md`: 台本 YAML の早見表
- `features.md`: 実装済み機能と計画中機能の一覧
- `script_samples.md`: 同梱サンプル台本のカタログ

## Guides

- `guides/submodule.md`: 利用側プロジェクトへ git submodule として取り込む手順
- `guides/performance_regression_ledger.md`: 高速化の履歴、採用/却下判断、再計測時の注意
- `guides/performance_logs/`: 性能検証ログの個別メモ
- `guides/character_assets.md`: 立ち絵・表情差分素材を作るときのメモ

## Design

- `design/yaml_schema_draft.md`: YAML スキーマ草案
- `design/parser_and_builder.md`: YAML から IR / filter_complex 生成への設計メモ
- `design/ffmpeg_filter_mapping.md`: FFmpeg フィルタ対応表
- `design/effects_extensibility_plan.md`: エフェクト拡張方針
- `design/markdown_input_pipeline_plan.md`: Markdown 入力パイプライン計画

## Notes

- `issues_pending.md`: 未確定の課題
- `user_simple_plugin.md`: ユーザープラグイン例
