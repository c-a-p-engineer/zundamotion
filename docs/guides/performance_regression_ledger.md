# 高速化の履歴と回帰防止メモ

このドキュメントは、Zundamotion を再度高速化するときに「以前に遅くなった変更」を繰り返さないための記録です。

結論から書くと、CPU 経路では「大きな 1 本の filter graph にまとめれば速い」とは限りません。実測しない最適化は簡単に悪化します。

## AI向けの読み方

このファイルは、次の順で読むと判断を間違えにくいです。

1. `最新の採用・却下一覧` で、現在の方針を先に確認する
2. `今回の短尺ベンチ結果` で、直近の実測値と条件を確認する
3. `遅くなった変更` / `速くなった変更` で、過去に失敗・成功した理由を見る
4. `ベンチマーク時の手順` で、次に測るときの条件を揃える
5. `参考ベースライン` は過去ログの詳細。厳密比較ではなく、傾向確認として扱う

検索しやすいキーワード:

- `FinalizePhase cache`
- `scene base cache`
- `subtitle layer video`
- `PNG 字幕チャンク分割`
- `GPU overlay`
- `scene-unit filter graph`
- `static slide fast path`
- `cache_refresh`
- `reencoded-next-suffix`

## 目的

- 何をやったら遅くなったかを残す
- 何をやったら速くなったかを残す
- 再計測時の前提条件を固定する
- どこまでが現実的な改善余地かを明確にする

## 先に結論

- CPU では、巨大な scene fast path は逆に遅くなった
- CPU では、`clip_workers=6` と過大な `filter_threads` は遅かった
- VOICEVOX の長い再試行は全体時間を大きく悪化させた
- 完成版字幕は `PNG overlay` より `ASS/libass` の方が速かったが、可読性は PNG の方が高い
- 通常動画の字幕焼き込みは PNG を標準にする。ASS/libass は `subtitle.render_mode: auto` / `ass` で明示したときだけ使う
- `auto` のASS対象は背景色・透過率だけの軽い字幕に限る。角丸・枠線・余白・背景画像・字幕エフェクトはPNGに戻す
- CPU固定時はOpenCL smoke testを走らせない。GPUを使わない経路で `scale_opencl` 警告を出さない
- `--no-cache` でも同一生成回の一時ファイル・duration/media-info は再利用する。永続キャッシュは読まず書かず、同一実行内の重複生成と重複probeだけを避ける
- NVENC では `veryfast` など x264 系 preset を渡してはいけない。`p1`〜`p7` へ正規化する
- `quality=speed` で NVENC `p7` を選ぶのは逆効果。`p1` が fastest、`p7` が slowest/best
- `cache_refresh` が同一キーを何度も消す実装は無駄だった
- PNG 字幕焼き込みは巨大な 1 本の filter graph に戻さない。字幕範囲をチャンク分割し、字幕のない gap は stream copy する
- `subtitle.png_chunk_size` は `auto` を既定にする。ただし既知の中尺ケースでチャンク数が増えないよう、90字幕級だけを大きめにし、66字幕級は従来の `12` 相当に留める
- FinalizePhase の `consume_next_head` 付き transition は、消費後の next scene 後続部を再エンコードする。`-ss` + stream copy では切り出し位置より前の音声が混ざり、次シーン冒頭音声が二重化する場合がある
- 2026-05-10 の短尺ベンチでは、`FinalizePhase cache` は採用。transition boundary と final concat intermediate を内容ハッシュでキャッシュする
- `FinalizePhase cache` の key に一時パスや mtime を入れると、同一内容でも cache hit しない。入力動画は `size + sha256` で識別する
- 画像アセットは画像の差し替えが発生するため、同名ファイルでも中身が変わったら別 cache として扱う。cache key 内の既存ローカル画像パスには `sha256` を含める
- `subtitle-only transparent video` は再度却下。qtrle/alpha 中間動画の生成・I/Oが重く、短尺ベンチでも安定完走しなかった
- `scene-unit filter graph` と `static slide fast path` は、現状の line clip + scene cache 構造を壊すリスクに対して効果未確認。既定採用しない
- `GPU overlay` は、この環境では CUDA filter smoke が失敗したため不採用。CPU/GPU 往復が発生する構成では採用しない
- いまの CPU 経路の残ボトルネックは主に `VOICEVOX`、行クリップ生成、長尺時の字幕チャンク焼き込み

## 最新の採用・却下一覧

2026-05-10 時点の判断です。新しく高速化を試す場合は、この表を先に更新してください。

| 対象 | 判定 | 理由 |
|---|---|---|
| scene base / subtitle cache | 採用 | 字幕済み scene cache hit で `VideoPhase` がほぼ 0 秒になる |
| FinalizePhase cache | 採用 | transition boundary と final concat の再生成を避けられる |
| PNG 字幕チャンク分割 | 採用 | 巨大 filter graph による長時間停止を避けられる |
| PNG 字幕チャンクサイズ auto | 採用 | 長尺・字幕多数時だけチャンク数を減らし、既知の中尺ケースでは `12` 相当を維持する |
| 顔 overlay 事前キャッシュ | 採用 | 同一実行内の顔 overlay 再生成を抑制できる |
| 画像内容署名付き cache key | 採用 | 画像の差し替えが発生するため、`13-redesign.png` のような同名画像差し替えで古い scene cache を再利用しない |
| subtitle-only transparent video | 却下 | qtrle/alpha 中間動画が重く、I/O も増える |
| static slide fast path | 却下 | 対象条件が狭く、既存 line clip + cache と競合する |
| scene-unit filter graph | 却下 | 巨大 filter graph 化で debug 性と保守性が落ちる |
| GPU overlay / CUDA overlay | 却下 | smoke test 失敗。CPU/GPU 往復のリスクが高い |
| transition suffix stream copy | 却下 | next scene 冒頭音声が再出現する場合がある |

