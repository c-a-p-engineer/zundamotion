# P0. 高速化（最優先）

## 04. 外側の並列レンダリング（ジョブ並列）

**背景**
1本の ffmpeg 内の並列化は限界がある。シーン毎の独立処理を同時に走らせた方が壁時計が縮む。

**ゴール**

* `--jobs N` で**シーン単位並列**。NVENC は1〜2本同時、CPUは `min(nproc/2, 4)` 目安。

**実装イメージ**

* `GenerationPipeline` or `VideoPhase` に `concurrent.futures` を導入：

  * ワーカー数は `N`。NVENC 検出時は `min(N, 2)` に丸め。
  * 進捗：`tqdm` or 自前ログで全体進捗を集約表示。
  * キャッシュ衝突回避：正規化キャッシュの出力名は**ハッシュのみ**で一意。

---

## 05. FFmpeg 並列オプション最適化（filter\_threads, thread\_flags）

**背景**
明示的に `-threads 1` 指定が残っている／filter並列が無効のケースがあると遅い。

**ゴール**

* フィルタ並列を有効化し、**平均速度 > 1.0×** を安定化。

**実装イメージ**

* 共通オプション：

  * `-threads 0`（auto）
  * `-filter_threads N -filter_complex_threads N`（N = `min(nproc, 8)` など）
  * `-thread_type slice+frame`（対応ビルド/エンコーダのみ）
* 既存の `-threads 1` があれば削除し、上記を `ffmpeg_utils._threading_flags()` で一元化。

---

## 06. NVENC スループット設定（速度寄りプリセット）

**背景**
NVENC は preset で速度/品質が変動。速度を稼ぎたいときは一段軽い preset が効く。

**ゴール**

* 品質が許す範囲で **`-preset p4 → p3`** へ引き上げ（または `-tune hq` の解除）、速度を底上げ。

**実装イメージ**

* `meta.speed_profile: fast|balanced|quality` を導入：

  * fast: `-preset p3`
  * balanced: `-preset p4`（既定）
  * quality: `-preset p5` + `-b:v` 運用など
* 実行ログに決定 preset を出力してベンチ比較可能に。

---

# P1. 安定化

## 07. 署名（signature）比較の厳格化と差分ログ

**背景**
copy-concat 成否は「本当に**完全一致**か」に依存。比較キーが甘いと、copy 失敗や音ズレの火種になる。

**ゴール**

* 一致時のみ copy。**不一致キーをログに列挙**して即判断できる。

**実装イメージ**

* `ffprobe -v error -show_streams -show_format -of json` を解析し、以下を比較：

  * Video: `codec_name,width,height,pix_fmt,profile,level,r_frame_rate,avg_frame_rate,time_base`
  * Audio: `codec_name,profile,sample_rate,channels,channel_layout,sample_fmt,time_base,bit_rate`
  * Format: `format_name`（mp4）
* `compare_media_params(a,b)` は差分キーと各値を返却 → Finalize で WARN ログ。

---

## 08. タイムスタンプ整形（time\_base/PTS 安定化）

**背景**
CFRでも `time_base` や `avg_frame_rate` が微妙に揺れると copy で弾かれたり音ズレが出る。

**ゴール**

* すべてのクリップで **同一の time\_base / avg\_frame\_rate**。

**実装イメージ**

* クリップ出力に以下を追加：

  * `-vsync cfr -r 30`（既存）
  * `-fflags +genpts -avoid_negative_ts make_zero`
  * `-video_track_timescale 90000`（MP4 muxer）
* `ffprobe` で time\_base/avg\_frame\_rate を signature に含めて検証。

---

## 09. エンコーダ選択の実行時固定（混在禁止）

**背景**
実行途中で NVENC/CPU が混在すると copy 失敗の原因。

**ゴール**

* プロセス開始時に NVENC 可否を判定し、**全クリップで同一エンコーダ**を強制。

**実装イメージ**

