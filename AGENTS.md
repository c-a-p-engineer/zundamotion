# AGENTS.md

このファイルは、`zundamotion` で AI / Codex が常時読む**最小ルール**だけを置く。
詳細な実装規約は `docs/guides/ai_coding_rules.md`、現在状態と次タスクは `docs/guides/project_status.md` を正とし、必要時だけ参照する。

## 1. 最初に確認するもの

常時読む入口は次の 3 つに限定する。

1. `README.md`
2. `docs/guides/project_status.md`
3. `docs/README.md`

その後、作業種別を判定して「作業ごとの正本」から必要な資料だけを読む。
`scripts/script_cheatsheet.md` は YAML / 台本仕様を扱う場合だけ読む。コード、CLI、FFmpeg、cache、設計を変更する場合は `docs/guides/ai_coding_rules.md` を追加で読む。
日付付きタスク計画、過去ログ、完了済みリファクタリング計画を現在状態の正本として扱わない。

## 2. 作業ごとの正本

| 作業 | 最初に読む資料 |
| --- | --- |
| 現在状態、次タスク、完了状況 | `docs/guides/project_status.md` |
| Python 実装、責務分割 | `docs/guides/project_structure.md`, `docs/guides/python_coding_rules.md` |
| YAML、台本挙動、サンプル | `scripts/script_cheatsheet.md`, `docs/features.md`, `docs/script_samples.md` |
| CLI、セットアップ、実行 | `docs/guides/setup_and_runtime.md`, `README.md` |
| AI / CI authoring、`validate` / `compile` / `capabilities` | `docs/guides/compiler_interface.md`, `zundamotion/authoring.py`, `zundamotion/cli.py` |
| TTS backend / Provider 境界 | `docs/guides/tts_provider.md`, `zundamotion/components/audio/provider.py` と対象 backend |
| Render Lock、入力 provenance | `docs/guides/render_lock.md`, `docs/guides/reproducibility_contract.md`, `docs/guides/runtime_version_policy.md` |
| runtime lock、Docker、固定バージョン | `docs/guides/runtime_version_policy.md` |
| 再現性、乱数、media比較、cache key | `docs/guides/reproducibility_contract.md` |
| 性能、並列度、cache、FFmpeg経路 | `docs/guides/performance_regression_ledger.md`, `docs/guides/performance_tuning.md` |
| filter / A/V sync | `docs/design/ffmpeg_filter_mapping.md` と対象実装 |
| pipeline / scene / clip 構造 | `docs/guides/project_structure.md`, `docs/design/parser_and_builder.md` |
| 立ち絵・表情差分素材 | `docs/guides/character_assets.md` |
| GitHub Pages / demo | `docs/guides/github_pages_feature_demo.md`, `docs/features.md` |
| submodule 利用 | `docs/guides/submodule.md` |
| 未確定、不採用、再検討条件 | `docs/issues_pending.md` |

過去の性能比較が必要な場合だけ `docs/guides/performance_logs/` や日付付き解析資料を読む。
大規模責務分割の履歴を確認するときだけ `docs/guides/source_refactoring_plan.md` を読む。

## 3. 変更対象の原則

- 通常の変更は `zundamotion/`、`scripts/`、`docs/`、`tools/` の必要範囲だけで完結させる。
- 差分最小を優先し、無関係な整形や一括置換をしない。
- 1 PR は原則 1 責務とする。
- stacked PR は暫定状態として扱う。base PR が統合された後は current `master` との差分と mergeability を再確認し、必要なら current `master` から責務差分だけを再構成して CI を取り直す。
- 古い stacked branch の CI 成功を、current `master` への統合成功の証拠として扱わない。
- 行数や関数長の閾値を満たすことだけを目的に、動いている互換 facade を追加分割しない。
- 挙動変更と構造整理を同時に大きく混ぜない。

### 設定・利用者向け挙動

YAML、CLI、環境変数、preset、利用者向け挙動を追加・変更した場合は、正本へ次を記載する。

