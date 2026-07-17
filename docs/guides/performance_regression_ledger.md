# 高速化の履歴と回帰防止メモ

このドキュメントは、Zundamotion を再度高速化するときに「以前に遅くなった変更」を繰り返さないための記録です。

結論から書くと、CPU 経路では「大きな 1 本の filter graph にまとめれば速い」とは限りません。実測しない最適化は簡単に悪化します。

## AI向けの読み方

このファイルは、次の順で読むと判断を間違えにくいです。

1. `最新の採用・却下一覧` で、何をしたか、効果があったか、採用可否を先に確認する
2. 迷った項目だけ、後続の個別セクションで実測条件とログを確認する
3. `遅くなった変更` / `速くなった変更` で、過去に失敗・成功した理由を見る
4. `ベンチマーク時の手順` で、次に測るときの条件を揃える
5. `参考ベースライン` は過去ログの詳細。厳密比較ではなく、傾向確認として扱う
6. 詳細な個別ログは `docs/guides/performance_logs/` を参照する

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

- 何をしたのかを残す
- 効果があったのかを残す
- 採用するのか、却下するのかを残す
- 再計測時の前提条件を固定する
- どこまでが現実的な改善余地かを明確にする

## 先に結論

- 採用するもの: scene/subtitle cache、トピック単位のシーン分割、FinalizePhase cache、PNG 字幕チャンク分割、content-addressed VOICEVOX cache、ffprobe/probe dedupe、Performance summary instrumentation。
- 条件付きで使うもの: ASS/libass 字幕は軽い字幕だけ。通常字幕は可読性を優先して PNG を標準にする。
- 却下するもの: 巨大 filter graph 化、subtitle-only transparent video、static slide fast path、scene-unit filter graph、GPU overlay、transition suffix stream copy、過大な CPU worker/thread 設定。
- 注意するもの: NVENC preset は `p1` から `p7` に正規化する。`quality=speed` では `p1` を使う。`cache_refresh` は同一キーを何度も消さない。
- いまの CPU 経路の残ボトルネックは主に `VOICEVOX`、行クリップ生成、長尺時の字幕チャンク焼き込み。

## 最新の採用・却下一覧

2026-05-28 時点の判断です。新しく高速化を試す場合は、この表を先に更新してください。