## 今回の短尺ベンチ結果

2026-05-10 に、最終 mp4 出力速度を対象として短尺ベンチを行いました。

### 入力条件

- 台本: `vendor/zundamotion/scripts/benchmark_short_render.yaml`
- 発話数: 24
- 字幕: PNG 字幕あり
- 背景画像: あり
- キャラクター立ち絵: あり
- foreground PNG overlay: あり
- scene transition: あり
- 音声: `--no-voice` による silent audio
- 実行環境:
  - CPU: Intel(R) Core(TM) i7-10710U CPU @ 1.10GHz, 12 logical CPUs
  - GPU: NVIDIA GeForce GTX 1650 with Max-Q Design, driver 581.08
  - ffmpeg: `7.0.1-full_build-www.gyan.dev`
  - OS: WSL2 Linux `6.6.114.1-microsoft-standard-WSL2`
- 主な実行オプション:
  - `--hw-encoder cpu`
  - `--quality speed`
  - `--jobs 0`
  - `--no-voice`
  - `--debug-log`
  - `--log-kv`
  - `FFMPEG_LOG_CMD=1`
  - `HW_FILTER_MODE=cpu`

### ベースライン

Cache OFF (`--no-cache`)。

| metric | value |
|---|---:|
| total | 158.11s |
| AudioPhase | 22.23s |
| VideoPhase | 110.86s |
| FinalizePhase | 18.76s |

ログ:

- `logs/20260510_165357_113.log`

### FinalizePhase cache 採用結果

初回生成では cache miss。transition boundary と final concat intermediate を生成します。

| metric | cache refresh / miss |
|---|---:|
| total | 141.40s |
| VideoPhase | 94.31s |
| FinalizePhase | 21.68s |

同一入力で cache hit した場合:

| metric | cache hit |
|---|---:|
| total | 16.14s |
| AudioPhase | 9.19s |
| VideoPhase | 0.01s |
| FinalizePhase | 0.53s |

改善率:

| metric | baseline | cache hit | improvement |
|---|---:|---:|---:|
| total | 158.11s | 16.14s | 89.8% |
| VideoPhase | 110.86s | 0.01s | 99.99% |
| FinalizePhase | 18.76s | 0.53s | 97.2% |

重要な実装メモ:

- 最初は cache key に一時ファイルパスや mtime を含めていたため、warm run と hit run で key が変わった
- 修正後は入力動画を `size + sha256` で識別する
- 同一内容であれば temp path と cache path が変わっても `finalize_transition_*` と `finalize_concat_*` が HIT する

採用理由:

- transition boundary clip の再生成を避けられる
- final concat intermediate の再生成を避けられる
- `FinalizePhase` が `21.68s -> 0.53s` まで短縮した

### subtitle-only transparent video 再検証

目的:

- 大量の subtitle PNG overlay chain を、透明字幕動画 + 本編への 1 overlay に置き換える

結果:

| metric | before | after |
|---|---:|---:|
| total | 125.28s | incomplete |
| AudioPhase | 16.33s | 4.60s |
| VideoPhase | 85.84s | incomplete |
| FinalizePhase | 12.86s | not reached |

ログ:

- before: `logs/20260510_165905_789.log`
- after: `logs/20260510_170114_885.log`

判定:

- 却下

理由:

- `Layer-video mode` は開始したが、短尺ベンチでも安定完走しなかった
- 透明中間動画に `qtrle` / alpha を使うため、I/O と中間エンコードが増える
- 2026-05-07 の長尺検証でも qtrle 字幕レイヤー生成が `1200.22s` かかっており、同じ失敗傾向
- 通常運用の既定値にはしない

### scene base cache 強化

判定:

- 採用済み機能として維持

実測上の効果:

- cache hit run では `scene_bench_a_sub` / `scene_bench_b_sub` が HIT
- `VideoPhase` は `0.01s`

補足:

- 字幕変更のみの再生成では、scene base を再利用して字幕 burn-in だけやり直す既存テストがある
- 今回は新規大改修ではなく、既存キャッシュ方針の有効性確認として扱う

### static slide fast path

判定:

- 却下

理由:

- 今回の短尺台本は静的背景だが、foreground overlay、立ち絵、字幕 burn-in があり、既存の line clip path が使われた
- 対象条件を厳密に絞ると適用範囲が狭い
- 広く適用しようとすると `scene-unit filter graph` と同じ高リスク改修になる

### scene-unit filter graph

判定:

- 却下

理由:

- `1 scene = 1 filter_complex` は clip 数を減らせる可能性があるが、filter graph が巨大化する
- 既存の line clip + scene cache は debug しやすく、キャッシュも効いている
- OSS 保守性と障害調査性を落としてまで採用する根拠がない

### GPU overlay

判定:

- 却下

観測:

- CUDA filter smoke は一部失敗
  - RGBA path: `Unsupported input format: yuva420p`
  - NV12 download path: `Invalid output format rgba for hwframe download`
- CPU-mode ベンチ中の GPU utilization はほぼ 0%

理由:

- overlay を完全に GPU 側へ寄せられない
- CPU/GPU 往復が発生する可能性が高い
- この環境では本番レンダリング高速化として採用できるだけの実測効果がない

## 遅くなった変更

### 1. CPU で simple scene fast path を有効化した

内容:
- 「1 シーン 1 FFmpeg」に寄せる fast path を CPU でも使った

結果:
- `diiva_company_intro` では逆に遅くなった
- CPU は巨大な `filter_complex` 1 本より、行クリップを 2 並列で回した方が安定して速かった

原因:
- 字幕、立ち絵、顔差分、背景処理を 1 本へ詰め込むと、CPU フィルタ処理が重くなりすぎた

今後のルール:
- `scene fast path` は GPU 利用時だけ試す
- CPU ではデフォルトで無効のままにする
- CPU で再挑戦する場合は、必ず同じ台本でベンチマークしてから有効化する

### 2. CPU で `clip_workers` と FFmpeg フィルタスレッドを上げすぎた

内容:
- CPU 経路でも `clip_workers=6`
- `filter_threads=12`, `filter_complex_threads=12`

結果:
- 並列しすぎて逆に遅くなった
- ログでは CPU オーバーレイ系のクリップが悪化した

原因:
- 立ち絵・顔差分・字幕のあるクリップは CPU フィルタ負荷が高く、プロセス並列とフィルタ並列の両方を増やすと oversubscription になる

今後のルール:
- CPU オーバーレイ中心では `clip_workers=2` を基準にする
- CPU では `filter_threads` / `filter_complex_threads` は控えめにする
- `hw_kind is None` を CPU-bound として扱う

### 3. VOICEVOX のリトライを重くしすぎた

内容:
- 多段の指数バックオフで長時間待つ構成

結果:
- 接続不安定時に `AudioPhase` が極端に長くなった
- 実際に `143.95s` まで膨らんだログがあった

原因:
- 失敗した合成を長時間待ち続けた

今後のルール:
- リトライ回数は少なめに抑える
- 待機時間は短く切る
- 不安定時は早めに silent fallback へ切り替える

### 4. `no_sub` を既定で作った

内容:
- 完成版に加えて `*_no_sub.mp4` も毎回作る

結果:
- Finalize/BGM の追加処理が増えた
- 利用しない場合は純粋な無駄だった

今後のルール:
- `system.generate_no_sub_video` は既定で `false`
- 本当に必要なときだけ opt-in

### 5. `cache_refresh` で同じキーを何度も消した

内容:
- `face_overlay.png` など同じキャッシュキーを同一実行中に何度も削除・再生成した
- `get_cached_path()` 側では scene キャッシュが生き残る抜け道もあった

結果:
- コールド計測のつもりでも無駄な再生成が増えた
- 逆に scene キャッシュだけ残って測定が歪むケースもあった

今後のルール:
- `cache_refresh` は「1 実行につき同一キー 1 回だけ無効化」
- `get_or_create()` と `get_cached_path()` の両方で `cache_refresh` を尊重する
- 同一キーの並列生成は 1 本に集約する

### 6. NVENC へ x264 preset をそのまま渡した

内容:
- `h264_nvenc` に `veryfast` を渡していた
- FFmpeg/NVENC の preset 有効値は環境により異なるが、今回のコンテナでは `p1`〜`p7` と `fast`/`medium`/`slow` などだった

結果:
- `Unable to parse "preset" option value "veryfast"` で正規化処理が失敗
- opening/ending の normalize で NVENC 失敗ログが出て CPU fallback していた

原因:
- x264 と NVENC の preset 名を同じ文字列として扱っていた
- `quality=speed` で `p7` を選んでいたが、今回の NVENC では `p7` は slowest/best

今後のルール:
- エンコーダごとに preset を正規化する
- NVENC の speed は `p1`/`p2`、balanced は `p4`/`p5`、quality は `p6`/`p7` を基準にする
- Docker 側で FFmpeg を固定するより、コード側でエンコーダ別 preset 変換を持つ

### 7. `auto` NVENC の Hybrid path が長尺クリップで停止した

内容:
- `--hw-encoder auto` で NVENC を使い、背景 scale は GPU、overlay は CPU の Hybrid path になった

結果:
- `agile/002_agile-manifesto` の `main_52` で ffmpeg 出力が `size:1.0MB` のまま 3 分以上進まなかった
- `Ctrl-C` 相当で中断した

原因候補:
- GPU scale と CPU overlay の間でフレーム転送が発生し、特定クリップで詰まる
- `overlay_cuda` に寄せ切れていないため、NVENC の利点が出る前にフィルタ経路が重くなる

今後のルール:
- Hybrid path が発生する構成では、`auto` で安易に GPU を選ばない
- `overlay_cuda` まで完全に乗る場合だけ GPU を優先する
- 長尺台本では `auto` のスモークテストだけでなく、短い実クリップの進捗監視で CPU fallback する

## 速くなった変更

### 1. 完成版字幕を `ASS/libass` 優先にした

内容:
- 最終字幕焼き込みを PNG 連続 overlay から `ASS/libass` 優先へ変更