- 項目名
- 意味
- 設定可能値
- デフォルト値
- 省略時挙動
- 他設定との優先順位がある場合はその順序

同じ仕様説明を複数資料へ複製しない。

### 利用者向け機能

利用者向け機能を追加・変更した場合は、必要に応じて次を更新する。

- `docs/features.md`
- `scripts/script_cheatsheet.md`
- demo manifest / demo YAML / 実生成動画
- Pages 用テスト

`implemented` または利用者向け `partial` 機能を Pages へ掲載する場合は、現在の Zundamotion で生成したデモ動画と制限事項を必須とする。

## 4. FFmpeg / Python の最低ルール

### FFmpeg

- `filter_complex` 生成と process 実行を分離する。
- `fps`、`setpts`、`asetpts`、`concat`、`overlay`、`enable` を触る場合は A/V sync への影響を確認する。
- DEBUG ログから command を再現できる状態を維持する。
- 性能変更は `performance_regression_ledger.md` の過去採用・却下を確認し、同一条件で前後比較する。
- CPU simple scene fast path など、過去に実測で不採用となった方式を根拠なしに再導入しない。

### Python

- 副作用のある処理と純粋変換を分ける。
- YAML / 外部 I/O 境界以外へ `Dict[str, Any]` を無制限に広げない。
- 環境変数読み取りを深い処理へ散らさない。
- 標準出力への `print` は避け、既存 logger を使う。
- public import、YAML、CLI、cache key、machine-readable format の互換性を変更する場合は明示する。

## 5. ドキュメント管理

文書の役割は次で固定する。

- 現在状態・次タスク: `docs/guides/project_status.md`
- 利用仕様: `scripts/script_cheatsheet.md`, `docs/features.md`
- 作業規則: `AGENTS.md`, `docs/guides/ai_coding_rules.md`, `docs/guides/python_coding_rules.md`
- machine-readable authoring 契約: `docs/guides/compiler_interface.md`
- TTS backend 境界: `docs/guides/tts_provider.md`
- 入力 provenance: `docs/guides/render_lock.md`
- 出力再現性: `docs/guides/reproducibility_contract.md`
- 性能判断: `docs/guides/performance_regression_ledger.md`
- 未確定・再検討条件: `docs/issues_pending.md`
- 履歴: 日付付き計画、解析ログ、完了済みリファクタリング記録

新しい資料を追加するときは、既存の正本へ統合できないかを先に確認する。
主要な入口になる資料だけ `docs/README.md` と必要に応じてこのファイルへ導線を追加する。

## 6. GitHub Pages

- `master` 側を正本とし、`gh-pages` を直接編集しない。
- Pages 関連変更は `master` push 時だけ公開される条件を維持する。
- サイト未変更時に不要な deploy を増やさない。

## 7. ログと安全

- 日本語での説明、コメント、ドキュメント更新を基本にする。
- 本番資格情報、token、cookie、社内 URL、PII をログ、出力、サンプルへ含めない。
- 外部入力と plugin は信頼済みと仮定しない。
- Render Lock / provenance の検証中に network asset や生成AIを暗黙取得しない。

## 8. 完了時の確認

作業終了時は、変更内容に応じて次を確認する。

- 実装変更: unit / FFmpeg integration / smoke / reproducibility の必要範囲
- 性能変更: 同一条件 benchmark と A/V warning
- 利用者向け変更: README / cheatsheet / features / demo の更新要否
- machine-readable contract 変更: format version、stable key / error code / exit code、help、互換性テスト
- TTS Provider 変更: capability と既存 compatibility wrapper、AudioGenerator / timeline / cache 責務への影響
- Render Lock 変更: deterministic hash、difference code、network 非取得、出力再現性との責務分離
- 新規資料: `docs/README.md` とこの `AGENTS.md` の導線更新要否
- 現在状態が変わった場合: `docs/guides/project_status.md` の更新要否
- 未確定事項が生じた場合: `docs/issues_pending.md` への記録要否
- stacked PR: base 統合後の current `master` を基準に差分と CI を再確認したか

実行・確認していない検証を完了したと報告しない。