| 対象 | 何をしたのか | 効果があったのか | 採用可否 |
|---|---|---|---|
| scene base / subtitle cache | scene base と字幕済み scene をキャッシュする | 字幕済み scene cache hit で `VideoPhase` がほぼ 0 秒になる | 採用 |
| トピック単位のシーン分割 | 長い `main` に詰めず、章やトピックごとに scene を分ける | 一部修正時に未変更シーンを再利用しやすい | 採用 |
| FinalizePhase cache | transition boundary と final concat intermediate を内容ハッシュでキャッシュする | transition boundary と final concat の再生成を避けられる | 採用 |
| PNG 字幕チャンク分割 | PNG 字幕焼き込みを字幕範囲ごとの chunk に分ける | 巨大 filter graph による長時間停止を避けられる | 採用 |
| PNG 字幕チャンク/gap exact trim | chunk と gap を `trim` / `atrim` で正確に切る | `-ss` + stream copy で起きた発話二重化を避けられる | 採用 |
| PNG 字幕チャンクサイズ auto | 字幕密度、gap、最長連続字幕区間から chunk size を決める | 既知の中尺ケースで過剰な chunk 増加を避けられる | 採用 |
| PNG 字幕 `compress_level=1` | PNG 圧縮レベルを軽くする | bounded bench で `compress_level=6` より速く、サイズ差も小さい | 採用 |
| 顔 overlay 事前キャッシュ | 同一実行内の顔 overlay PNG を事前生成して再利用する | clip ごとの顔 overlay 再生成を抑制できる | 採用 |
| 画像内容署名付き cache key | 既存ローカル画像パスの cache key は `sha256` を正とし、`mtime` は含めない | 同名画像差し替えを検知しつつ、同一内容の再出力で scene cache を無効化しない | 採用 |
| Performance summary instrumentation | FFmpeg/ffprobe/cache/字幕PNG/中間ファイル/VideoPhase内訳を記録する | 既存経路を変えずに次の削減対象を判断できる | 採用 |
| VOICEVOX content-addressed speech cache | 音声 cache を line_id 依存から内容署名ベースに変える | 同一テキスト・同一話者・同一パラメータを scene/line をまたいで再利用できる | 採用 |
| ffprobe 種別 PerfSummary | ffprobe を duration/stream/other に分類して集計する | probe 削減対象を判断しやすくなる | 採用 |
| media probe in-flight dedupe | 同一実行内の同一 duration/media-info probe をまとめる | 同一 probe の多重起動を避けられる | 採用 |
| media-info stream probe in-flight dedupe | `has_audio_stream` などの同一 media-info probe を同一実行内でまとめる | 並列処理中の同一ファイル stream ffprobe 多重起動を避けられる | 採用 |
| media duration in-flight dedupe | 同一実行内の同一 duration probe を完了前からまとめる | 並列処理中の同一 duration ffprobe 多重起動を避けられる | 採用 |
| A/V safety instrumentation | `run_id`、`AVWarning`、subtitle burn、ffprobe caller/path を記録する | timestamp warning や重い subtitle burn の発生箇所を追跡できる | 採用 |
| SceneCache miss observability | base/subtitle/timing の短縮キーと miss reason を PerfSummary に残す | キャッシュ無効化の原因をログ末尾と JSON から切り分けやすい | 採用 |
| subtitle gap copy 最大化 | 字幕のない gap を stream copy で最大限使う案を検証した | `000_intro_channel-intro` では `SubtitleGap count=0` で削れる gap がなかった | 却下 |
| subtitle PNG tight bbox 化 | 字幕 PNG を bbox に合わせて小さく crop する案を検証した | PNG は字幕ボックス相当サイズで、crop は背景ボックス表現を壊すリスクが高い | 却下 |
| subtitle PNG input 共有 | 同じ字幕 PNG input を共有する案を検証した | `000_intro_channel-intro` では duplicate total `0` で input count は減らなかった | 却下 |
| face overlay input 共有 | 同じ顔 overlay input を共有する案を検証した | `000_intro_channel-intro` では duplicate total `0` で input count は減らなかった | 却下 |
| subtitle-only transparent video | 字幕だけの透明動画を作り、本編へ 1 回 overlay する案を試した | qtrle/alpha 中間動画が重く、I/O も増えた | 却下 |
| static slide fast path | 静止スライドを専用 fast path に流す案を検討した | 対象条件が狭く、既存 line clip + cache と競合する | 却下 |
| scene-unit filter graph | scene 全体を 1 本の filter graph にまとめる案を検討した | 巨大 filter graph 化で debug 性と保守性が落ちる | 却下 |
| GPU overlay / CUDA overlay | CUDA overlay を使う案を検証した | smoke test 失敗。CPU/GPU 往復のリスクが高い | 却下 |
| transition suffix stream copy | next scene suffix を stream copy で切り出す案を試した | next scene 冒頭音声が再出現する場合がある | 却下 |

## 2026-06-10 039_security_librahack 再生成ログ観察

対象ログ:

- `logs/20260610_172006_476.log`
- `logs/20260610_180259_569.log`

前提:

- 1 本目は完走ログ。
- 2 本目は `18:13:34` 付近で終わっており、`VideoPhase` 完了、`FinalizePhase`、`PerfSummary`、`Total execution time` は出ていない。
- したがって、これは「完走時間の比較」ではなく「`police_hook` 変更がどこまで再計算を波及させたか」の観察メモとして扱う。

### 事実

1 本目の完走ログでは、全体の支配コストは `VideoPhase` と `FinalizePhase` だった。