効果:
- 最終字幕合成のコストを削減
- 完成版字幕の経路がシンプルになった

後続判断:
- 高速化としては有効だった
- ただし字幕の見やすさが既存 PNG 字幕より落ちる
- 通常動画の既定には採用しない。PNG 字幕を標準に戻し、速度検証や軽量字幕では `subtitle.render_mode: auto` / `ass` で明示利用する

### 2. 完成版の前景/字幕合成を単発ジョブ向けスレッド数にした

内容:
- 行クリップ用の `clip_workers` に引っ張られず、最終焼き込みは単発 FFmpeg としてスレッド数を決定

効果:
- 最終字幕焼き込みのスレッド不足を回避
- CPU での最終段が少し短くなった

ルール:
- `apply_foreground_overlays()`
- `apply_overlays()`
- `apply_subtitle_overlays()`

これらの最終合成は単発ジョブとして扱う

### 3. 字幕 PNG のプロセスプールを共有した

内容:
- scene ごとに `SubtitlePNGRenderer` を作り直さないようにした

効果:
- 字幕 PNG ワーカーの起動コストを削減

### 4. 音声生成を先行並列化したが、並列度は 2 を基準にした

内容:
- AudioPhase の逐次実行をやめ、順序維持のまま先行並列化
- ただし `auto` の既定上限は 2

効果:
- 安定しているときの `AudioPhase` を短縮
- 3 以上に上げて不安定化するケースを避けた

### 5. CPU 経路のスレッド判定を修正した

内容:
- `hw_kind is None` を CPU-bound として扱うよう修正

効果:
- CPU クリップが `threads=6 / filter_threads=4 / filter_complex_threads=4` へ落ち着いた
- 過剰なフィルタスレッドを避けられた

### 6. `cache_refresh` の実効性を直した

内容:
- scene キャッシュも含めて正しく再生成
- 同一キーの並列生成を抑止

効果:
- コールド計測の再現性が上がった
- `face_overlay` の無駄な再生成が減った

### 7. NVENC preset をエンコーダ別に正規化した

内容:
- `VideoParams.to_ffmpeg_opts("nvenc")` で x264 系 preset を NVENC preset へ変換
- `quality=speed` の NVENC preset を `p7` から `p1` へ修正
- `hw_encoder=cpu` のときは `get_encoder_options()` で NVENC probe をしないようにした

効果:
- `h264_nvenc -preset veryfast` の即時失敗を解消
- CPU 指定時の無駄な NVENC 検出を避けた

注意:
- preset エラーは解消したが、`agile/002_agile-manifesto` では Hybrid path が停止したため、NVENC auto はまだ安全な高速化とは言えない

### 8. PNG 字幕焼き込みをチャンク分割した

内容:
- 完成版 PNG 字幕焼き込みを、1 本の巨大な `filter_complex` ではなく複数チャンクへ分割する
- 字幕同士が重なる範囲は同じチャンクに残し、見た目を崩さない
- 字幕のない gap は再エンコードせず stream copy し、最後に concat する
- 2026-05-11 以降、既定の `subtitle.png_chunk_size` は `auto`
  - `ZUNDAMOTION_SUB_PNG_CHUNK_SIZE` で実行環境ごとの固定値に上書きできる
  - 90字幕級・長尺では `15-16` 程度を選び、66字幕級では従来相当の `12` を維持する

効果:
- 長尺台本で巨大 filter graph が詰まる状態を避けられる
- PNG 字幕の可読性を維持したまま、ASS/libass へ逃がさずに完走しやすくなった
- 長尺・字幕多数時の ffmpeg 起動/concat 小片数を減らす。ただし巨大 filter graph へ戻さないため上限は `36` に制限する

実測:
- `logs/20260508_005644_685.log` の `004_ai-code-readable`
  - `Total execution time: 220.32s`
  - `AudioPhase: 20.57s`
  - `VideoPhase: 191.90s`
  - `FinalizePhase: 5.16s`
  - `base=399.47s`, `subtitles=90`, `png_chunk_size=12`, `8 subtitle chunk(s)`
- 同じ `004_ai-code-readable` の旧経路実行 `logs/20260507_233939_428.log` は、字幕焼き込み ffmpeg が 1 時間以上進行した後に中断された
- `logs/20260507_225123_235.log` の `005_pc_why-restart-fixes`
  - `Total execution time: 490.72s`
  - `AudioPhase: 42.19s`
  - `VideoPhase: 440.80s`
  - `FinalizePhase: 5.26s`
  - `base=342.54s`, `subtitles=66`, `png_chunk_size=12`, `6 subtitle chunk(s)`
- 旧経路 `logs/20260507_171633_602.log` の `005_pc_why-restart-fixes` は `Total execution time: 1548.87s`, `VideoPhase: 1377.01s`, `FinalizePhase: 110.72s`

2026-05-11 の auto 選択値確認:

| source | previous | auto | expected chunk count |
|---|---:|---:|---:|
| `logs/20260510_123809_482.log` / 009, `subtitles=94`, `base=521.15s` | `png_chunk_size=12`, `8 chunk(s)` | `16` | 約 `6 chunk(s)` |
| `logs/20260510_131146_816.log` / 010, `subtitles=90`, `base=534.25s` | `png_chunk_size=12`, `8 chunk(s)` | `15` | 約 `6 chunk(s)` |
| `logs/20260507_225123_235.log` / 005, `subtitles=66`, `base=342.54s` | `png_chunk_size=12`, `6 chunk(s)` | `12` | `6 chunk(s)` 維持 |