* 起動時に `is_nvenc_available()` を1回だけ評価→`context.hw_encoder = 'nvenc'|'cpu'` に固定。
* ログに「決定エンコーダ」を出力。

---

## 10. 失敗時フォールバックと早期失敗のトグル

**背景**
copy に通らず再エンコードになると時間がかかる／CI では失敗してほしいケースもある。

**ゴール**

* デフォルトは安全フォールバック、CI では **`--final-copy-only`** で**不一致なら即エラー**。

**実装イメージ**

* CLI 追加：`--final-copy-only`（bool）
* Finalize 内：

  * 一致 → copy
  * 不一致 → `final-copy-only` が True なら `sys.exit(1)`、False なら従来 concat へ。

---

## 11. ロギング / メトリクスの保存

**背景**
回帰検知・チューニングに**数字**が必要。

**ゴール**

* 各フェーズ時間、平均速度、copy 採用可否、署名差分を **JSON で保存**。

**実装イメージ**

* `reporting/generation_report.json`：

  * クリップごとの処理時間/平均速度
  * 正規化キャッシュヒット率
  * Final mode（copy | transcode）
  * 不一致キーの一覧
* CI で閾値監視（速度/採用率が下がったら失敗）。

---

# P2. 拡張機能

## 12. 字幕の固定文字数ラップ（ピクセル幅ラップと切替）

**背景**
日本語などスペースが少ない言語では**一定文字数**での改行が便利。

**ゴール**

* YAML で `wrap_mode: chars` + `max_chars_per_line: N` 指定時に **N文字ごと改行**。

**実装イメージ**

* `subtitle_png.py`：

  * 追加 `def _wrap_text_by_chars(text, max_chars) -> str`
  * `render()` で `wrap_mode` を見て `chars` なら上記を適用、未指定なら従来の `wrap_by_pixel`。
  * さらに**禁則処理**（句読点のぶら下がり回避）オプションも設計しておく。

---

## 13. 字幕 overlay の CUDA 化を opt-in

**背景**
自動で `overlay_cuda` を使うとフィルタグラフが複雑になり、環境差でコケやすい。

**ゴール**

* 既定は **CPU overlay + NVENC エンコード**（安定）。
* `subtitle.use_cuda_overlay: true` の明示時だけ CUDA overlay を利用。

**実装イメージ**

* `subtitle.py`：

  ```python
  use_cuda = bool(style.get("use_cuda_overlay", False)) and is_nvenc_available() and has_cuda_filters()
  ```
* CUDA 経路は **全入力を `hwupload_cuda`** で GPU フレームに統一。失敗時は CPU 経路へフォールバック。

---

## 14. ラウドネス正規化（EBU R128）

**背景**
TTS + BGM の複合でクリップ間の音量ムラが出やすい。

**ゴール**

* LUFS をターゲット（例 `-23`) に\*\*±1dB以内\*\*で統一。

**実装イメージ**

* `loudnorm` を BGM 合成前に適用：

  ```
  -af "loudnorm=I=-23:TP=-2.0:LRA=11:print_format=json"
  ```
* メジャーメント値を `report.json` に保存して再現性確保。

---

## 15. プロファイル化（meta.video\_profile / speed\_profile）

**背景**
案件・環境ごとに規格値や速度重視設定を切り替えたい。

**ゴール**

* YAML の `meta.video_profile` / `meta.speed_profile` で**一括切替**。

**実装イメージ**

* `video_profile`：`resolution, fps, pix_fmt, profile, level`
* `speed_profile`：`fast|balanced|quality` → NVENC preset や `-b:v`/`-cq` を切替。
* 実行時に決定プロファイルをログ出力してトレース可能に。

---

### 補足：実装順のおすすめ

1. **01→02→03→04→05**（P0高速化の柱）
2. **07→08→09→10→11**（安定化メッシュ）
3. **12→13→14→15**（拡張でUX/品質UP）