| metric | value |
|---|---:|
| AudioPhase | 74.73s |
| VideoPhase | 919.62s |
| FinalizePhase | 529.88s |
| Total | 1538.50s |
| ffmpeg_calls | 250 |
| ffprobe_calls | 205 |
| cache_hit | 852 |
| cache_miss | 182 |
| subtitle_burn_ms | 395511.3 |
| face_precache_ms | 57222.2 |
| scene_concat_ms | 22873.2 |
| `has_audio_stream` ffprobe | 129 calls / 149598.7ms |

同じ 1 本目で目立つ点:

- `FinalizePhase` では `finalize_transition_*` が 21 本すべて `Cache MISS`。
- `FinalizePhase` だけで約 8.8 分かかっている。
- `subtitle_burn_ms` が約 395.5 秒あり、字幕焼き込みだけで約 6.6 分使っている。
- `has_audio_stream` の ffprobe が 129 回、累計約 149.6 秒で、probe だけでも約 2.5 分使っている。

2 本目の途中ログでは、`AudioPhase` は 77.34s で、ここは大差がない。

一方で `SceneCache` の miss が `police_hook` だけに留まっていない。

base/sub 両方が miss している scene:

- `intro`
- `police_hook`
- `outline`
- `shock_numbers`
- `frame`
- `timeline`
- `timeline_start`
- `timeline_trouble`
- `timeline_arrest`
- `timeline_statement`
- `crawler`
- `load_comparison`

2 本目途中時点の集計:

| metric | value |
|---|---:|
| SceneCache MISS | 24 |
| SceneCache STORE | 20 |
| SubtitleInput | 13 |
| FilterGraph | 26 |
| AVWarning | 18 |

重要:

- 2 本目では `finalize_transition_*` の再生成は 0 回。
- `finalize_concat.mp4` の再生成も 0 回。
- つまり今回遅かった主因は `FinalizePhase` ではなく、`SceneCache` が前半から中盤の多数シーンで外れ、`VideoPhase` が広く再実行されたこと。

### 解釈

`police_hook` だけを直したつもりでも、実際には少なくとも前半 12 scene が再レンダリングされている。

ログ上の miss 理由は次の 2 段構えになっている。

- subtitle layer: `reason=subtitle_config_or_timing_changed`
- base layer: `reason=base_video_not_cached`

調査で確認できたこと:

- scene cache key に含まれるローカル画像署名が `path + size + mtime_ns + sha256` だった。
- SlideForge が内容不変のスライド PNG を再出力すると `mtime_ns` だけが変わり、該当画像を使う base/sub scene cache が無効化されていた。
- `police_hook` の変更そのものより、動画生成前のスライド一括再出力が多数 scene の再生成を引き起こしていた。

特に不自然なのは `intro` まで miss している点。

`intro` が無変更でも base/sub が両方 miss したのは、背景 PNG の内容ではなく更新時刻まで cache key に含めていたため。

画像は既に `sha256` で内容変更を検知できるため、`mtime_ns` を加える必要はなかった。

### 今回のボトルネック整理

優先度順:

1. 同一内容の画像再出力で scene cache invalidation が発生する
2. subtitle burn の CPU コストが大きい
3. `has_audio_stream` 系 ffprobe がまだ多い
4. cold な `FinalizePhase` は依然として重い

今回の `police_hook` 差分に限れば、最優先は 1。この問題は 2026-06-11 に対応済み。

`FinalizePhase cache` は効いているが、その前段の `VideoPhase` が大量再実行されると体感差はまだ大きい。

### 改善案

#### P0: 画像 cache key を内容基準へ変更する

対応:

- 画像の cache key は `path + size + sha256` とする。
- 動画・音声はハッシュ計算コストを避け、`path + size + mtime_ns` を維持する。
- 同一画像再出力、画像内容変更、非画像 mtime 変更の回帰テストを追加する。

#### P0: subtitle layer と base layer の責務をさらに分離する