検証:
- `python3 -m py_compile vendor/zundamotion/zundamotion/components/video/overlays.py vendor/zundamotion/zundamotion/components/video/renderer.py vendor/zundamotion/zundamotion/components/pipeline_phases/video_phase/main.py vendor/zundamotion/zundamotion/pipeline.py vendor/zundamotion/tools/zundamotion_perf_benchmark.py vendor/zundamotion/tests/test_overlay_alpha_preservation.py`
- Docker app container:
  - `python -m py_compile vendor/zundamotion/zundamotion/components/video/overlays.py vendor/zundamotion/zundamotion/components/video/renderer.py vendor/zundamotion/zundamotion/components/pipeline_phases/video_phase/main.py vendor/zundamotion/zundamotion/pipeline.py vendor/zundamotion/tools/zundamotion_perf_benchmark.py`
  - `python -m pytest -q tests/test_overlay_alpha_preservation.py tests/test_scene_renderer_subtitle_flow.py`: `9 passed in 5.47s`
- `python3` による auto 選択値 smoke:
  - `90/534.25s -> 15`
  - `94/521.15s -> 16`
  - `66/342.54s -> 12`

未実施:
- このホストには `ffmpeg` / `ffprobe` がなかったため、実動画の壁時計ベンチは未実施。次回は Docker/Dev Container 側で、同じ台本を `png_chunk_size: 12` と `auto` の2条件で比較する

注意:
- 2026-05-08 の計測は永続キャッシュ有効の再生成であり、完全な cold-cache 比較ではない
- ただし旧 `004` の巨大字幕焼き込みが実用上止まったこと、変更後 `004` が `220.32s` で完走したことから、チャンク分割は採用する
- チャンクを小さくしすぎると concat/copy の小片が増える。大きくしすぎると巨大 filter graph 問題に戻るため、auto は既知ログで悪化しない範囲に留める

### 9. Transition の next scene 後続部は再エンコードする

内容:
- `consume_next_head` 付き local transition では、境界の短い transition 部分だけを処理する
- トランジション境界で使用した next scene 先頭は、後続本編から消費する
- 消費後の next scene 後続部は、stream copy ではなく再エンコードで切り出す

効果:
- `-ss` + stream copy のキーフレーム都合で、消費済みの先頭音声が suffix 側に残る問題を避けられる
- OP→本編のように次シーン冒頭が短い発話でも、「わかる、わかる」のような二重発話を防げる

実測:
- `logs/20260507_171633_602.log` の `005_pc_why-restart-fixes` 旧経路: `FinalizePhase: 110.72s`
- `logs/20260507_225123_235.log` の `005_pc_why-restart-fixes` 変更後: `FinalizePhase: 5.26s`
- `logs/20260508_005644_685.log` の `004_ai-code-readable` 変更後: `FinalizePhase: 5.16s`
- 2026-05-08 の `scripts/copipetan-dev-room/check_transition.yaml` で、OP トランジション有効時に次シーン冒頭の「わかる」が二重に聞こえないことを確認
- 変更後ログでは transition 適用時に `reencoded-next-suffix` が出る

今後のルール:
- `consume_next_head` 付き transition の next scene suffix は、現在の再エンコード方針を維持する
- 速度最適化目的で suffix を stream copy に戻さない。戻す場合は、キーフレーム非境界で次シーン冒頭音声が再出現しないことを音声つきの最小再現動画で確認する

## ベンチマーク時の手順

### 短尺ベンチツール

短尺ベンチは vendor 側のツールを使う。

```bash
python vendor/zundamotion/tools/zundamotion_perf_benchmark.py --case baseline
```

全ケースをまとめて測る場合:

```bash
python vendor/zundamotion/tools/zundamotion_perf_benchmark.py --case all
```

Task 1 / Task 4 だけを測る場合:

```bash
python vendor/zundamotion/tools/zundamotion_perf_benchmark.py --case task1
python vendor/zundamotion/tools/zundamotion_perf_benchmark.py --case task4
```

入力台本を変える場合:

```bash
python vendor/zundamotion/tools/zundamotion_perf_benchmark.py \
  --script vendor/zundamotion/scripts/benchmark_short_render.yaml \
  --output-dir output/perf \
  --case all
```

出力:

- `output/perf/benchmark_results.json`
- `output/perf/*.mp4`
- `output/perf/variants/*.yaml`

ツールが固定する主な条件:

- `--hw-encoder cpu`
- `--quality speed`
- `--jobs 0`
- `--no-voice`
- `--debug-log`
- `--log-kv`
- `FFMPEG_LOG_CMD=1`
- `HW_FILTER_MODE=cpu`
- `ZUNDAMOTION_AUDIO_WORKERS=2`
- `ZUNDAMOTION_SCENE_WORKERS=1`
- `SUB_PNG_WORKERS=2`

結果 JSON では次を見る:

- `timings.total`
- `timings.AudioPhase`
- `timings.VideoPhase`
- `timings.FinalizePhase`
- `gpu_before`
- `gpu_after`
- `log_tail`

注意:

- `--case baseline` は `--no-cache` で cache off を測る
- `--case task4` は `task4_after_warmup` で cache refresh、`task4_after_cache_hit` で cache hit を測る
- WSL 側に `ffmpeg` / `ffprobe` がない場合、Windows 側の実行ファイルを `.bench/bin` に wrapper として自動登録する
- vendor repo 単体で実行する場合は、必要に応じて `--script` で台本パスを明示する

### コールド計測

どちらかを使う:

```bash
rm -rf cache/*
```

または

```bash
python -m zundamotion.main ... --cache-refresh
```

注意:
- `--cache-refresh` は現在、scene キャッシュも含めて再生成される
- 比較条件を揃えるなら `cache/` 削除の方が分かりやすい

### 推奨比較コマンド

音声なし:

```bash
HW_FILTER_MODE=cpu \
python -m zundamotion.main scripts/diiva_company_intro.yaml \
  -o output/diiva_company_intro.mp4 \
  --quality speed \
  --jobs auto \
  --hw-encoder auto \
  --no-voice \
  --log-kv
```

音声あり:

```bash
HW_FILTER_MODE=cpu \
python -m zundamotion.main scripts/diiva_company_intro.yaml \
  -o output/diiva_company_intro.mp4 \
  --quality speed \
  --jobs auto \
  --hw-encoder auto \
  --log-kv
```

GPU が利用できる環境の標準比較は `HW_FILTER_MODE=cpu --hw-encoder auto` とし、CPU 合成 + NVENC エンコードを測る。GPU がない環境や切り分けでは `--hw-encoder cpu` に戻して比較する。

### 比較時に見るべき値

- `AudioPhase.run`
- `VideoPhase.run`
- `FinalizePhase.run`
- 各クリップの `Finished clip ... in Xs`
- 最終字幕焼き込みの所要時間
- `VOICEVOX synthesis failed ...`
- `clip_workers` / `threads` / `filter_threads`

## 参考ベースライン

2026-03-27 時点:

- 遅かった実行例: `456.14s`
  - `AudioPhase: 143.95s`
  - `VideoPhase: 306.65s`
- 以前のコールド実行: `296.01s`
- 改善後のコールド `--no-voice`: `98.02s`
  - `AudioPhase: 1.34s`
  - `VideoPhase: 94.49s`
- 改善後のコールド音声あり: `233.74s`
  - `AudioPhase: 98.14s`
  - `VideoPhase: 133.05s`

2026-05-01 `agile/002_agile-manifesto`:

- 前回 CPU 固定生成: `1045s`
  - 動画尺: `298.968s`
  - `AudioPhase: 58.39s`
  - `VideoPhase: 682.83s`
  - `FinalizePhase: 291.69s`
  - 本編 63 クリップ concat: `3.57s`
  - 出力: `35MB`
- CPU 固定・キャッシュ有効再生成: `416s`
  - 動画尺: `298.968s`
  - `AudioPhase: 20.80s`
  - `VideoPhase: 88.02s`
  - `FinalizePhase: 300.64s`
  - 本編 63 クリップ concat: `1.92s`
  - 出力: `35MB`
  - 前回比: `629s` 短縮、約 `2.5x`、約 `60%` 短縮
- `--hw-encoder auto` / NVENC:
  - NVENC preset エラーは解消
  - `main_52` で `size:1.0MB` のまま 3 分以上進まず中断
  - 実運用では当面 CPU 固定が安定
- 字幕レンダリング方針:
  - ASS/libass は高速だが、既存 PNG 字幕より可読性が落ちる
  - SRT は投稿用・確認用に出力し続ける
  - 動画へ焼き込む字幕は PNG レンダリングを標準に戻す
  - ASS は削除せず、`subtitle.render_mode: auto` / `ass` で明示した場合に使う
  - 以後の通常動画の性能比較では PNG 字幕を基準にし、ASS は別モードとして比較する
- CPU 固定・PNG 字幕再生成: `1184.50s`
  - 壁時計: `1187s`
  - 動画尺: `298.968s`
  - `VideoPhase: 886.25s`
  - `FinalizePhase: 276.88s`
  - 本編 63 クリップ concat: `2.34s`
  - 出力: `34MB`
  - 前回 ASS 版 `416s` 比: `+768s`、約 `2.85x`
  - PNG 字幕焼き込みが支配的。見た目優先の方針では、次の改善対象は PNG 字幕合成のキャッシュ粒度と FinalizePhase の部分再エンコード

この計測で分かったこと:
- 結合そのものは遅くない。本編 63 クリップ concat は数秒
- ASS 版ではキャッシュが効くと `VideoPhase` は大きく短縮される
- PNG 版では字幕焼き込みが `VideoPhase` の主ボトルネックになる
- 残ボトルネックは PNG 字幕焼き込みと `FinalizePhase` の dissolve transition 再エンコード
- 進捗ログの `ETA` / `pct` は長い ffmpeg では出るが、推定値はかなり揺れる

2026-05-02 `sample_subtitle_render_modes` 改善確認:

- CPU固定時のOpenCL smoke testをスキップ
  - `scale_opencl` / OpenCL smoke warning: `0`
- duration/media-infoキャッシュキーを一時ディレクトリ非依存に変更
  - 再実行時 `Cache HIT for duration`: `9`
  - 再実行時 `Cache MISS for duration`: `0`
