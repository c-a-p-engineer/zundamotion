# 📋 Zundamotion タスクリスト（優先度順）

本ファイルは、現状コード・ログの観察結果に基づく改善タスクと将来機能を、優先度順に整理したものです。

参照ログ: `logs/20250831_172922_025.log`, `logs/20250831_004024_506.log`, `logs/20250830_155656_544.log`

### 最新ログサマリ（2025-08-31 17:29 実行）

- AudioPhase: ≈14.1s（概算、問題小）
- VideoPhase: 136.09s（支配的）
- BGMPhase: 2.59s / Finalize: 34.27s
- NVENCのスモークテストは成功→エンコードはNVENC使用。
- CUDAフィルタのスモークテストが exit 218 で失敗し、以降CPUフィルタへフォールバック。
- スレッド: `clip_workers=2`, `filter_threads=6`, `filter_complex_threads=6`（CPU経路の既定ヒューリスティクス通り）。

### 最新ログサマリ（2025-08-31 18:50 実行）

- AudioPhase: 10.52s（軽量）
- VideoPhase: 160.26s（支配的）
- BGMPhase: 3.29s / Finalize: 39.16s
- NVENC: 利用可能（エンコードはNVENC）。
- フィルタ: 字幕PNGがあるクリップは「CPU overlays（RGBA）」を選択。RGBA無しの一部クリップのみCUDA経路。
- 補足: `--no-cache` 下でもEphemeral再利用が機能し、同一キー生成の重複が抑止されている（ログで確認）。

直近のボトルネックは VideoPhase（CPU overlay）と Finalize（concat I/O）。

## P0（必須・最優先）



### 03. シーンベース合成の強化（静的オーバーレイの事前合成）

- タイトル: 行で不変な立ち絵/挿入画像をシーンベースに事前合成し、行ごとのCPU overlayを最小化
- 詳細:
  - 各シーンで可視キャラ（name/expression/scale/anchor/pos）の共通集合を抽出→ベース映像にPNG合成して書き出し。
  - 行側は「字幕＋音声」のみの重畳に縮退。`pre_scaled`/`normalized` の伝搬を徹底。
  - 既存の静的検出ロジック（`video_phase`）を見直し、確実に発火・再利用されるようにログと条件を強化。
- ゴール: 行ごとのフィルタグラフを短縮し、VideoPhaseのCPU overlayコストを大幅に削減。
- 実装イメージ: `VideoPhase.run` の静的検出→`render_looped_background_video` とベース生成へ委譲、行側で省略。

### 04. RAMディスク利用と同時実行数の適応制御（継続検証）

- タイトル: I/O 待ちを最小化しつつ GPU/CPU の飽和を回避
- 詳細: 一時出力先として `/dev/shm`（空き容量チェック付き）を優先。`clip_workers` を HW 検出と実測に基づき自動調整（NVENC=1〜2、CPUのみ=CPU/2 など）。`-filter_threads`/`-threads:v` をワーカー数に応じて設定。
- 背景: VideoPhase が支配的。I/O と CPU フィルタの両輪で時間を消費している可能性が高い。GPU が1基の場合は並列し過ぎるとスループットが低下。
- ゴール: システム構成に応じた安定したスループットを確保。ワークロード変動時でも p95 を悪化させない。
- 実装イメージ: `temp_dir` 初期化時に RAMディスク候補を選択。`_determine_clip_workers` を HW/Encoder 種別と `nvidia-smi`/実測に基づき調整。FFmpeg に `-filter_threads N` を付与。

補足（今回ログ 20250831_172922_025）:
- 本件ログでは `clip_workers=2`, `filter_threads=6` と保守的な設定で稼働。CUDAフィルタ失敗が主因でCPU合成となり、VideoPhaseが支配。
- CUDA経路が復旧すれば、ここは `clip_workers=1〜2`, `-filter_threads=1` 上限でも十分スループットが改善見込み。

### 24. 字幕PNG生成のレイテンシばらつき解消（完了）

