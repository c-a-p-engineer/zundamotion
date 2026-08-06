# 2026-08-06 レンダリングログ解析と追加タスク

この文書は、次の2件の実行ログを解析し、`source_refactoring_plan.md` の残作業を性能・診断面から補完する。

- `20260806_163214_570.log`
  - `scripts/copipetan-dev-room/072_security_incognito-mode.yaml`
  - CPU / speed / 初回キャッシュに近い長尺レンダー
- `20260806_161922_927.log`
  - `scripts/sample.yaml`
  - CPU / speed / scene cache がほぼ有効な短尺レンダー

2件は YAML、動画時間、キャッシュ状態が異なるため、直接的な速度比較には使わない。同一 YAML・同一 runtime lock・同一 CPU 条件で cold / warm を測るベンチマークを追加タスクとする。

## 1. 解析結果

### 1.1 長尺・初回レンダー

| 指標 | 計測値 |
| --- | ---: |
| 出力動画時間 | 767.98 秒 |
| 総実行時間 | 4,287.16 秒 |
| 実時間倍率 | 5.58 倍 |
| AudioPhase | 538.81 秒 |
| VideoPhase | 3,663.80 秒 |
| FinalizePhase | 89.31 秒 |
| FFmpeg 呼び出し | 292 回 |
| ffprobe 呼び出し | 669 回 |
| line clip | 185 本 |
| subtitle chunk | 27 本 |
| intermediate files | 86 本 / 168.0 MB |
| cache hit / miss / write | 1,297 / 996 / 998 |

主要な処理時間:

| 処理 | 時間 | 総実行時間比 |
| --- | ---: | ---: |
| line clip 描画 | 1,859.57 秒 | 43.4% |
| 字幕焼き込み | 814.28 秒 | 19.0% |
| scene concat | 70.72 秒 | 1.6% |
| face precache | 48.66 秒 | 1.1% |

line clip は185本すべて cache miss で、平均10.05秒、p95 17.22秒、最大25.08秒だった。実行環境は `nproc=12` だが、`clip_workers=1`、`scene_workers=1`、codec threads=1 で動作している。

字幕は183種類の PNG が各2回参照され、PerfSummary上は `subtitle_png=366` と記録されている。27個の字幕chunkの焼き込みに合計814.28秒を要し、最遅chunkは55.94秒だった。

ffprobe の主な呼び出しは次のとおり。

| caller | 回数 | 累積時間 |
| --- | ---: | ---: |
| `concat_copy_safety` | 213 | 27.20 秒 |
| `has_audio_stream` | 190 | 13.61 秒 |
| `generate_audio` | 185 | 19.49 秒 |
| `subtitle_chunk_duration` | 27 | 1.30 秒 |

全体は正常終了し、`av_warnings_total=0`、最終音声の `duration_delta=0.004739` だった。現在確認できる問題は出力破損ではなく、cold renderの処理量、重複probe、再エンコード回数、並列度、診断精度である。

### 1.2 短尺・warm cacheレンダー

| 指標 | 計測値 |
| --- | ---: |
| 出力動画時間 | 87.59 秒 |
| 総実行時間 | 20.88 秒 |
| 実時間倍率 | 0.238 倍 |
| AudioPhase | 4.94 秒 |
| VideoPhase | 6.34 秒 |
| FinalizePhase | 1.34 秒 |
| BGMPhase | 6.63 秒 |
| FFmpeg 呼び出し | 5 回 |
| ffprobe 呼び出し | 15 回 |
| cache hit / miss / write | 102 / 1 / 3 |
| scene cacheにより省略したline clip | 26 本 |

scene cache は6sceneすべてHITし、line clip、字幕PNG、字幕burnは実行されていない。それでもVideoPhaseは6.34秒を要し、BGMPhaseは6.63秒で全phase中最大だった。

全体は正常終了し、`av_warnings_total=0`、最終音声の `duration_delta=0.018964` だった。warm cacheの機能自体は有効だが、cache lookup、media metadata確認、BGM再合成に固定費が残っている。

## 2. 確認した問題点

### P0: 契約違反・比較基盤

1. **明示的CPU指定でもハードウェアencoder smoke testが実行される**
   - `hw_encoder=cpu`かつ`DISABLE_HWENC=1`でVideoRendererはCPUになっている。
   - その後の動画normalizeでNVENC、QSVのsmoke testが実行され、警告と長いstderrを出している。
   - encoder選択契約がnormalize経路まで伝播していない。

