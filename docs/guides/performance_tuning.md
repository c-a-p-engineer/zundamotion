# パフォーマンスと運用

このガイドは、Zundamotion の高速化設定と上級者向け運用メモをまとめたものです。

関連:

- [docs 入口](../README.md)
- [README](../../README.md)
- [セットアップと実行](./setup_and_runtime.md)
- [性能改善の履歴](./performance_regression_ledger.md)

## 基本方針

- GPU エンコードが使えるなら活用する
- 字幕や RGBA オーバーレイは必要に応じて CPU フィルタへフォールバックする
- 長尺ではシーン分割とキャッシュ再利用を前提にする

## よく使う設定

```yaml
video:
  scene_base_min_lines: 6
  scene_workers: 1

voice:
  parallel_workers: auto

system:
  cache_scene_base_video: true
  generate_no_sub_video: false
```

## 主な最適化ポイント

- GPU オーバーレイ方針:
  - 完成版の字幕焼き込みは字幕装飾に応じて `ASS/libass` と `PNG` を自動切替
  - RGBA を含む overlay は基本的に CPU 側で合成
- CUDA 診断とフォールバック:
  - CUDA フィルタが失敗した場合は診断ログを出して CPU フィルタへフォールバック
  - `scale_cuda` が無い環境では自動で `scale_npp` を使用
- ハイブリッド GPU スケール:
  - `video.gpu_scale_with_cpu_overlay: true` で背景スケーリングだけ GPU を使う
- 字幕 PNG プリキャッシュ:
  - `video.precache_subtitles: true` で事前生成
- 字幕 PNG ワーカー共有:
  - ラン全体で `ProcessPoolExecutor` を共有
- 音声生成の先行起動:
  - `voice.parallel_workers=auto` は安定性優先で最大 2 並列
- シーン並列描画:
  - `video.scene_workers` を `auto` または整数で指定
- 単純シーン fast path:
  - 背景静止画、単一キャラ、通常発話だけのシーンは GPU エンコード時に適用
  - CPU版は実験機能で、既定では無効

## CPU simple scene fast path（実験機能）

CPUエンコード時のsimple scene fast pathは、性能評価のための内部実験です。通常実行では
従来どおりstandard pathを使用します。有効化する場合だけ次の環境変数を指定します。

```bash
ZUNDAMOTION_CPU_SCENE_FAST_PATH=1 zundamotion render script.yaml --out out.mp4
```

適用対象は意図的に狭くしています。

- 背景はシーン全体で同一の静止画
- `background.fit=stretch`
- 可視characterは1体だけで、全lineで同一の画像・位置・scale
- characterの`enter` / `leave` / `move`なし
- lineは通常`talk`または`wait`
- `insert` / `image_layers` / `voice_layers` / screen/background effect / `video_filter`なし
- PNG必須の字幕スタイルなし

1条件でも外れた場合、fast pathは使用せずstandard pathへフォールバックします。FFmpeg実行に
失敗した場合も同様です。`--no-cache`指定時はfast pathのscene動画も永続cacheへ保存しません。

この実験を既定有効へ昇格する条件は、同一YAML・runtime lock・CPU条件で出力とタイミングの
同等性を確認した上で、wall timeと`VideoPhase`中央値がともにstandard比90%以下になることです。
改善が小さい、出力差がある、または複雑性が見合わない場合はstandard pathを維持します。

## スレッドと計測

- `FFMPEG_PROFILE_MODE=1` で `-benchmark -stats` を付与
- `FFMPEG_THREADS` で `-threads` を明示上書き
- `FFMPEG_STALL_TIMEOUT_SEC` で FFmpeg の進捗・出力サイズが停滞した場合の中断秒数を調整
  - 既定値は `900`
  - `0` で停滞検知を無効化
- CPU フィルタ経路では `-filter_threads` / `-filter_complex_threads` を保守的にキャップ

## CPU / GPU 固定ベンチマーク

Python 3.14 と GPU が使えるコンテナで、同じ短い台本を CPU、GPU エンコード + CPU
フィルタ、GPU エンコード + CUDA フィルタの順に比較できます。