- モジュール内フォントキャッシュを導入し、プロセス内でのフォント初期化コストを削減済み。
- 背景: `logs/20250830_035010_363.log` の 03:53:10→03:53:16 で PNG 1枚の生成に ~5.96s。
- ゴール: 字幕PNG生成の p95 を <100ms に安定化。
- 実装イメージ: `components/subtitle_png.py` でフォントロードのシングルトン化、文字列→レイアウトの LRU、`--precache-subtitles` フラグの追加。

<!-- 07. ログ整形の乱れ修正（対応済み） -->

## P1（重要・中期）

### 30. 複数キャラ・レイアウト・動き（基盤と最小実装）

- 概要: 複数キャラの同時表示、入退場、移動/拡大縮小/回転/不透明度、表情切替の最小セットを実現。
- スキーマ拡張（YAML）:
  - `scene.characters[]`: {name, visible, slot(left|center|right|bottom|custom), x, y, scale, rotate, z, mirror, expression}
  - `line.actions[]`: {t, target(name|all|speaker), visible, transition(fade|slide|pop), duration, move:{x,y}, scale, rotate, opacity, ease(in|out|inOut|linear), expression}
  - 時間`t`は行先頭相対秒。省略時は行開始で適用。
- 自動レイアウト: slotごとの既定座標・マージンと重なり回避（最前面キャラを優先）。`custom`は x/y をそのまま使用。
- 入退場: visible=true/false + transition + duration + ease を enable式でffmpeg overlayに反映。
- 2Dトランスフォーム: move/scale/rotate/opacity のキーフレーム（2点補間）→ 簡易tweenを生成。
- 表情切替: `expression` を PNG 切替（fallback: default）。
- Zオーダー: 行ごとに z を昇順で並べ直し（手前が後段 overlay）。
- 話者強調（最小）: speaker に軽シャープ/彩度UP、非話者を-10%減光（有効/無効フラグ）。
- 依存/整合: P0-01 の「顔パーツ事前スケール」キャッシュと連携。ベース合成（静的レイヤ）の検出と両立。

### 31. アクションエンジン拡張（キーフレーム/ease/テンプレ）

- 概要: 2点以外のキーフレーム連結、ease種追加（quad/cubic/back/bounce）、テンプレの導入。
- スキーマ: `line.actions[].keyframes=[{t,x,y,scale,rotate,opacity,ease}]` を許容。`preset: 'enter_left'|'exit_right'|'pop'` 等で簡便指定。
- 実装: 小さなtweenユーティリティで enable式や式値を生成。logに導出パラメタをDEBUG出力。

### 32. ミラー/影/深度（描画品質）

- ミラー: `mirror:true` で左右反転（hflip）。表情PNGの向き依存は fallback（あれば `*_mirrored.png`）。
- 影: ドロップシャドウ（ガウスぼかし＋黒）、床落ち影（楕円PNGのスケール）。強度/オフセットをparams化。
- 深度: zに応じて微ぼかし/彩度を変化させ奥行きを演出（オプション）。

### 33. カメラ/ショット（Ken Burns + フォロー）

- 概要: シーン/行にカメラキーフレーム（x,y,scale）を付与。話者フォローモードで自動寄り。
- スキーマ: `scene.camera.keyframes[]` と `line.actions[].camera.keyframes[]` を許容。`follow:'speaker'|<name>`。
- 実装: ベース映像に対する crop/scale/overlay で疑似カメラ。既存の字幕・キャラ overlay と両立するよう順序を整理。

### 34. 名前枠/ローワーサード/ネームプレート

- 概要: 話者名と枠のプリセット。左右/上下のオート配置。
- スキーマ: `line.nameplate:{style:'default', position:'auto'|'left'|'right', offset:{x,y}}`、色/角丸/影をparams化。
- 実装: テンプレPNG + テキスト合成（Pillow）→ overlay。タイミングは行全体 or アクションt。

### 35. パララックス/パーティクル（強化）

- 概要: 背景/中景/前景のレイヤ速度差、雨/雪/紙吹雪を前景に追加。
- スキーマ: `scene.layers[]:{path, speed_x, speed_y, loop}`。`scene.particles:{type:'snow'|'rain'|'confetti', amount, speed}`。
- 実装: ループ動画/画像のoverlay。速度は enable式で座標を時間関数に。
### 28. アルファ2値化の設定化とプレフライト（堅牢性）