現状でも sub/base の 2 層はあるが、sub miss のあと base も未命中になっている。

見直し候補:

- base scene key から subtitle timing 由来の値が混入していないか確認する。
- scene 内の audio duration だけで base が決まる構造なら、その依存を scene ローカルに閉じる。
- chapter 時刻や後続シーン offset のような finalize 向け情報を base cache key に入れない。

狙い:

- 字幕タイミングだけ変わった場合でも base を再利用する。

#### P1: cache miss 理由を「なぜその値が変わったか」まで出す

現状の `reason=subtitle_config_or_timing_changed` は粒度が粗い。

追加したい内訳:

- text changed
- audio duration changed
- subtitle style changed
- scene timing offset changed
- scene composition changed
- background/character transform changed

狙い:

- 「本当に `police_hook` だけか」をログから即判定できるようにする。

#### P1: subtitle burn の重い scene を継続監視する

1 本目では `subtitle_burn_ms=395511.3` と大きい。

継続施策:

- `subtitle_burn_top` 上位 scene を定期的に見る。
- 4 字幕以上を 1 chunk に詰めすぎている scene があれば chunk 分割を見直す。
- スライド系 scene で subtitle overlay と face overlay の同時適用が不要な場面は構成を簡素化する。

#### P1: `has_audio_stream` probe をさらに減らす

1 本目では 129 回 / 約 149.6 秒で、まだ大きい。

候補:

- clip render 前後の stream probe を path 単位で強く再利用する。
- scene concat / subtitle burn / finalize で同一ファイルを複数回見ている経路を棚卸しする。

### 次に確認すべきこと

実装前に次を確認すると切り分けが速い。

1. 同一台本で `police_hook` の文言だけ 1 行変えた最小ケースを作る
2. その前後で `SceneCache` hit/miss の scene 一覧を比較する
3. `intro` まで miss するなら cache key 設計問題として扱う
4. `police_hook` 以降だけ miss するなら timeline/timing 連鎖として扱う

### 今回の判断

- `FinalizePhase cache` 自体は機能している
- 今回の遅さの本丸は、画像署名に `sha256` と `mtime_ns` の両方を含めていたため、SlideForge が同一内容の PNG を再出力しただけで `SceneCache` が無効化されたこと
- 画像は `path + size + sha256`、動画・音声は従来どおり `path + size + mtime_ns` で識別する
- 次の改善対象は `FinalizePhase` ではなく、scene cache miss reason の可観測性

### 対応結果

2026-06-11 に画像署名を修正した。

- 画像は内容が同一なら、再保存で `mtime_ns` が変わっても cache key を維持する。
- 画像内容が変われば `sha256` が変わるため cache miss する。
- 動画・音声は内容ハッシュ計算コストを避け、従来どおり `mtime_ns` 変更で cache miss する。
- `tests/test_cache_manager.py` に同一画像再出力、画像内容変更、非画像 mtime 変更の回帰テストを追加した。
- 署名形式が変わるため、修正適用後の初回レンダーだけは既存画像 scene cache と互換せず cold run になる。

既存短尺台本 `scripts/benchmark_perf_summary.yaml` を Docker 内で実行し、初回生成後に背景 PNG の `mtime` だけを更新して再実行した。

| metric | 初回 | 同一内容 PNG 再出力相当 |
|---|---:|---:|
| Total | 74.55s | 22.46s |
| VideoPhase | 53.63s | 1.06s |
| FinalizePhase | 1.04s | 0.39s |
| line_clips | 3 | 0 |
| subtitle_chunks | 1 | 0 |
| subtitle_burn_ms | 5528.5 | 0.0 |

再実行時に `scene=perf_summary_smoke layer=sub HIT` を確認した。これにより、SlideForge が同一内容のスライド PNG を再出力しても scene cache を再利用できる。

## 2026-05-20 P0-1 Performance 計測ログ拡張

何をしたのか:

- `[PerfSummary]` に FFmpeg/ffprobe 呼び出し回数、cache hit/miss/write、line clip、字幕 PNG、字幕 chunk、中間ファイル量を追加した。
- JSON 出力 `output/perf/perf_summary.json` を追加し、`system.performance.summary_json` で出力先を変更できるようにした。

効果:

- `scripts/benchmark_perf_summary.yaml` で、`ffmpeg_calls=14`、`ffprobe_calls=10`、`subtitle_chunks=1`、`subtitle_png=6`、`intermediate_files=19` を記録できた。
- 既存のレンダリング経路、PNG 字幕、口パク、YAML DSL には影響せず、後続の削減対象を比較できるようになった。

採用可否:

- 採用。通常ログは `[PerfSummary]` の短い数行に留める。

## 2026-05-20 P1-1 VOICEVOX content-addressed cache / ffprobe 削減

何をしたのか:

- VOICEVOX 音声 cache の出力名を line_id 依存の `<line_id>_speech_<hash>.wav` から `voice_speech_<hash>.wav` に変更。
- cache key には `text`, `speaker`, `speed`, `pitch`, `intonation`, `volume`, `pre_phoneme_length`, `post_phoneme_length`, VOICEVOX engine version, dictionary hash, audio params, `voicevox_url` を含める。
- plain VOICEVOX 音声は line_id ごとの再保存を避け、content-addressed cache path を直接使う。
- `get_audio_duration()` 直呼びを `CacheManager.get_or_create_media_duration()` 経由へ寄せた。
- media duration / media info cache に in-flight dedupe を追加し、同一実行内の同一 probe 多重起動を抑制。
- PerfSummary に ffprobe 種別を追加。

効果:

- 6 発話中、実際の VOICEVOX 生成は 2 種類のテキスト分だけ。
- 同一テキストは `Cache disabled: Reusing existing ephemeral output` で再利用された。
- media probe in-flight dedupe により、短尺ベンチの `AudioPhase` は `2.24s -> 1.30s`、`ffprobe_calls` は `14 -> 12` に減った。
- 実動画 warm-cache では `Total execution time` が `38.10s -> 13.54s`、`AudioPhase` が `29.57s -> 4.64s`、`ffprobe_calls` が `101 -> 19` に減った。

注意:

- cache key に VOICEVOX engine version と dictionary hash を含めたため、初回は旧音声 cache と互換せず cold run になる。
- cold run では `030_cert_aws-saa-00_overview.p1-check.mp4` が `AudioPhase: 75.73s` になった。これは旧 key から新 key への移行コストで、2 回目以降は warm-cache の値を見る。
- duration cache hit のログはまだ多いが、実 ffprobe 起動数は `ffprobe_duration_calls` を見る。

採用可否:

- 採用。同一テキストを scene/line をまたいで再利用でき、実動画 warm-cache でも効果が出た。

## 台本設計でキャッシュを効かせる

長尺動画では、台本構造そのものも再生成時間に影響します。

推奨:

- 長い本編を 1 つの `main` シーンに詰め込まず、トピック、章、数枚のスライド単位でシーンを分ける。
- 変更されやすい導入、用語説明、実例、まとめは別シーンにしておく。
- 各シーンの `id` は、`main_intro`、`main_inheritance`、`main_summary` のように内容が分かる名前にする。
- シーンを分けた場合は、各シーン冒頭で必要な `bg`、`characters`、表情を明示する。

理由:

- Zundamotion はシーン単位で `scene_<id>_base` / `scene_<id>_sub` のキャッシュを持つ。
- 字幕やセリフを一部だけ直した場合、未変更シーンは cache hit しやすい。
- 1 つの巨大シーンにまとめると、その中の一部変更でもシーン全体のキャッシュが無効になりやすい。

注意:

