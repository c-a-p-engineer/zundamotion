# 現在状態と次の作業

更新日: 2026-09-25

このファイルは、Zundamotion の**現在状態、未完了事項、次に着手する作業**の正本です。
AI / Codex が「今どこまで終わっているか」「次に何をするか」を確認するときは、日付付きの過去計画ではなくこのファイルを優先します。

中長期の製品ゴール、設計原則、フェーズ順序は [product_roadmap.md](./product_roadmap.md) を正とします。

## 1. 現在の基準線

- `master` は大規模な責務分割フェーズを完了済みです。
- J-cut の現行互換挙動は E2E characterization 済みです。`j_cut.duration` は同一行の pre-roll + audio delay として動き、字幕は pre-roll 冒頭から表示されます。一般的な音声先行J-cut semantics は未実装として明示します。
- PR #87 の最終統合監査では unit / FFmpeg integration / wheel・sdist build / clean wheel install / CPU render smoke / no-voice reproducibility が成功しています。
- 同検証の Performance Smoke は cold 6.251s / warm1 0.782s / warm2 0.774s、A/V warning 0 です。
- 再現性検証では video framemd5、audio PCM、sidecar の比較が一致しています。
- source metrics 上の大きいファイルや長い関数は残っていますが、互換 facade や既存契約維持の責務を含むため、数値超過だけを理由に追加分割しません。
- AI / CI 向け machine-readable compiler interface と TTS Provider 境界は導入済みです。
- project-level Render Lock / provenance があり、`capabilities -> validate -> compile -> lock -> verify-lock -> render` の事前検査経路があります。
- TTS Provider は `voicevox` と `chatterbox` を公開しています。VOICEVOX を既定とし、Chatterbox Multilingual V3 は optional runtime として扱います。
- Chatterbox は23言語、行単位の言語切替、voice cloning等へ対応していますが、remote model artifact の runtime lock、font fallback、実モデルbenchmark等は未完了です。
- SVG character rig は v2 の source-part / joint / pivot 検証と blink / lip-sync / hair / limb motion preview まで authoring / QA 側に実装済みです。本体rendererへのruntime統合はまだ行いません。
- product roadmap は **low-spec first / Motion over complexity / Progressive enhancement / Compiler-Orchestrator** を中長期原則とし、標準rendererは引き続き Python + FFmpeg とします。

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
| machine-readable compiler interface | 完了 | PR #89。`validate` / `compile` / `capabilities`、compiled-config v1 |
| TTS Provider 基盤 | 完了 | 共通Provider / capability、VOICEVOX互換、Chatterbox optional provider |
| Render Lock / provenance | 完了 | script / compiled-config / asset / runtime lock hash と `verify-lock` |
| SVG character rig authoring v2 | 完了 | source-part / joint / pivot validation と motion preview。runtime統合は別フェーズ |

詳細な高速化の採用・却下理由は `performance_regression_ledger.md` を正とします。
過去の分割計画は `source_refactoring_plan.md`、2026-08-07 時点のタスク表は `current_task_plan_20260807.md` に履歴として残します。

## 3. 現在の未完了事項

### P0: 正しさ・基準線の確定

1. **Audio worker 1/2 の長尺実測**
   - bounded concurrency と worker policy 自体は実装済みです。
   - 同一長尺 YAML で worker 1/2 を比較し、既定値を維持するか変更するかを決めます。
   - 完了条件: AudioPhase / total elapsed / provider failure / timeline order / output equivalence を比較可能な記録として残すこと。

### P1: 0.1.x Foundation stabilization

1. **0.1.0 リリース基準線の確定**
   - GitHub Release、配布物、リリースノート、公開手順を整理します。

2. **TTS / 多言語契約の安定化**
   - VOICEVOX / Chatterbox の共通 capability 境界を実運用で確認します。
   - language、font fallback、reading/display、provider固有voice ID、cache identity を整理します。
   - Chatterbox の remote model artifact / transitive runtime lock と実モデルbenchmarkは、通常VOICEVOX runtimeを重くしない形で扱います。