- 静止背景のみの scene base を共有キャッシュ化
  - 同じ背景・尺・解像度・音声条件なら `scene_base_shared` を再利用する
- キャッシュ有効再生成:
  - `AudioPhase: 1.68s`
  - `VideoPhase: 0.01s`
  - `FinalizePhase: 0.50s`
  - `GenerationPipeline.run: 3.86s`

2026-05-07 `copipetan-dev-room/003_php_what-is-php` 字幕レイヤー動画方式検証:

- 比較対象:
  - 従来方式: `logs/20260506_131348_889.log`
  - 字幕レイヤー方式: `logs/20260507_025745_059.log`
  - 条件はいずれも `--no-cache`、CPU filter mode、PNG字幕主体
- 結果:
  - 従来方式 `GenerationPipeline.run: 1783.44s`
    - `AudioPhase: 53.56s`
    - `VideoPhase: 1726.97s`
  - 字幕レイヤー方式 `GenerationPipeline.run: 1808.28s`
    - `AudioPhase: 56.94s`
    - `VideoPhase: 1691.50s`
    - `FinalizePhase: 49.04s`
  - 総時間は `+24.84s` 悪化
  - VideoPhase 単体は `-35.47s` 短縮
- 字幕レイヤー方式の内訳:
  - `scene_output_main.mp4` 生成完了: `03:05:33.020`
  - qtrle 字幕レイヤー生成開始: `03:05:33.171`
  - qtrle 字幕レイヤー生成完了: `03:25:33.388`
  - qtrle 字幕レイヤー生成時間: `1200.22s`
  - 字幕レイヤー1回 overlay 完了: `03:26:58.432`
  - 本編への1回 overlay は約 `85s`
- 分かったこと:
  - 本編側 filter graph は軽くなるが、字幕PNGの時間軸配置コストは消えず、qtrle レイヤー生成側へ移る
  - 1920x1080 / 30fps / 約396.52s / 71字幕の qtrle `.mov` 生成が重すぎる
  - qtrle レイヤーはログ上約 `201.5MB` まで増え、可逆ARGB中間としてI/Oとエンコード負荷が大きい
  - `--no-cache` では字幕レイヤーの永続キャッシュ利点が出ない
- 判定:
  - 初回・no-cache の高速化策としては不採用
  - 再検証する場合もフラグ付き実験機能に留め、通常運用の既定値は `subtitle.layer_video.enabled: false` 相当にする
  - 次の候補は顔 overlay の事前バッチ/キャッシュ改善、SubtitlePNGRenderer worker 数、字幕PNG事前バッチ生成

2026-05-07 `copipetan-dev-room/003_php_what-is-php` 顔 overlay 事前キャッシュ採用:

- 比較対象:
  - 基準: `logs/20260506_131348_889.log`
  - 字幕レイヤー方式: `logs/20260507_025745_059.log`
  - 顔 overlay 事前キャッシュ後: `logs/20260507_040313_995.log`
  - 条件はいずれも `--no-cache`、CPU filter mode、PNG字幕主体
- 結果:
  - 基準 `GenerationPipeline.run: 1783.44s`
    - `AudioPhase: 53.56s`
    - `VideoPhase: 1726.97s`
  - 字幕レイヤー方式 `GenerationPipeline.run: 1808.28s`
    - `VideoPhase: 1691.50s`
  - 顔 overlay 事前キャッシュ後 `GenerationPipeline.run: 1258.94s`
    - `AudioPhase: 42.00s`
    - `VideoPhase: 1165.47s`
    - `FinalizePhase: 48.67s`
  - 基準比:
    - 総時間 `-524.50s`、約 `29.4%` 短縮
    - `VideoPhase` `-561.50s`、約 `32.5%` 短縮
  - 字幕レイヤー方式比:
    - 総時間 `-549.34s`
    - `VideoPhase` `-526.03s`
- 顔 overlay 事前キャッシュの観測:
  - `Precached 6 face overlay PNG(s) for scene 'main'`
  - 以降の clip では `temp_face_overlay_*` が大量に `Cache disabled: Reusing existing ephemeral output` になっている
  - `--no-cache` でも同一プロセス内の ephemeral reuse により、clip ごとの顔 overlay PNG 再生成を抑制できている
  - ただし初回 clip 開始直後に `temp_face_overlay_5a8dba7f...` と `temp_face_overlay_f6090436...` の追加生成が残った
    - 事前候補に `mouth/close.png` と `eyes/open.png` 系が入っていない可能性が高い
- 注意:
  - 今回ログでは `AutoTune` が `clip_workers 1 -> 3` に上げている
  - そのため 500 秒級の短縮を顔 overlay 事前キャッシュ単独の効果として扱わない
  - ただし事前キャッシュ自体は動作し、clip 内の顔 overlay 生成ブレを減らす効果がログで確認できた
- 判定:
  - 採用
  - `video.precache_face_overlays: true` を既定値として維持する
  - 次の改善は事前キャッシュ候補に `mouth/close.png` と `eyes/open.png` を含め、clip 開始後の顔 overlay 追加生成を 0 に近づける

2026-05-02 `intro/001_channel-intro` `--no-cache --hw-encoder auto` 調査:

- 指定コマンドは無限停止ではなく `647.42s` で完走
  - `AudioPhase: 24.97s`
  - `VideoPhase: 524.23s`
  - `FinalizePhase: 94.66s`
  - 出力: `output/copipetan-dev-room/intro/001_channel-intro.mp4`
