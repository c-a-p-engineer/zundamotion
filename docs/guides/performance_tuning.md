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
  - 背景静止画、単一キャラ、通常発話だけのシーンは GPU エンコード時のみ適用

## スレッドと計測

- `FFMPEG_PROFILE_MODE=1` で `-benchmark -stats` を付与
- `FFMPEG_THREADS` で `-threads` を明示上書き
- CPU フィルタ経路では `-filter_threads` / `-filter_complex_threads` を保守的にキャップ

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