- シーンを細かくしすぎると、シーン連結やトランジション境界が増える。1 スライド 1 シーンを機械的な標準にはしない。
- `transition` を多用すると境界処理が増える。キャッシュ粒度を分けたいだけなら、通常のシーン分割でよい。
- `characters_persist` と `background_persist` は同一シーン内の継続であり、シーンをまたいだ状態継承に依存しない。

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
- 字幕のない gap と字幕チャンクのベース動画は、`trim` / `atrim` で正確に切り出して最後に concat する
- 2026-05-11 以降、既定の `subtitle.png_chunk_size` は `auto`
  - `ZUNDAMOTION_SUB_PNG_CHUNK_SIZE` で実行環境ごとの固定値に上書きできる
  - 90字幕級・長尺では `15-16` 程度を選び、66字幕級では従来相当の `12` を維持する

効果:
- 長尺台本で巨大 filter graph が詰まる状態を避けられる
- PNG 字幕の可読性を維持したまま、ASS/libass へ逃がさずに完走しやすくなった
- 長尺・字幕多数時の ffmpeg 起動/concat 小片数を減らす。ただし巨大 filter graph へ戻さないため上限は `36` に制限する
- 2026-05-18 に、gap / chunk 切り出しの `-ss` + stream copy は廃止した。短尺動画で切り出し前の音声が混ざり、同じ発話が二重に聞こえる再現があったため、速度より音声境界の正確さを優先する

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

auto 選択値 smoke:
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

2026-06-19 `copipetan-dev-room/047_security_csrf` FFmpeg 停滞検知追加:

- 症状:
  - パイプライン自体は残るが、内側の FFmpeg が `pct:98.x%` / `size:0.3MB` 付近から数時間進まない
  - 既存の heartbeat は出続けるため、外側からは「処理中」に見える
- 対応:
  - `run_ffmpeg_async` に進捗 marker と出力ファイルサイズの停滞検知を追加
  - `FFMPEG_STALL_TIMEOUT_SEC` 秒、どちらも変化しない場合は FFmpeg を terminate し、猶予後に kill する
  - 既定値は `900` 秒、`0` で無効化
- 狙い:
  - 外側 watchdog の起動忘れに依存せず、エンジン内で停止状態を検出して失敗扱いにする

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

## 2026-05-16 PNG 字幕 P0/P1 判断

詳細ログ:

- [2026-05-16 PNG 字幕高速化ログ](performance_logs/2026-05-16-png-subtitle.md)

結論:

- P0 診断ログは採用。`[SubtitlePNG]` / `[SubtitleChunk]` / `[SubtitleGap]` / `[SubtitleInput]` / `[FaceOverlay]` / `[SceneCache]` / `[FilterGraph]` を追加した。
- P1-1 `subtitle.png_chunk_size=auto` の密度ベース調整は採用。
- P1-7 `subtitle.png_compress_level=1`, `subtitle.png_optimize=false` は採用。
- P1-2 gap copy 最大化、P1-3 tight bbox 化、P1-4 scale 事前固定、P1-5 subtitle input 共有、P1-6 face input 共有は、`000_intro_channel-intro` 実測では改善余地なしとして却下。
- P1-8 CPU worker/thread 再調整は、比較実測がないため保留。

代表実測:

| source | total | duration | ratio | VideoPhase | FinalizePhase | subtitles | chunks | note |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| baseline long log | `2995.87s` | `975.77s` | `3.07x` | `2526.82s` | `259.13s` | `149` | 未記録 | P0 追加前 |
| `logs/20260516_174940_014.log` | `578.96s` | `193.41s` | `2.99x` | `475.94s` | `50.46s` | `60` | `6` | `000_intro_channel-intro` |

`000_intro_channel-intro` の判断材料:

- `SubtitleGap count=0`: gap copy 最大化では削れない。
- subtitle input duplicate total: `0`: subtitle PNG input 共有は効果なし。
- face overlay duplicate total: `0`: face overlay input 共有は効果なし。
- subtitle PNG は最大 `1068x200` 程度: 動画フルキャンバスではなく、tight bbox crop は背景ボックス表現を壊すリスクが高い。
- subtitle chunk burn 合計は約 `95s`: 残りの主因は input 重複ではなく line clip の CPU overlay と再エンコード時間。