- 背景: `alphaextract+geq` を用いた2値化が環境差で失敗する場合がある。現在は環境変数で自動OFFリトライ。
- 対応: YAML設定（`video.face_overlay.alpha_hard_threshold: {enabled, threshold}`）に昇格。起動時に短いフィルタグラフでプレフライトし、失敗時は自動的に無効化＋ログ。
- ゴール: 予期せぬ 234 の再発防止・原因の明示。
- 実装: `ffmpeg_utils` にスモークを追加し、`VideoRenderer.create` で反映。

### 29. AutoTune の永続化と条件見直し

- 背景: クリップ少数のシーンでは profile結果が不安定。実行毎の学習結果が失われる。
- 対応: 直近の最適caps/clip_workersを `cache/` に保存し、次回実行の既定に適用。CPU overlay 支配の判定閾値を 0.5→0.6 に要評価。

### 27. CUDA不可時のGPUフィルタ代替（OpenCL/Vulkan/QSV overlay の検討）

- タイトル: CUDAフィルタ未対応/失敗環境でのGPU合成代替パスを用意
- 詳細:
    - `overlay_cuda/scale_cuda` が使えない環境向けに、`overlay_opencl` や `overlay_vulkan`（ビルド有効時）、`overlay_qsv` の存在確認とスモークテストを追加。成功時はCPUフィルタではなく当該GPUフィルタを採用。
    - 字幕や立ち絵のアルファ合成要件に応じ、各フィルタのサポート状況を調査し、可能な範囲で適用（不可なら自動でCPU）。
- 背景: `logs/20250830_155656_544.log` で CUDA フィルタのスモークテストが exit 218 で失敗、以降CPU合成となり VideoPhase が支配的に。
- ゴール: CUDA非対応環境でもGPU合成経路を確保し、CPU負荷を軽減。
- 実装イメージ: `ffmpeg_utils.has_*_filters()` を追加し、`VideoRenderer` のフィルタ選択に反映。軽量スモークテストとプロセス内キャッシュはCUDAと同様に実装。

### 08. 同一素材の重複プローブ抑止（完了）

- ffprobeを使う `get_media_info`/`get_*_duration` に短期メモ化を導入済み。

### 07. `--no-cache` 時の挙動とログ文言の明確化（完了）

- 一時出力は `temp_dir`（ephemeral）を使用。ログでも Ephemeral を明示。

### 11. Insert メディア正規化経路の統一（完了）

- Insert 動画の正規化は `normalize_media` に統一済み。

### 09. 字幕クリップ生成のスループット改善

- 背景: PNG生成と合成の並列度が律速になりがち。
- 対応: `clip_workers` の自動最適化、`-filter_threads`/`-filter_complex_threads` の見直し、PNG生成を ProcessPool へ。

### 10. VOICEVOX 音声合成の並列化

- 背景: AudioPhase 27.42s。セリフ数増で直列だと増大。
- 対応: スピーカーID単位での並列化上限を設定し `asyncio.gather` で束ねる。レート制限配慮。

### 12. FinalizePhase の `--final-copy-only` をCLIに配線

- 目的: 再エンコードへのフォールバックを抑止した厳格運用を可能に。

### 13. 字幕フォントのフェイルセーフ

- 背景: 指定フォント不在時の失敗回避。
- 対応: 系統フォントへのフォールバックと警告ログ。

## P2（改善・将来・機能追加）

### 14. 口パク（リップシンク）対応（静止立ち絵の口形アニメ）

- 機能: 音声から音素/ビセームを推定し、`characters/*` の口形差分PNGを時間同期で切替。
- 実装案: 軽量な音素推定（pyopenjtalk/phoneme forced alignment 等）→ タイムラインへ mouth=OPEN/CLOSE を注入 → `render_clip` で overlay 切替。
- 代替: 音量包絡で簡易口パク（閾値2段階）。

### 15. フィルター/エフェクトのプリセット

- 機能: ぼかし/ビネット/色調（LUT）/色温度/ズームパン（Ken Burns）などを行/シーン単位で適用。
- 実装案: `line_config.effects[]` を追加し、`filter_complex` を合成。RGBA無しなら CUDA フィルタ採用。