3. **AI 向け authoring harness の完成**
   - machine-readable な事前検査経路は実装済みです。
   - AI が必要最小限の資料を読み、diagnosticから局所修正し、scene単位の確認へ進めるガイド / harness を整備します。

4. **0.1.x compiler contract の安定化**
   - `compiled-config` / validation / capabilities / Render Lock の v1 契約を実運用で確認し、破壊変更が必要な場合は format version を上げます。

### P2: 0.2 Motion Core

次の表現力フェーズの最優先です。

- move / pan / zoom の複数 keyframe
- easing
- generic motion track
- position / scale / rotate / opacity
- camera track と character motion の責務分離
- motion preset
- motion-aware cache identity
- motion capability / validation
- representative frame / actual video QA

最初から任意frame callbackやbrowser runtimeを導入しません。
既存 `move` / pan / zoom を同一motion contractへ段階的に寄せます。

### P3: 0.3 Character Runtime

Motion Core の基準線を確認してから着手します。

- SVG rig / rig config の runtime model
- blink / lip-sync
- breathing / body sway
- head / hair motion
- simple arm / limb gesture
- reaction preset
- existing PNG character path への fallback
- character state / expression / persist / motion の統合規則

現在の SVG rig authoring / validator / preview を再利用し、本体rendererからブラウザSVG DOMを毎frame描画する方式は既定にしません。

### P4: 0.4 Materialize / Rich Scene

Motion Core / Character Runtime でも費用対効果が悪い具体的sceneが確認できた後に比較します。

- render backend contract
- scene単位のrenderer selection
- materialized clip
- provenance / cache / lock
- partial rerender
- Remotion / Web Canvas / Lottie / Rive 等の optional adapter 比較

Rich renderer を標準依存にすることは既定方針ではありません。

### P5: 0.5 AI Director / Voice Ecosystem

- scene / shot plan
- camera / motion / expression preset selection
- insert / overlay selection
- provider capability negotiation
- external TTS の materialize / provenance
- scene-level preview / partial render
- automatic render QA feedback

Google系など新しいcloud TTSを追加する場合も、既存 `TTSProvider` 境界を使い、timeline / render coreへ直接埋め込みません。

## 4. 現時点でやらないこと

- CPU simple scene fast path の再導入
- 行数・関数長の閾値を満たすことだけを目的にした追加リファクタリング
- `song` 機能の再導入
- GUI 本体を CLI / headless 契約より先に作ること
- arbitrary FFmpeg filter 文字列を無制限に公開設定へ開放すること
- Render Lock 内からネットワーク上の生成AIや外部assetを自動取得すること
- Remotion / Web Canvas / browser runtime への全面移行
- Motion Core の評価前に独自2D engineを新規所有すること

再検討条件がある不採用・保留事項は `../issues_pending.md` に記録します。
中長期の再検討条件は [product_roadmap.md](./product_roadmap.md) を参照します。

## 5. 次の実装順序

原則として次の順です。

1. P0の正しさ未確定項目を閉じる
2. 0.1.x release / compiler / provider 基準線を整理する
3. Motion Core の behavior contract を定義する
4. multi-keyframe + easing の最小縦切りを実装する
5. 少数の motion preset で実動画を比較する
6. Motion Core の費用対効果を確認して Character Runtime へ進む
7. native経路で不足する具体例が集まってから Rich Renderer を比較する

## 6. 状態更新ルール

- 実装や検証で現在状態が変わったら、このファイルを更新します。
- 完了した作業を「次タスク」として残しません。
- 実装履歴や詳細ログは専用資料へ残し、このファイルを履歴ログ化しません。
- 中長期の原則や phase 順序は `product_roadmap.md` を更新し、このファイルへ重複記載しすぎません。
- 日付付き計画や解析資料は、その日付時点の証拠として扱い、現在状態の正本にしません。
- Issue の有無と内部タスクの有無を混同しません。Issue 化していない作業もここには記録できます。
- feature branch / PR 上では、実装済みと検証済みを区別し、CI未確認の変更を `master` の確定基準線として扱いません。
