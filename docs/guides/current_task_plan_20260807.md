# 現行タスク計画（2026-08-07）— 履歴

状態: **superseded / 履歴資料**

このファイルは 2026-08-07 時点の作業計画を保存するための記録です。
ここに記載されていた #33、#39、#40、#41、#42、#43 などの作業は、その後の PR 群で完了または判断済みです。
**現在の未完了事項や次タスクを判断するためには使用しません。**

現在状態の正本:

- [`project_status.md`](./project_status.md)
- [`../issues_pending.md`](../issues_pending.md)
- [`performance_regression_ledger.md`](./performance_regression_ledger.md)

## この計画から完了した主要項目

| 当時の対象 | 現在の状態 | 主な後続記録 |
| --- | --- | --- |
| #33 Run Base | 完了 | Phase 6A 系列へ統合 |
| #39 Phase 6A standard renderer | 完了 | PR #57 まで |
| #40 Subtitle segment/audio | 完了 | PR #58〜#62、#79、#81 |
| #41 CacheManager | 完了 | PR #68 |
| #42 Phase 6B / CPU fast path評価 | 完了 | PR #63〜#67。CPU fast path は不採用 |
| #43 Clip / Subtitle / FFmpeg / Finalize 残分割 | 完了 | PR #69〜#74、#82〜#84、最終監査 #87 |

その後発生した CPU overlay-heavy stall #77 も PR #78 / #80 で修正済みです。

## 2026-08-07 時点で得られた基準

この計画が作られた時点では、固定 cold / warm benchmark、cache observability、FFmpeg / ffprobe 計測、subtitle 指標、A/V warning 等が整備され、大規模分割と性能改善を安全に進めるための基準線が形成されていました。

後続の性能判断は `performance_regression_ledger.md` と `performance_logs/` に集約しています。

## 履歴資料として残す理由

- 当時の依存順と判断理由を追跡できる
- 後続 PR が何を解消したか確認できる
- 同じ大規模リファクタリングを再度「未完了」と誤認しないための比較点になる

AI / Codex はこのファイル内の旧優先順位や旧チェック状態を現在の作業指示へ変換してはいけません。
