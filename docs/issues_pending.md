# 未確定の課題

このファイルには、**現在も未確定の事項**と、**再検討条件を持つ不採用判断**だけを置きます。
現在状態と優先順位は `guides/project_status.md`、性能の採用・却下履歴は `guides/performance_regression_ledger.md` を正とします。

完了したリファクタリングや解消済み性能課題はここへ残しません。

## J-cut の実レンダー契約

- 状態: 要再検証
- 現状: `j_cut.duration` による映像 pre-padding は実装済みです。
- 未確定: 音声先行、字幕、scene 境界、transition を同時に含む E2E characterization が不足しています。
- 懸念: 単体ロジックだけが正しくても、最終 timeline / A/V sync で差が出る可能性があります。
- 完了条件: 実レンダーで A/V timing と出力順を固定し、`docs/features.md` の状態を「実装済み」へ変更できること。

## Audio worker 1 / 2 の長尺既定値

- 状態: 実測待ち
- 現状: AudioPhase の bounded concurrency と worker policy は実装済みです。
- 未確定: 同一長尺 YAML で worker 1 / 2 のどちらを既定として妥当とするか。
- 懸念: worker 増加が VOICEVOX Engine の負荷・失敗率・総時間に対して常に有利とは限りません。
- 完了条件: 同一 runtime / YAML で AudioPhase、total elapsed、VOICEVOX failure、timeline order、出力同等性を比較し、既定値の判断を記録すること。

## Generic public motion target abstraction の採用見送り

- 状態: 採用見送り（再検討条件あり）
- 現状: character / camera / background は内部の MotionTrack helper を部分的に共有していますが、public contract は異なります。
- 不採用理由:
  1. character は persistent position/scale と line-local rotate/opacity を持ち、face overlay追従も必要です。
  2. camera は bounded world viewport と world/screen-space 境界を所有し、line-localです。
  3. background pan/zoom は background-local effect ownerで、legacy no-keyframe clamp/fallback互換を持ちます。
  4. 現時点でこれらを `motion.targets[]` のような共通public DSLへ押し込んでも、利用者・実装双方の複雑性を減らしません。
- 再検討条件:
  1. 2つ以上のownerが同一public target/property/lifecycle schemaを必要とする。
  2. owner-specific adapter間でvalidation/loweringの実質的重複が増える。
  3. Character Runtimeがstable rig subtarget IDを導入し、target referenceが利用者価値を持つ。
  4. AI authoringがowner-specific capabilityだけでは安全にtargetを選択できない実例が蓄積する。
- 現在の代替方針: owner-specific authoring/capabilityを維持し、共通化は内部のpure MotionTrack helperまでに留めます。
- 詳細: `design/motion_preset_contract.md`

## 歌唱機能 (`song`) の採用見送り

- 状態: 採用見送り
- 背景: VOICEVOX song API を使った歌唱機能を試作したが、Zundamotion の本来用途との整合性を再評価しました。
- 理由:
  1. 長い歌を 1 本として扱うと字幕 cue が長くなり、字幕運用と相性が悪い。
  2. 長時間歌唱を YAML で記述するコストが高い。
  3. 楽曲・BGMとの同期責務が動画生成本体へ入り込み、保守範囲が広がる。
  4. 外部で生成した音声を既存 BGM / 音声取り込みで扱える。
- 再検討条件: 短いジングル、固定フレーズ等に用途を限定し、字幕分割、記法、BGM同期、保守責務を明確に分離できる場合。
- 詳細: `guides/song_mode_rejected.md`

## 記録ルール

新しい項目を追加する場合は、最低限次を記載します。

- 状態
- 現状の事実
- 未確定事項
- 懸念または不採用理由
- 完了条件または再検討条件

単なる将来アイデアや優先順位付きタスク一覧はここへ置かず、`guides/project_status.md` で管理します。