## 2026-05-28 P0 Performance / A-V safety instrumentation

何をしたのか:

- timestamp 系 warning の発生箇所を特定する
- 複数 render run のログ混在を防ぐ
- scene/chunk 単位で subtitle burn の重さを確認する
- ffprobe の caller/path 別発生源を確認する
- 既存 `[PerfSummary]` の主要 metric 名を維持しつつ、追加計測を additive に入れる
- ログに `[Render] run_id=...`、`[AVWarning]`、`[PerfSummary] av_warnings_total=...`、`subtitle_burn_top`、`ffprobe_top_caller`、`ffprobe_top_path` を追加した。
- JSON に `run_id`、`av_warnings`、`subtitle_burn.by_scene`、`subtitle_burn.top_chunks`、`ffprobe.by_caller`、`ffprobe.top_paths`、`ffprobe.top_callers` を追加した。

出力互換性:

- 既存 `[PerfSummary]` の主要 metric 名は維持
- `output/perf/perf_summary.json` は維持
- `run_id` は additive に追加
- `output/perf/perf_summary.<run_id>.json` を追加

効果:

- 短尺 benchmark で `run_id`、`av_warnings.total=0`、`subtitle_burn.by_scene`、`subtitle_burn.top_chunks`、`ffprobe.by_caller`、`ffprobe.top_callers` を確認できた。
- 計測と安全性確認だけを追加し、レンダリング結果を変える高速化は入れていない。

採用可否:

- 採用。timestamp warning は隠さず構造化して記録する。
- subtitle-only transparent video / 巨大 filter graph / GPU overlay / ASS 強制化は、この P0 では対象外。

## 2026-05-29 media-info stream probe in-flight dedupe

何をしたのか:

- `get_media_info()` に同一実行内の in-flight dedupe を追加した。
- `has_audio_stream()` などが同じメディアに対して並列に stream probe した場合、最初の ffprobe task を共有する。
- 既存の process-local memo は維持し、完了後の同一ファイル再問い合わせも従来通り再利用する。

効果:

- 単体テストで同一ファイルへの並列 `has_audio_stream()` 3 回が ffprobe 1 回にまとまることを確認した。
- `ffprobe_top_caller caller=has_audio_stream` が目立つ実動画ログで、同一ファイルへの同時 stream probe がある場合の無駄を削れる。

採用可否:

- 採用。duration/media-info の既存 in-flight dedupe 方針と同じで、レンダリング経路や出力内容を変えない。
- 効果は「同一ファイルの並列 probe」があるケースに限られる。ファイルがすべて異なる場合は、次に呼び出し元で既知の音声有無を渡す設計を検討する。

## 2026-07-16 PCM中間音声とDTS安全concat

何をしたのか:

- 中間WAVを `pcm_s16le`、最終MP4をAAC-LCへ分離した。
- 行クリップの映像・音声PTSを0始点へ正規化した。
- AACは各クリップ境界にencoder delay/paddingを持つため、複数AACクリップは事前判定でstream copyを避け、映像copy＋音声AAC再エンコードを使用する。
- PCM等の安全な入力または単一入力は従来通りcopy経路を維持する。
- 中間形式・mix処理のバージョンを音声キャッシュキーだけに追加した。

性能上の判断:

- 複数行シーンでは音声再エンコードが増えるが、映像はcopyするためPNG字幕や映像の再エンコードは増やさない。
- `Non-monotonic DTS` を出してから再試行せず、codec事前判定で警告自体を回避する。
- 字幕PNGの描画方式、チャンク分割、見た目は変更しない。

## 2026-07-17 PNG字幕の極短edge gapフォールバック

何をしたのか:

- PNG字幕のsegment経路は、先頭・末尾gapが `copy_gap_threshold` 以上の場合だけ選択する。
- コンテナまたは音声のdurationが映像packet終端より長い素材では、gapのexact cutが失敗し得るため、失敗理由を記録してscene全体の字幕burnへフォールバックする。
- 複数の字幕chunkや十分に長いgapでは、従来のsegment最適化を維持する。

性能上の判断:

- 1〜2フレーム級のedge gapをcopyするためにsegment分割する効果は小さく、FFmpegの丸めとstream終端差による失敗リスクの方が大きい。
- フォールバック時はscene全体を再エンコードするため遅くなるが、生成失敗や欠落segmentを連結するより安全性を優先する。
- PNG字幕の描画方式、チャンク内の字幕、見た目は変更しない。

## 2026-07-17 transition concatと行クリップ計測

何をしたのか:

- ローカルトランジションのprefix、boundary、suffix連結を直接 `concat_videos_copy()` する経路から `concat_videos_safe()` へ統一した。
- AAC/MP3を含む複数断片は、映像copy＋音声AAC再エンコードを事前選択する。音声なし断片が混在する場合は、映像をcopyしたまま同じsample rate/channelsの無音AACを補ってから連結する。
- `lossy_audio_encoder_delay` による予定済み音声再エンコードはINFOとし、実copy失敗やDTS警告後のフォールバックだけをWARNINGに残した。
- 行クリップ計測でauto-tune分岐内だけに定義されていた `elapsed` と特徴量を分岐外へ移し、並列シーンでも全行を記録するようにした。
- 行ごとにcache lookup、render、cache store、素材準備、合計時間、cache状態、worker、出力パス、字幕・顔・移動・effect有無を性能JSONへ保存する。
- 集約はlockで保護し、件数、HIT/MISS、合計、render、平均、p50、p95、最大、遅い上位10件を出力する。

性能上の判断:

- transition部品の音声再エンコードは増えるが映像stream copyは維持し、警告発生後のフルトランジション再エンコードを避ける。
- `video_line_clip_ms` は「素材準備開始からoverlay適用後の行クリップ取得完了までの合計時間」とする。内訳は別指標で保持する。
- 計測失敗は動画生成を止めないが、握り潰さずWARNINGへscene/lineと原因を残す。

## 2026-07-17 対象別キャッシュMISS実動検証

何をしたのか:

- scene IDとcache layer、transition境界index、final concatを指定する完全一致のキャッシュ無効化APIを追加した。
- scene cache HITで行処理へ入らない場合を `line_clip_metrics=not_executed` として、0 msの実行結果と区別した。
- CPU固定時はCUDA/OpenCL smokeを省略し、`[FilterDiag] skipped reason=cpu_mode` を記録する。autoやGPU候補では従来の診断を維持する。
- transition部品の安全concat完了時にfrom/to、mode、理由、映像・音声codec、DTS警告件数を構造化ログへ出す。
- 短尺素材でcontainer durationがvideo stream durationより長い場合もfreeze-tailが映像を失わないよう、映像streamの終端を基準にseekする。

064対象MISS実測:

- 無効化: `classic_reference` 24ファイル、`opening->office_alarm` 18ファイル、final concat 3ファイル。
- line clip: 6 MISS、合計 `74819.2 ms`、render `73144.8 ms`、p95 `17102.7 ms`、最大 `17968.0 ms`。
- 他scene cacheにより79行を未実行として計上。
- transition: `audio_reencode / lossy_audio_encoder_delay / h264 / aac / dts_warnings=0`。
- 最終出力: AAC-LC、48 kHz、stereo、A/V開始差 `0.063016 s`、尺差 `0.016617 s`、`av_warnings_total=0`。

採用可否:

- 採用。全キャッシュ削除を避けながら修正経路だけを実行でき、性能JSONに対象と結果を残せる。
- キャッシュ削除は64桁SHAを含む完全なファイル名構造で照合し、scene IDの部分一致は使用しない。
