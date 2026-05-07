# 高速化の履歴と回帰防止メモ

このドキュメントは、Zundamotion を再度高速化するときに「以前に遅くなった変更」を繰り返さないための記録です。

結論から書くと、CPU 経路では「大きな 1 本の filter graph にまとめれば速い」とは限りません。実測しない最適化は簡単に悪化します。

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
- いまの CPU 経路の残ボトルネックは主に `VOICEVOX`、最終字幕焼き込み、FinalizePhase のトランジション再エンコード

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

## ベンチマーク時の手順

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

## 現時点での打ち止めライン

CPU 経路では、レンダラー内部だけでさらに大きく縮める余地は小さいです。

次の大きな改善が必要なら、候補は次の 3 つです。

- GPU 実機で scene fast path を本格運用する
- より安定した高速 TTS に切り替える
- 「1 シーン 1 render graph」を本格実装する

逆に、以下はもう安易にやらないこと:

- CPU で巨大 scene fast path を既定有効化
- CPU で `clip_workers` を大きく戻す
- VOICEVOX の長い待機リトライを増やす
- `no_sub` を既定出力へ戻す