- 主因:
  - AutoTune が `HW filter mode=cpu` を読み込んだ状態でも、`--hw-encoder auto` が NVENC を選び続けていた
  - 実行ログでは `CPU path: ... keeping NVENC encoding` が各クリップで発生
  - PNG 字幕焼き込みの本編全体再エンコードが約 `4.5min`
  - dissolve transition の再エンコード 2 回が約 `95s`
- 対応:
  - AutoTune が CPU フィルタ固定を指示している場合、`--hw-encoder auto` ではエンコーダも CPU に寄せる
  - 明示 `--hw-encoder gpu` は従来通り NVENC を維持する
  - 混在経路の長時間化と「終わらないように見える」状態を避ける
- 検証:
  - `vendor/zundamotion/tests/test_hw_encoder_selection.py`: `7 passed`
- 対応後の同一コマンド再生成:
  - `Total execution time: 595.94s`
  - `VideoPhase: 492.66s`
  - `FinalizePhase: 72.86s`
  - 修正前 `647.42s` 比で `51.48s` 短縮、約 `8.0%` 短縮
  - クリップ生成ログは `CPU path: using CPU filters for scaling/overlay` になり、`keeping NVENC encoding` は消えた

2026-05-08 `copipetan-dev-room/004_ai-code-readable` / `005_pc_why-restart-fixes` PNG 字幕チャンク分割 + transition suffix copy 検証:

注意:
- この時点では transition suffix copy を採用候補にしていたが、後続の `check_transition.yaml` 検証で次シーン冒頭音声の二重化が確認されたため、transition suffix copy の採用判断は撤回する
- 現在の推奨は、`consume_next_head` 後の next scene suffix を再エンコードする方式

- 計測コマンド条件:
  - `HW_FILTER_MODE=cpu`
  - `ZUNDAMOTION_AUDIO_WORKERS=2`
  - `ZUNDAMOTION_SCENE_WORKERS=2`
  - `SUB_PNG_WORKERS=2`
  - `--hw-encoder cpu --quality speed --jobs 0 --log-kv`
  - 永続キャッシュ有効。`--no-cache` ではないため、cold-cache の厳密比較ではない
- `004_ai-code-readable` 変更後: `logs/20260508_005644_685.log`
  - `Total execution time: 220.32s`
  - `GenerationPipeline.run: 219.57s`
  - `AudioPhase: 20.57s`
  - `VideoPhase: 191.90s`
  - `FinalizePhase: 5.16s`
  - 字幕焼き込み: `8 subtitle chunk(s)`, `base=399.47s`, `subtitles=90`, `png_chunk_size=12`
  - transition: `copied-next-suffix`。現在は非推奨
- `004_ai-code-readable` 旧経路試行: `logs/20260507_233939_428.log`
  - `AudioPhase: 35.73s`
  - 字幕焼き込み ffmpeg が長時間継続し、1 時間以上経過後に中断
  - 旧経路の巨大 PNG filter graph は、長尺台本では実用上完走しないケースがある
- `005_pc_why-restart-fixes` 旧経路: `logs/20260507_171633_602.log`
  - `Total execution time: 1548.87s`
  - `AudioPhase: 57.74s`
  - `VideoPhase: 1377.01s`
  - `FinalizePhase: 110.72s`
- `005_pc_why-restart-fixes` 変更後: `logs/20260507_225123_235.log`
  - `Total execution time: 490.72s`
  - `AudioPhase: 42.19s`
  - `VideoPhase: 440.80s`
  - `FinalizePhase: 5.26s`
  - 字幕焼き込み: `6 subtitle chunk(s)`, `base=342.54s`, `subtitles=66`, `png_chunk_size=12`
  - transition: `copied-next-suffix`。現在は非推奨
- 参考キャッシュ再生成:
  - `logs/20260507_224417_846.log`: `005_pc_why-restart-fixes`, `Total execution time: 21.05s`, `VideoPhase: 0.01s`, `FinalizePhase: 4.38s`
  - `logs/20260507_224930_944.log`: `005_pc_why-restart-fixes`, `Total execution time: 29.84s`, `VideoPhase: 0.01s`, `FinalizePhase: 5.80s`
- 判定:
  - PNG 字幕チャンク分割は採用
  - transition suffix copy は撤回。現在は `reencoded-next-suffix` を推奨
  - 変更後 `005` は旧経路比で総時間 `-1058.15s`、約 `68.3%` 短縮。ただし worker 数、永続キャッシュ、コマンド条件の差も含むため、全短縮を単独変更の効果として扱わない
  - cold-cache の再比較を行う場合は、同じコマンドで `cache/` を削除するか `--cache-refresh` を指定して別途記録する

## 現時点での打ち止めライン

CPU 経路では、レンダラー内部だけでさらに大きく縮める余地は以前より小さくなっています。

次の大きな改善が必要なら、候補は次の 3 つです。

- GPU 実機で scene fast path を本格運用する
- より安定した高速 TTS に切り替える
- 「1 シーン 1 render graph」を本格実装する

逆に、以下はもう安易にやらないこと:

- CPU で巨大 scene fast path を既定有効化
- CPU で `clip_workers` を大きく戻す
- VOICEVOX の長い待機リトライを増やす
- `no_sub` を既定出力へ戻す
