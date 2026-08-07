# 現行タスク計画（2026-08-07）

この文書は、2026-08-06の2件の実レンダーログ、Phase 6Aの進捗、2026-08-07にmasterへ反映した性能・診断変更を統合した現行タスク表です。

## 0. 基準

- 検証対象master: `b7d1315266aa6864e73db659e2571be64de93de4`
- 回帰検証PR: #46
- 検証head: `6e4c7611cb5786ed386e350b0bd3ca383e6ca112`
- CI run: `31135886560` success
- Performance Smoke run: `31135886525` success
- 正しさ優先: legacy Run Baseは既定無効
- 既存契約: YAML、CLI、public import、cache key、FFmpegの意味を原則維持
- 詳細ログ: [`performance_logs/20260807_issue44_validation.md`](./performance_logs/20260807_issue44_validation.md)

## 1. master反映済み・回帰検証済みタスク

| ID | 実装単位 | PR | 状態 | 主な成果 |
|---|---|---:|---|---|
| PERF-00 | cold/warm固定ベンチ | #24/#46 | 検証済み | cold 1回、warm 2回、PerfSummary・ログ・動画・比較JSON・runtime/input hash |
| BUG-CPU-ENC-01 | CPU encoder policy伝播 | #26/#46 | 検証済み | 1 renderの間だけ`DISABLE_HWENC=1`、終了時復元 |
| BGM-CACHE-01 | final BGM mix cache | #27/#46 | 検証済み | persistent finalize入力のBGM再合成をwarm時省略 |
| AUDIO-DURATION-01 | WAV header duration | #28/#46 | 検証済み・互換修正 | PCM WAVはRIFF header読取、旧delegate signatureも維持 |
| PROBE-CACHE-01 | stream/duration統合probe | #29/#46 | 検証済み | `-show_streams -show_format` 1回でstreamとdurationを共有 |
| OBS-SCENE-MISS-01 | Scene Cache MISS分類 | #30/#46 | 検証済み | manifest missing/version/corrupt/read failureを区別 |
| AUDIO-PERF-01A | Audio worker policy | #31/#37/#46 | 検証済み | requested/resolved/sourceを診断、既存monkeypatch seam維持 |
| FACE-MEMO-01 | face overlay run memo | #32/#46 | 検証済み | 同一要求のPath/in-flight taskをrun内共有 |
| RUN-BASE-PLAN | original-index planner | #34/#46 | 検証済み | waitを含む元行番号、signature、offsetを純粋計画化 |
| RUN-BASE-SAFETY | legacy optimizer停止 | #35/#46 | 検証済み・責務修正 | 誤描画可能性を遮断し、標準描画オーケストレーション所有権を維持 |
| CACHE-LATENCY-01A | Scene cache lookup計時 | #36/#46 | 検証済み | base/sub HIT/MISS別のlookup総時間と回数 |
| OBS-SUBTITLE-01 | Subtitle PNG指標分離 | #38/#46 | 検証済み | request/unique/repeat/persistent/ephemeral/generatedを分離 |

## 2. Issue #44 回帰検証結果

以下をすべて成功確認した。

- runtime lock検証
- unit tests
- FFmpeg integration tests
- wheel / sdist build
- clean wheel install
- CPU render smoke
- no-voice media reproducibility
- cold/warm Performance Smoke
- source metrics生成

検証中に2件の回帰を検出し、PR #46内で修正した。

1. `AudioDurationCacheProxy`が`caller`非対応delegateへkeyword引数を強制していた
2. Run Base safety guardが`_render_scene_internal`をoverrideし、標準描画の責務境界を破っていた

### 固定cold/warm実測

| 指標 | cold | warm1 | warm2 |
|---|---:|---:|---:|
| elapsed | 6.735s | 0.773s | 0.759s |
| VideoPhase | 5187.6ms | 55.0ms | 55.5ms |
| AudioPhase | 446.1ms | 360.6ms | 344.4ms |
| FinalizePhase | 99.4ms | 14.4ms | 28.6ms |
| ffmpeg calls | 22 | 8 | 8 |
| ffprobe calls | 19 | 4 | 4 |
| line clips | 4 | 0 | 0 |
| subtitle burn | 236.0ms | 0ms | 0ms |
| A/V warning | 0 | 0 | 0 |

warm2 / coldは`0.112695`。warmでもAudioPhase約0.35秒、FFmpeg 8回、ffprobe 4回が残る。

## 3. 現在のP0問題

### Run Baseの元行番号とsignature境界

Issue #33。

- wait除外後のindexを元scene行番号として扱う可能性
- signature変更時に次runのinsert情報を前runへ混入する可能性
- legacy optimizerは既定無効で誤描画リスクを遮断済み
- 次は正しいplannerを生成I/Oとruntimeへ接続する

## 4. 残タスク一覧

### P0

| 順序 | Issue | 実装単位 | 完了条件 |
|---:|---:|---|---|
| 1 | #33 | Run Base renderer/runtime接続 | inline legacy block削除、planner利用、original line offset、A/V同等 |

### P1

| 順序 | Issue | 実装単位 | 主なPR分割 |
|---:|---:|---|---|
| 2 | #39 | Phase 6A標準描画分割 | Run Base I/O、LineContext、wait、talk plan/render、executor、metrics、assembly、cache、cleanup、orchestration |
| 3 | #40 | 字幕segment最適化 | range plan、video-only segment、video concat、元音声1回mux、bounded executor |
| 4 | #39 | line clip性能比較 | jobs 1/2/3とFFmpeg thread budgetをPERF-00条件で比較 |
| 5 | - | Audio worker実測 | worker 1/2を長尺同一YAMLで比較し、auto既定を維持または変更 |

### P2

| 順序 | Issue | 実装単位 | 主なPR分割 |
|---:|---:|---|---|
| 6 | #41 | CacheManager内部改善 | signature memo、status分類、latency内訳、media metadata、削除理由/manifest同期 |
| 7 | #42 | Phase 6BとCPU fast path評価 | preparation、eligibility、graph、execution、実験フラグ、benchmark |
| 8 | #43 | Clip/Subtitle/FFmpeg/Finalize残分割 | Phase 5、3、4、7を依存順に実施 |

## 5. 実装順

```text
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