2. **2ログを直接比較できる統一ベンチマークがない**
   - YAML、尺、cache状態が異なる。
   - 改善前後を定量判定するには同一入力のcold / warm反復が必要。

### P1: 主要性能ボトルネック

3. **CPU資源に対してline clip描画が直列**
   - 12論理CPUに対し、line clip 185本をworker 1、codec threads 1で処理している。
   - line clipだけで約31分を占める。

4. **字幕焼き込みの再エンコード時間が大きい**
   - 27chunk、合計13分34秒。
   - 30〜38秒程度のchunkで40〜56秒かかる例がある。

5. **字幕処理後に音声を再エンコードしている**
   - 各sceneのline concatでAAC再エンコードした後、字幕chunk結合でも`lossy_audio_encoder_delay`を理由にAAC再エンコードしている。
   - 字幕は映像処理なので、音声を分離して最後に1回だけmuxできる余地がある。

6. **warm cacheでもBGMを毎回再合成する**
   - scene、transition、finalize concatがHITしていてもBGMPhaseが6.63秒かかる。
   - 短いwarm renderでは最大phaseになっている。

7. **media probeが用途別に重複する**
   - cold renderで669回。
   - duration、stream有無、concat安全性が別processとして呼ばれ、同一artifactを複数回probeする。

### P2: 固定費・診断精度

8. **scene cache HITにも約0.6〜1.4秒/sceneの固定費がある**
   - warm sampleで6sceneすべてHITだがVideoPhaseが6.34秒。
   - key生成、asset fingerprint、cache validationのどこが支配的か追加計測が必要。

9. **face overlayの永続cache参照が多い**
   - cold renderで20種類に対して949回のcache accessがある。
   - 同一run内のpath解決をメモ化できる余地がある。

10. **AudioPhaseのcold生成が約9分**
    - 185発話を生成し、各WAVをffprobeでduration確認している。
    - VOICEVOXへのbounded concurrencyと生成結果からのduration伝播を検証する余地がある。

11. **CPUではsimple fast pathが一律skipされている**
    - 各sceneで`skipping simple fast path (cpu_encoder)`となる。
    - Phase 6B完了後に、CPUでも再現性を維持できる適用範囲を評価する必要がある。

12. **PerfSummaryの一部指標が実生成数と要求数を区別しない**
    - 183種類の字幕PNGに対し`subtitle_png=366`。
    - persistent cache HITと同一run内再利用も同じ`cache_hit`へ集約されている。

13. **scene cache miss理由が粗い**
    - base artifactが存在しない場合でもsub側は`subtitle_or_base_key_changed`になる。
    - `previous_key == current_key`、`changed_components=none`でも同じ理由が出る。

## 3. 追加タスク一覧

各行を原則1 PRとする。性能変更は構造分割PRと混在させず、characterization testと同一YAMLの前後ベンチを付ける。

