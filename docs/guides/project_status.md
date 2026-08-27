# 現在状態と次の作業

更新日: 2026-08-27

このファイルは、Zundamotion の**現在状態、未完了事項、次に着手する作業**の正本です。
AI / Codex が「今どこまで終わっているか」「次に何をするか」を確認するときは、日付付きの過去計画ではなくこのファイルを優先します。

## 1. 現在の基準線

- `master` は大規模な責務分割フェーズを完了済みです。
- PR #87 の最終統合監査では unit / FFmpeg integration / wheel・sdist build / clean wheel install / CPU render smoke / no-voice reproducibility が成功しています。
- 同検証の Performance Smoke は cold 6.251s / warm1 0.782s / warm2 0.774s、A/V warning 0 です。
- 再現性検証では video framemd5、audio PCM、sidecar の比較が一致しています。
- source metrics 上の大きいファイルや長い関数は残っていますが、互換 facade や既存契約維持の責務を含むため、数値超過だけを理由に追加分割しません。
- 次の製品層として、AI / CI がレンダー前に利用する machine-readable compiler interface、TTS Provider 境界、project-level Render Lock / provenance を追加するフェーズへ移行しています。

## 2. 完了した主要フェーズ

| 領域 | 状態 | 主な記録 |
| --- | --- | --- |
| Phase 6A standard scene rendering | 完了 | #39、PR #57 までで orchestration を分割 |
| Subtitle segment 性能改善 | 完了 | #40、PR #58〜#62、#79、#81 |
| CacheManager 診断・probe・lifecycle | 完了 | #41、PR #68 |
| Phase 6B scene preparation / fast path | 完了 | #42、PR #63〜#67 |
| CPU simple scene fast path | 不採用 | PR #67。性能根拠を得られず standard path を維持 |
| ClipRenderer | 完了 | #43、PR #69 |
| Subtitle internals | 完了 | #43、PR #70〜#71 |
| FFmpeg high-level ops / capabilities | 完了 | #43、PR #72〜#73 |
| Finalize / FFmpeg runner / VideoPhase / Markdown | 完了 | #43、PR #74、#82〜#84 |
| CPU overlay-heavy stall | 修正済み | #77、PR #78、#80。静止画入力の有限化で終端停止も防止 |
| 最終構造監査 | 完了 | PR #87 |
| machine-readable compiler interface | 実装 | `validate` / `compile` / `capabilities`、compiled-config v1 |
| TTS Provider 基盤 | 実装 | 共通 Provider / capability、VOICEVOX compatibility adapter。第二providerは未実装 |
| Render Lock / provenance | 実装 | script / compiled-config / asset / runtime lock hash と `verify-lock` |

詳細な高速化の採用・却下理由は `performance_regression_ledger.md` を正とします。
過去の分割計画は `source_refactoring_plan.md`、2026-08-07 時点のタスク表は `current_task_plan_20260807.md` に履歴として残します。

## 3. 現在の未完了事項

### P0: 正しさ・基準線の確定

1. **J-cut の E2E characterization**
   - `j_cut.duration` の映像 pre-padding 実装は存在します。
   - 音声先行、字幕、scene 境界、transition を含む実レンダー契約を固定する必要があります。
   - 完了条件: A/V timing と出力順を再現可能なテストで固定し、`docs/features.md` の「要再検証」を解消できること。

2. **Audio worker 1/2 の長尺実測**
   - bounded concurrency と worker policy 自体は実装済みです。
   - 同一長尺 YAML で worker 1/2 を比較し、既定値を維持するか変更するかを決めます。
   - 完了条件: AudioPhase / total elapsed / VOICEVOX failure / timeline order / output equivalence を比較可能な記録として残すこと。

### P1: 次の製品フェーズ

1. **0.1.0 リリース基準線の確定**
   - GitHub Release、配布物、リリースノート、公開手順を整理します。
2. **多言語 TTS / 字幕契約**
   - `TTSProvider` 境界を前提に、無料・OSSを優先して第二provider候補を検証します。
   - language、font fallback、reading/display、provider固有voice ID、cache identity の扱いを定義します。
3. **AI 向け authoring harness の完成**
   - `capabilities -> authoring -> validate -> compile -> lock -> verify-lock -> render` の機械可読基盤は実装済みです。
   - 次は AI が必要最小限の資料を読み、diagnosticから局所修正し、scene単位の確認へ進めるガイド / harness を整備します。
4. **0.1.x compiler contract の安定化**
   - `compiled-config` / validation / capabilities / Render Lock の v1 契約を実運用で確認し、破壊変更が必要な場合は format version を上げます。

### P2: 表現力・運用性

- キャラクター位置に連動した音声 pan
- cache / log 保守 CLI
- move / pan / zoom の複数 keyframe
- template catalog / version 管理
- storyboard / scene単位 partial render

## 4. 現時点でやらないこと

- CPU simple scene fast path の再導入
- 行数・関数長の閾値を満たすことだけを目的にした追加リファクタリング
- `song` 機能の再導入
- GUI 本体を CLI / headless 契約より先に作ること
- arbitrary FFmpeg filter 文字列を無制限に公開設定へ開放すること
- Render Lock 内からネットワーク上の生成AIや外部assetを自動取得すること

再検討条件がある不採用・保留事項は `../issues_pending.md` に記録します。

## 5. 状態更新ルール

- 実装や検証で現在状態が変わったら、このファイルを更新します。
- 完了した作業を「次タスク」として残しません。
- 実装履歴や詳細ログは専用資料へ残し、このファイルを履歴ログ化しません。
- 日付付き計画や解析資料は、その日付時点の証拠として扱い、現在状態の正本にしません。
- Issue の有無と内部タスクの有無を混同しません。Issue 化していない作業もここには記録できます。
- feature branch / PR 上では、実装済みと検証済みを区別し、CI未確認の変更を `master` の確定基準線として扱いません。
