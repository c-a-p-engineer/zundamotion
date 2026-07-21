# AGENTS.md

このファイルは、`zundamotion` 本体で AI / Codex が常時読む最小ルールだけを置く。
詳細な実装規約は `docs/guides/ai_coding_rules.md` を正とし、必要時だけ参照する。

## 1. 最初に確認するもの

1. `README.md`
2. `scripts/script_cheatsheet.md`
3. `docs/README.md`
4. `docs/guides/ai_coding_rules.md`

性能、設計、サンプル対応を触る場合は `docs/README.md` から該当詳細へ進む。

## 2. 作業ごとに読む資料

- Python 実装を触るとき
  - `docs/guides/project_structure.md`
  - `docs/guides/python_coding_rules.md`
  - 必要に応じて対象モジュールの近接コード
- YAML オプション、台本挙動、サンプルを触るとき
  - `scripts/script_cheatsheet.md`
  - `docs/features.md`
  - `docs/script_samples.md`
- CLI、セットアップ、実行方法を触るとき
  - `docs/guides/setup_and_runtime.md`
  - `README.md`
- Docker runtime、digest、固定ランタイム更新を触るとき
  - `docs/guides/runtime_version_policy.md`
- 再現性、乱数、media 比較、cache key を触るとき
  - `docs/guides/reproducibility_contract.md`
- 性能、並列度、キャッシュ、FFmpeg 経路を触るとき
  - `docs/guides/performance_regression_ledger.md`
  - `docs/guides/performance_tuning.md`
  - `docs/design/ffmpeg_filter_mapping.md`
- pipeline や設計分割を触るとき
  - `docs/guides/project_structure.md`
  - `docs/guides/source_refactoring_plan.md`
  - `docs/guides/refactoring_check.md`
  - `docs/design/parser_and_builder.md`
  - 必要に応じて `docs/design/` の関連資料
- 立ち絵や素材前提を触るとき
  - `docs/guides/character_assets.md`
- submodule 利用前提や親プロジェクト連携を触るとき
  - `docs/guides/submodule.md`
- 不採用判断、保留事項、再検討条件を確認するとき
  - `docs/issues_pending.md`
  - 必要に応じて `docs/guides/song_mode_rejected.md`

作業前に、対象変更に対応する資料を読んでから実装する。不要な資料まで広く読まず、変更理由に直結する範囲へ絞る。

## 3. 変更対象の原則

- 通常の作業は `zundamotion/`、`scripts/`、`docs/`、`tools/` の範囲で完結できるかを先に確認する
- YAML オプション、CLI オプション、設定項目、挙動フラグを追加・変更した場合は、`README.md`、`scripts/script_cheatsheet.md`、関連 docs の更新要否を確認する
- 設定項目を追加・変更した場合は、利用者向けの正本に「項目名」「意味」「設定可能値」「デフォルト値」を記載し、省略時挙動や他設定との優先順位がある場合はそれも明記する
- 大きな仕様追加や不採用判断は、判断理由と再検討条件を `docs/issues_pending.md` または `docs/guides/` に残す
- `visible` 未指定時の表示や暗黙的なキャラクター補完など、設定ミス補正か仕様変更かが曖昧な挙動は実装前に確認する
- 新しい資料を `docs/` 配下へ追加した場合は、`AGENTS.md` に「何のときに読む資料か」を追記する
- 新しい資料が主要な入口になる場合は、`docs/README.md` の導線も更新する

## 4. 参照先

- docs 入口: `docs/README.md`
- AI 向け低トークン規約: `docs/guides/ai_coding_rules.md`
- Python コード規約: `docs/guides/python_coding_rules.md`
- 機能一覧: `docs/features.md`
- サンプル台本一覧: `docs/script_samples.md`
- 性能変更時: `docs/guides/performance_regression_ledger.md`
- 台本 YAML 仕様: `scripts/script_cheatsheet.md`

## 5. ログと安全

- 日本語での説明、コメント、ドキュメント更新を基本にする
- 標準出力への `print` は避け、既存の logger を使う
- 差分最小を優先し、無関係な整形や大規模置換をしない
- 本番資格情報、トークン、社内 URL、PII をログ、出力、サンプルへ含めない

## 6. 完了時の確認

- 実装変更がある場合は、関連 docs とサンプル更新要否を確認したか報告する
- 何を読んだか、なぜ他を読まなかったかを簡潔に説明できる状態にする
- 新しい資料を追加した場合は、`AGENTS.md` と `docs/README.md` の更新有無を確認したか報告する
- 未確認事項、残課題、必要なら `docs/issues_pending.md` への追記有無を報告する