```bash
python scripts/benchmark_cpu_gpu.py
```

結果は `output/benchmarks/cpu-gpu-fixed-benchmark.json`、各実行ログは同じ
ディレクトリの `smoke-*.log` に保存されます。JSON には経過時間、出力サイズ、
ストリーム開始時刻・長さ、A/V 開始オフセット、DTS 警告数、GPU 使用率とレンダラー
CPU 使用率のサンプル、FFmpeg プロセス数を残します。比較対象の条件を変えないため、
このスクリプトは `--no-cache`、`--jobs 1`、`FFMPEG_PROFILE_MODE=1` を固定します。

## CPU standard / simple fast path固定ベンチマーク

Issue #42 のCPU実験は専用YAMLをstandard/fastで交互に3回ずつ描画し、中央値と出力を比較します。

```bash
python tools/cpu_scene_fast_path_benchmark.py \
  --script scripts/benchmark_cpu_scene_fast_path.yaml \
  --output-dir output/benchmarks/cpu-scene-fast-path \
  --runs 3
```

ベンチマークはCPU、`--quality speed`、`--jobs 1`、`--no-cache`、`--no-voice`を固定します。
結果JSONにはwall time、`VideoPhase`、FFmpeg/ffprobe回数、A/V警告、standard/fastの経路選択、
`ffprobe`セマンティクス、decoded video `framemd5`、decoded PCM SHA-256を記録します。
性能差が基準未満でも測定自体は成功とし、JSONの`decision=keep_standard`で不採用を明示します。

## cold / warm 固定ベンチマーク

同一YAML・同一runtime lock・同一エンコーダー条件で、cache refreshによるcold 1回と
cache再利用によるwarm 2回を比較します。

```bash
python tools/zundamotion_cold_warm_benchmark.py \
  scripts/smoke_minimal.yaml \
  --output-dir output/benchmarks/cold-warm \
  --hw-encoder cpu \
  --quality speed \
  --jobs 1 \
  --no-voice
```

cold実行は`--cache-refresh`を使用し、対象台本が参照したキーだけを再生成します。
既存cache全体の削除は行いません。結果の`cold-warm-benchmark.json`には、各実行の
phase時間、line clip p50/p95、字幕焼き込み時間、FFmpeg/ffprobe回数、cache
HIT/MISS/WRITE、A/V警告数、入力YAMLとruntime lockのSHA-256を保存します。
各実行の生PerfSummary、ログ、動画も同じディレクトリへ保存されます。

GitHub Actionsの`Performance Smoke`は`smoke_minimal.yaml`をCPU・音声なしで実行し、
cold/warm比較に加えてCPU simple scene fast path実験も実行します。比較JSONと生PerfSummaryは
artifactとして保存します。長尺台本の性能判定では、この短尺CIだけで結論を出さず、同一
runtime lockのローカルまたは専用runnerで再計測します。

## 自動チューニング

- `video.auto_tune: true` で先頭クリップを軽く計測
- CPU overlay が支配的なら `clip_workers` や `filter_threads` を保守的に調整
- `video.profile_first_clips: 4` で計測対象数を変更可能

## キャッシュ関連

- `system.cache_scene_base_video: true`
  - 字幕焼き込み前の `scene_<id>_base` を内部キャッシュ
- `system.generate_no_sub_video: false`
  - 必要なときだけ `*_no_sub.mp4` を生成
- `--no-cache` でも同一キーは in-flight 集約
- 正規化済み背景には `.meta.json` を隣接保存し、再正規化を抑止

## 一時ディレクトリ

- `USE_RAMDISK=1` で空き容量が十分なら `/dev/shm` を使用

## 設定例

```yaml
video:
  gpu_overlay_experimental: true
  auto_tune: true
  profile_first_clips: 4
  precache_subtitles: true
```

## 補足

性能改善の履歴や採用/却下判断は [`performance_regression_ledger.md`](./performance_regression_ledger.md) を参照してください。