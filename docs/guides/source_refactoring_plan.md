# ソースリファクタリング完了記録

状態: **完了 / 履歴資料**

このファイルは、2026年に実施した Zundamotion の大規模責務分割の履歴を残すための資料です。
**現在のタスク計画ではありません。** 現在状態と次の作業は [`project_status.md`](./project_status.md) を参照してください。

## 目的

既存の YAML、CLI、public import、cache key、FFmpeg の意味を維持しながら、AI / Codex が変更時に読む範囲を小さくし、巨大な単一関数へ責務が集中する状態を解消することを目的に実施しました。

## 完了した領域

| 領域 | 結果 | 主な記録 |
| --- | --- | --- |
| Phase 0: baseline / source metrics | 完了 | PR #14 |
| Phase 1: validation 分割 | 完了 | validation responsibility split |
| Phase 2: Pipeline / AudioPhase | 完了 | PR #15〜#18 |
| Phase 6A: standard scene rendering | 完了 | #39、PR #57 まで |
| Phase 6B: preparation / fast path | 完了 | #42、PR #63〜#67 |
| CacheManager | 完了 | #41、PR #68 |
| Phase 5: ClipRenderer | 完了 | #43、PR #69 |
| Phase 3: Subtitle internals | 完了 | #43、PR #70〜#71 |
| Phase 4: FFmpeg utility / capabilities | 完了 | #43、PR #72〜#73 |
| Phase 7: Finalize / runner / VideoPhase / Markdown | 完了 | #43、PR #74、#82〜#84 |
| 最終構造監査 | 完了 | PR #87 |

## 最終判断

PR #87 の統合監査時点で、主要 hot path は専用モジュールへ分割され、public facade と互換境界が固定されています。

source metrics には 500 行超ファイルや 80 行超関数が残っていますが、次の理由から**数値超過だけを根拠に追加分割しません**。

- historical compatibility を保持する facade / base がある
- active public dispatch は既に modular runtime へ向いている
- 追加削除に runtime benefit がなく、互換性リスクだけが増える箇所がある
- 行数や関数長は問題検出の指標であり、達成目標そのものではない

今後の構造変更は、具体的な機能追加、バグ、計測された性能問題、保守上の変更集中が確認された場合にだけ行います。

## 維持した契約

大規模分割では原則として次を維持しました。

- YAML schema / 解釈
- CLI contract
- public import
- cache key と cache semantics
- FFmpeg input / filter / map / timestamp の意味
- A/V sync
- timeline 順序
- CPU render smoke
- no-voice reproducibility

性能経路を変更した箇所は、同一条件 benchmark と A/V検証を別途実施しています。
詳細は [`performance_regression_ledger.md`](./performance_regression_ledger.md) と `performance_logs/` を参照してください。

## 代表的な現在の責務境界

- scene standard rendering: context / precache / line pipeline / assembly / cache / orchestration
- fast path: preparation / eligibility / character plan / graph / executor
- clip rendering: input / policy / video・audio graph / command / executor / pipeline
- subtitle: PNG internals / segment plan / overlay graph / execution
- FFmpeg: background / normalize / concat / transition / capability / process / diagnostics
- cache: runtime / media probe / lifecycle / observability / signatures
- Finalize: cache / transitions / concat / orchestration

現在のファイル対応は [`project_structure.md`](./project_structure.md) を正とします。

## 履歴資料の扱い

このファイルや日付付きタスク計画に未完了チェックが残っていても、それを現在タスクとして扱いません。
現在状態は必ず `project_status.md` と実装・テスト・最新PRを照合して判断します。