### 16. トランジション拡充とテンプレ（xfade 以外）

- 機能: スライド/ワイプ/グリッチ/ズーム等の遷移。テンプレ名指定で適用。
- 実装案: `apply_transition` の種類を追加し、パラメータ化。

### 17. カラオケ風字幕（逐次ハイライト/グラデ/縁取り強化）

- 機能: 読上げ進行に応じて文字色を流す。影/縁取り/アウトライン色の詳細設定。
- 実装案: 固定PNGではなく分割PNG or drawboxレイヤ併用、または WebVTT → ffmpeg `subtitles` フィルタ採用の選択肢も検討。

### 17. ピクチャー・イン・ピクチャー（PIP）とフェイスカム枠

- 機能: 任意の動画/画像を右下などにPIP表示。枠・角丸・影のオプション。

### 18. BGM ビート検出と自動カット合わせ

- 機能: BGM の拍に台詞/カットを寄せるオプション。
- 実装案: 簡易オンセット検出 → タイムラインの開始時刻を微調整。

### 19. SRT/WebVTT の入出力

- 機能: 外部字幕との互換（インポート/エクスポート）。

### 20. プレビュー高速レンダリングモード

- 機能: 低解像度+低ビットレートでのクイックプレビュー（最終出力前の確認用）。
- 実装案: `--preview` で `VideoParams` を縮小し、字幕PNGキャッシュを使い回し。

### 21. 背景除去/クロマキー（簡易）

- 機能: 立ち絵/挿入動画の背景透過やクロマキー除去。

### 22. キーフレーム的パラメトリックアニメ

- 機能: 位置/スケール/不透明度を時間指定で変化（ズーム/パン/フェード）。

### 23. プロジェクトテンプレ/テーマ

- 機能: 共通の構成/スタイルをテンプレとして使い回し。


### 24. 吹き出し/ネームプレート（話者UI）

- 機能: キャラ名付きの吹き出し/プレートを表示。左右配置に応じ自動位置。
- 実装案: 吹き出しPNGテンプレ＋テキスト合成、もしくは字幕PNGの別スタイル枠で重畳。

### 25. YAMLスキーマ拡張（assets辞書・字幕スタイルテンプレ）

- 機能: パス直書きを減らし、`assets.*` キー参照で再利用。字幕スタイルのテンプレ名参照。
- 実装案: `script_loader.merge_configs` でテンプレ展開、検証の強化と README 追記。

### 26. 自動ポーズ/句読点ルール

- 機能: 句読点・三点リーダ等で短ポーズを自動挿入。長音/中点列の伸ばし。
- 実装案: 合成前のテキスト整形（オプション）と `AudioPhase` の無音挿入。

### 27. サムネ/チャプター自動生成

- 機能: キーシーンから静止画サムネ／YouTubeチャプター用TXTを自動出力。
- 実装案: `Timeline` のイベントからシーン境界を抽出し、`output.mp4` からフレーム書き出し。

## 補足（今回ログでの主な観測ポイント）

- `AudioPhase` は 27.42s（問題小）。
- `VideoPhase` は 205.31s と支配的。17:32:37 台で `scene_bg_intro.mp4` について `[Cache] Normalized miss` が多数発生（重複正規化の疑い）。
- `assets/bg/countdown.mp4` の正規化は NVENC で 9s 程度（正常）。
- シーン結合（-c copy）は成功しているが ~39s 要しており、I/O 最適化余地あり。

- 直近ログ: `logs/20250830_155656_544.log`
  - `AudioPhase` は 15.17s（問題小）。
  - `VideoPhase` は 111.72s と支配的。開始直後に CUDA フィルタのスモークテストが失敗→CPUフィルタへフォールバック。`clip_workers=2` でCPUフィルタが飽和し切れていない可能性。
  - シーンベース映像は「0 static overlay(s)」のまま生成され、固定コストが発生。`pre_scaled` 伝播による二重スケール回避で置換可能。
  - 背景正規化は NVENC で短時間に完了（例: `sample_video.mp4` ~1.26s、`countdown.mp4` ~5.05s）。
  - BGMPhase 3.40s、FinalizePhase 0.78s と軽微。最終結合は `-c copy` 成功。