| 優先 | ID | 実装単位 | 主な変更先 | 完了条件 |
| ---: | --- | --- | --- | --- |
| P0 | PERF-00 | cold / warmベンチマーク固定 | `tools/zundamotion_perf_benchmark.py`, CI artifact | 同一YAML、同一runtime lockでcold 1回・warm 2回を記録し、phase、line p50/p95、subtitle burn、FFmpeg/ffprobe、cacheをJSON比較できる |
| P0 | BUG-CPU-ENC-01 | CPU指定時のGPU encoder probe停止 | `ffmpeg_capabilities.py`, normalize encoder選択 | `--hw-encoder cpu`または`DISABLE_HWENC=1`でNVENC/QSV/VideoToolbox smokeを呼ばず、CPU codecだけを使用する |
| P1 | 6A-3E-PERF | line clip bounded executor | `scene_line_executor.py`, `scene_auto_tune.py` | worker 1/2/3とthread budgetを比較し、結果順序・cache key・出力を維持した構成を選ぶ。12CPU cold benchmarkでworker 1より悪化しない |
| P1 | SUB-EXEC-01 | 字幕chunk実行計画の最適化 | `subtitle_chunk_plan.py`, `subtitle_overlay_graph.py`, `overlays.py` | 巨大graph化せず、chunk境界と再エンコード範囲を見直し、同一入力で`subtitle_burn_ms`を比較する |
| P1 | SUB-AUDIO-01 | 字幕処理中の音声再エンコード排除 | `scene_assembly.py`, subtitle executor, concat utility | 字幕burnを映像のみへ適用し、元scene音声をcopy/muxする。A/V deltaとtransitionを回帰テストで固定する |
| P1 | BGM-CACHE-01 | 最終BGM mix cache | `bgm_phase.py`, cache metadata | finalized video fingerprint、BGM segment、volume、audio paramsをkeyにし、warm再実行でBGM FFmpegを省略する |
| P1 | PROBE-CACHE-01 | media probe統合 | `cache_media_probe.py`, `ffmpeg_ops.py` | 1回のffprobe結果からduration/streams/media paramsを共有し、同一immutable pathのrun内再probeをしない |
| P2 | CACHE-LATENCY-01 | scene cache HIT遅延の内訳計測 | `scene_cache.py`, cache fingerprint | key build、source fingerprint、artifact validation、copyの時間を別metric化し、warm 6sceneの6.34秒を説明できる |
| P2 | CACHE-MEMO-01 | run内asset fingerprint/path memo | cache、asset metadata cache | 同一pathのstat/digest/cache lookupをrun内で再利用し、keyの意味を変えない |
| P2 | FACE-MEMO-01 | face overlay run内memo | `scene_face_precache.py`, face overlay cache | 20種類に対する949回の永続cache accessを、種類数に近いlookup回数まで削減する |
| P2 | AUDIO-PERF-01 | TTS bounded concurrency | `audio_phase_speech.py`, VoiceVox adapter | speaker順序とtimelineを維持し、VOICEVOX負荷上限を設定したworker 1/2比較を行う |
| P2 | AUDIO-DURATION-01 | WAV durationの生成結果伝播 | audio generator、media probe cache | 生成直後のWAVを別ffprobe processで再確認せず、WAV headerまたは生成metadataからdurationを返す |
| P2 | 6B-CPU-FAST-01 | CPU fast path適用可能性の検証 | `scene_fast_path_eligibility.py`, fast path benchmark | Phase 6B分割後、CPUでも安全なsceneだけを対象にし、標準pathとの出力・A/V・cache差を比較する |
| P2 | OBS-CACHE-01 | cache指標の内訳追加 | `perf_stats.py`, cache manager | persistent HIT、same-run HIT、MISS、WRITE、validation failureを別集計する |
| P2 | OBS-SUBTITLE-01 | subtitle PNG指標の修正 | subtitle generator、`perf_stats.py` | request、unique key、generated、persistent hit、same-run hitを分け、183種類と366要求を区別する |
| P2 | OBS-SCENE-MISS-01 | scene miss理由の精密化 | `scene_cache.py`, invalidation diagnostics | key変更、artifact欠損、metadata欠損、subtitle config変更、base変更を別reasonとして出す |

## 4. 既存リファクタリング計画への組み込み

| 既存フェーズ | 追加するログ由来タスク |
| --- | --- |
| Phase 0 | `PERF-00` |
| Phase 6A-3 | `6A-3E-PERF`、line metricsの内訳 |
| Phase 6A-4 | `SUB-AUDIO-01`、scene assembly計測 |
| Phase 6B | `FACE-MEMO-01`、`6B-CPU-FAST-01` |
| Phase 3 | `SUB-EXEC-01`、`OBS-SUBTITLE-01` |
| Phase 4 | `BUG-CPU-ENC-01`、`PROBE-CACHE-01`、`CACHE-LATENCY-01`、`CACHE-MEMO-01`、`OBS-CACHE-01`、`OBS-SCENE-MISS-01` |
| AudioPhase後続 | `AUDIO-PERF-01`、`AUDIO-DURATION-01` |
| BGMPhase後続 | `BGM-CACHE-01` |

## 5. 実施順

構造分割を止めて性能変更へ全面移行はしない。次の順序とする。

1. `PERF-00`と`BUG-CPU-ENC-01`を独立PRで処理する。
2. 予定どおりRun Base、line clip、scene assemblyの責務分割を進める。
3. line executor境界確定後に`6A-3E-PERF`を実施する。
4. scene assembly境界確定後に`SUB-AUDIO-01`を実施する。
5. Phase 3で`SUB-EXEC-01`、Phase 4でprobe/cache系を処理する。
6. BGM cache、AudioPhase concurrency、CPU fast pathは独立ベンチ付きPRとして処理する。

性能改善の採否は実時間だけで決めない。再現性、A/V同期、cache互換、失敗時診断、メモリ使用量を同時に確認する。
