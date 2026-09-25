# Audio worker 1 / 2 benchmark — 2026-09-25

Issue: #101  
PR: #105  
GitHub Actions run: https://github.com/c-a-p-engineer/zundamotion/actions/runs/36116330292

## 目的

VOICEVOXを使うAudioPhaseのbounded concurrencyについて、worker 1 / 2のどちらを既定基準とするかを実測で判断する。

動画レンダー、字幕、GPU、scene/finalize処理は比較へ混ぜず、AudioPhaseだけを同一条件で測定した。

## 条件

- runner: GitHub-hosted `ubuntu-24.04`
- reported CPU count: 4
- platform: `Linux-6.17.0-1022-azure-x86_64-with-glibc2.39`
- Python: `3.14.6`
- VOICEVOX: `0.24.1`
- VOICEVOX image:
  `voicevox/voicevox_engine:cpu-ubuntu22.04-0.24.1@sha256:a6a96326ffda12a7292b235a6ef43d299ca33849993e262b230320e17c8c2be8`
- speaker: 3
- lines: 24
- cache: disabled; trialごとに独立directory
- provider retry attempts: 1
- trial order: `[1, 2, 2, 1]`
- benchmark commit: `1a344644c4e7035935fd766a6ea8c9d612a5cf0e`
- runtime lock SHA-256:
  `d6978e3a36502fd80a5af80bcac14233f99b1fa4612fa9eab995d054bc6366e6`

実行:

```bash
python tools/zundamotion_audio_worker_benchmark.py \
  --voicevox-url http://127.0.0.1:50021 \
  --speaker 3 \
  --lines 24 \
  --rounds 2
```

## 結果

| trial | workers | AudioPhase / benchmark total |
| ---: | ---: | ---: |
| 1 | 1 | 83.382s |
| 2 | 2 | 82.162s |
| 3 | 2 | 82.125s |
| 4 | 1 | 82.596s |

中央値:

| workers | median |
| ---: | ---: |
| 1 | 82.989s |
| 2 | 82.144s |

- worker 2 speedup vs worker 1: `1.010287x`
- worker 2 improvement: `1.018%`
- provider failures: `0`
- retry可能回数: `0`（benchmarkではattempt=1に固定）
- 全successful trialのdecode後PCM + timeline fingerprint: **一致**

## 出力同等性

各発話についてFFmpegでdecodeした `s16le` PCM SHA-256を比較した。

加えて次をtrial間で比較した。

- line order
- text
- audio duration
- timeline event order
- timeline start time
- timeline duration

4 trialすべてreferenceと一致した。

したがってworker 1 / 2の切替による出力順序・音声内容の差は、この条件では観測されなかった。

## 判断

**既存のworker policyは変更しない。**

現在の `auto` はCPU数に応じて最大2 workerを選択する。
今回の4 CPU環境ではworker 2はworker 1より約1.0%だけ速く、明確な高速化とは評価しない。

ただし:

- 出力同等性は保たれた
- failure増加はなかった
- worker 2が明確に悪化したEvidenceもない
- 既定値変更による互換・運用churnを正当化する差ではない

ため、既存のauto上限2を維持する。

同時に、**worker数を3以上へ増やす最適化の根拠にもならない**。
VOICEVOX側のCPU処理が支配的で、同一4 CPU runnerでは2並列化してもAudioPhase全体の短縮はほぼ得られなかった。

## 再検討条件

次の場合に再計測する。

- VOICEVOX engine / model / runtimeを変更した
- HTTP client / synthesis requestの並列処理を変更した
- AudioPhaseのtask schedulingを変更した
- 低スペック基準機を正式に固定した
- worker 2でfailure、memory pressure、thermal / load問題が観測された
- cloud / remote TTSなど別providerのconcurrency policyを決める

providerが変わる場合、このVOICEVOX結果をそのまま流用しない。

## 限界

- GitHub-hosted 4 CPU runnerの値であり、低スペック基準機そのものではない
- full video totalではなくAudioPhase-only
- no-cache cold synthesisを比較した
- retry/backoffは性能比較から除外した
- 24発話の固定scenarioであり、極端な短文・長文・多話者を網羅しない

したがって絶対秒数を一般化せず、今回のEvidenceは **同一環境におけるworker 1 / 2相対比較** として扱う。
