# 現行タスク計画（2026-08-07）

この文書は、2026-08-06の2件の実レンダーログ、Phase 6Aの進捗、2026-08-07にmasterへ反映した性能・診断変更を統合した現行タスク表です。

## 0. 基準

- 確認時master: `2c9f59d0b8b4f4f932d8aa83992d6dfbf0b41521`
- 未マージPR: 0
- 正しさ優先: legacy Run Baseは既定無効
- 既存契約: YAML、CLI、public import、cache key、FFmpegの意味を原則維持
- 検証状態: PR #24、#26〜#38はmaster反映済みだが、このGitHub App接続ではPR Actions結果を確認できていない。Issue #44完了まで「CI未確認」とする

## 1. 今回masterへ反映したタスク

| ID | 実装単位 | PR | 状態 | 主な成果 |
|---|---|---:|---|---|
| PERF-00 | cold/warm固定ベンチ | #24 | 反映済み・CI未確認 | cold 1回、warm 2回、PerfSummary・ログ・動画・比較JSON・runtime/input hash |
| BUG-CPU-ENC-01 | CPU encoder policy伝播 | #26 | 反映済み・CI未確認 | 1 renderの間だけ`DISABLE_HWENC=1`、終了時復元 |
| BGM-CACHE-01 | final BGM mix cache | #27 | 反映済み・CI未確認 | persistent finalize入力のBGM再合成をwarm時省略 |
| AUDIO-DURATION-01 | WAV header duration | #28 | 反映済み・CI未確認 | PCM WAVのduration ffprobeをRIFF header読取へ置換 |
| PROBE-CACHE-01 | stream/duration統合probe | #29 | 反映済み・CI未確認 | `-show_streams -show_format` 1回でstreamとdurationを共有 |
| OBS-SCENE-MISS-01 | Scene Cache MISS分類 | #30 | 反映済み・CI未確認 | manifest missing/version/corrupt/read failureを区別 |
| AUDIO-PERF-01A | Audio worker policy | #31/#37 | 反映済み・CI未確認 | requested/resolved/sourceを診断、既存monkeypatch seam維持 |
| FACE-MEMO-01 | face overlay run memo | #32 | 反映済み・CI未確認 | 同一要求のPath/in-flight taskをrun内共有 |
| RUN-BASE-PLAN | original-index planner | #34 | 反映済み・CI未確認 | waitを含む元行番号、signature、offsetを純粋計画化 |
| RUN-BASE-SAFETY | legacy optimizer停止 | #35 | 反映済み・CI未確認 | 誤描画可能性のあるinline Run Baseを既定無効 |
| CACHE-LATENCY-01A | Scene cache lookup計時 | #36 | 反映済み・CI未確認 | base/sub HIT/MISS別のlookup総時間と回数 |
| OBS-SUBTITLE-01 | Subtitle PNG指標分離 | #38 | 反映済み・CI未確認 | request/unique/repeat/persistent/ephemeral/generatedを分離 |

## 2. 新たに判明した問題

### P0: Run Baseの元行番号とsignature境界

Issue #33。

- waitを除外した配列indexを元のscene行番号として使う可能性
- signature変更時に次runのinsert情報を前runへ混入する可能性
- 現在はlegacy optimizerを既定無効にして正しさを保護
- 正しいplanner/renderer接続までは性能最適化だけ停止

### P0: 今回の変更群の回帰検証

Issue #44。

- compileall
- 全unit test
- FFmpeg integration
- wheel/sdistとclean install
- CPU render smoke
- no-voice reproducibility
- cold/warm Performance Smoke
- sample warm render
- source metrics再生成

## 3. 残タスク一覧

### P0

| 順序 | Issue | 実装単位 | 完了条件 |
|---:|---:|---|---|
| 1 | #44 | 現masterの回帰検証 | 必須CI、CPU smoke、再現性、cold/warm artifactが成功 |
| 2 | #33 | Run Base renderer/runtime接続 | inline legacy block削除、planner利用、original line offset、A/V同等 |

### P1

| 順序 | Issue | 実装単位 | 主なPR分割 |
|---:|---:|---|---|
| 3 | #39 | Phase 6A標準描画分割 | Run Base I/O、LineContext、wait、talk plan/render、executor、metrics、assembly、cache、cleanup、orchestration |
| 4 | #40 | 字幕segment最適化 | range plan、video-only segment、video concat、元音声1回mux、bounded executor |
| 5 | #39 | line clip性能比較 | jobs 1/2/3とFFmpeg thread budgetをPERF-00条件で比較 |
| 6 | - | Audio worker実測 | worker 1/2を長尺同一YAMLで比較し、auto既定を維持または変更 |

### P2

| 順序 | Issue | 実装単位 | 主なPR分割 |
|---:|---:|---|---|
| 7 | #41 | CacheManager内部改善 | signature memo、status分類、latency内訳、media metadata、削除理由/manifest同期 |
| 8 | #42 | Phase 6BとCPU fast path評価 | preparation、eligibility、graph、execution、実験フラグ、benchmark |
| 9 | #43 | Clip/Subtitle/FFmpeg/Finalize残分割 | Phase 5、3、4、7を依存順に実施 |

## 4. 実装順

```text
#44 現master回帰検証
  ↓
#33 Run Base正規接続
  ↓
#39 Phase 6A Line/Assembly/Orchestration
  ↓
#40 Subtitle segment/audio
  ↓
#41 CacheManager
  ↓
#42 Phase 6B / CPU fast path評価
  ↓
#43 ClipRenderer / FFmpeg / Finalize残分割
```

## 5. 今回採用しなかった進め方

- CI未確認の状態を「全タスク完了」と扱う
- Run Baseの既知バグをそのまま新モジュールへ移す
- subtitle segment audio、line executor、CacheManager分割を1PRへ混在させる
- CPU fast pathの適用範囲を検証前に広げる
- 巨大filter graph化で短期的にFFmpeg回数だけを減らす

## 6. 各PRの最低条件

1. 1 PR 1責務
2. characterization test先行
3. public import/YAML/CLI/cache key維持
4. FFmpeg commandの意味とA/V同期を明示
5. unit/FFmpeg integration成功
6. CPU smoke/no-voice reproducibility成功
7. 性能経路はPERF-00で前後比較
8. source metricsを記録
9. CI結果を確認してからmasterへ統合
