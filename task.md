# 📋 Zundamotion 改善タスクリスト（詳細版）

---

## 🚀 P0（最優先：高速化と安定化）

---

### **タスク01. NVENC/ハードウェアエンコードの最適化**

* **背景**
  ログ上では `-c:v h264_nvenc` が使用されているが、Video ステージの所要時間が全体の **81.5%（153秒）** を占めており遅い。NVENC のプリセットやフィルタが最適化されていない可能性。
* **ゴール**
  Video ステージを **2〜4倍高速化** し、全体処理を 3分→1分台へ短縮。
* **実装イメージ**

  * NVENC プリセットを `p4` → `p5/p6` に調整（速度優先）。
  * GPUフィルタ（`scale_cuda`, `overlay_cuda`）が使える場合は切替。
  * フォールバック発生時の理由を `encoder_probe` ログに記録。
* **確認**

  * JSONLに `encoder_selected=h264_nvenc` が明示される。
  * 同じ動画で `VideoPhase.elapsed_ms` が短縮される。

---

### **タスク02. 素材正規化キャッシュ**

* **背景**
  同じ背景や立ち絵をシーンごとに `scale/fps/pix_fmt` 変換しており、無駄が大きい。ログには正規化失敗警告も多数。
* **ゴール**
  同一素材を2回目以降利用する際はキャッシュを再利用し、**再処理ゼロ** にする。
* **実装イメージ**

  * 入力パス＋規格値（fps/解像度/pix\_fmt/audio spec）でハッシュ生成。
  * `cache/normalized/{hash}.mp4` を作り、次回から再利用。
  * `normalize_cache` ログに `hit/miss` を出力。
* **確認**

  * 同じ素材を複数シーンに使った場合、2回目以降は `hit` になり `elapsed_ms` が短縮。
  * エラーが出ずに安定。

---

### **タスク03. Finalize の copy concat 化**

* **背景**
  Finalize フェーズに **19.3秒（10.2%）** かかっている。これはクリップ間の仕様不一致で再エンコードされているため。
* **ゴール**
  クリップ仕様が一致すれば `-f concat -c copy` を利用し、Finalize を数秒未満に短縮。
* **実装イメージ**

  * 全クリップの codec/profile/level/fps/pix\_fmt/audio を統一。
  * 一致すれば `-f concat -c copy`、不一致なら `-c:v libx264` 等で再エンコード。
  * JSONL に `finalize_mode=copy|reencode` と差分理由を出力。
* **確認**

  * Finalize `elapsed_ms` が 19s → 3s 未満に短縮。
  * ログで不一致理由（例: fps=30 vs 29.97）が明示される。

---

### **タスク04. 字幕自動改行強化**

* **背景**
  長文セリフで字幕が右端をはみ出すケースあり。ログにも wrap 設定未反映の痕跡。
* **ゴール**
  すべての字幕が枠内に収まり、行数やフォントサイズも安定。
* **実装イメージ**

  * `max_chars_per_line` を自動算出（解像度・フォントサイズ基準）。
  * wrap 結果をログに記録（行数、文字数）。
  * 2行以上になった場合の行間・縁取りを最適化。
* **確認**

  * 長文セリフで `subtitle_wrap: lines=2` がログに出る。
  * 出力動画で字幕が収まる。

---

### **タスク05. TTS/BGM の音量正規化**

* **背景**
  場面によって BGM が大きすぎてセリフが埋もれる。音量ログは現在なし。
* **ゴール**
  全編で一定ラウドネスを実現（台詞優先）。
* **実装イメージ**

  * 台詞：`loudnorm` で -23 LUFS。
  * BGM：-30〜-24 LUFS に制御。台詞中は `sidechaincompress` でダッキング。
  * `loudness_analyze` ログに測定LUFS・ゲインを出力。
* **確認**

  * JSONLで `measured_lufs`, `gain_applied_db` が記録される。
  * 出力動画でBGMと台詞が聞きやすい。

---

### **タスク06. 口パク同期補正**

* **背景**
  音声と口パクが1テンポずれる。現在ログなし。
* **ゴール**
  音声波形の立ち上がり±1フレームで口パク開始。
* **実装イメージ**

  * 音声波形解析（ゼロクロス/RMS/VAD）で無音区間を検出。
  * 開始点をオフセット補正し、`lip_sync: applied_offset_ms` をログ。
* **確認**

  * 出力動画でズレが消える。
  * ログに補正量が残る。

---

## 📊 P0（観測・ログ強化）

---

### **タスク07. ms精度のタイマーデコレータ**

* **背景**
  現在は `Duration: 0.00 seconds` と粗すぎる。
* **ゴール**
  すべてのフェーズ・サブステップに `elapsed_ms` を記録。
* **実装イメージ**

  * `time.perf_counter_ns()` を使った `@time_log_ms` デコレータを追加。
  * JSONLに `event="phase_end", elapsed_ms=xxxx` を出す。
* **確認**

  * 全サブステップに ms 単位の所要時間が残る。

---

### **タスク08. ログファイル出力（人間可読＋JSONL）**

* **背景**
  現状はコンソールのみ。実行後の解析に不便。
* **ゴール**
  毎回 `logs/YYYYMMDD/HHMMSS_runid/` に `zundamotion.log`（人間可読）と `zundamotion.jsonl`（機械可読）を出力。
* **実装イメージ**

  * Python logging に 2つのハンドラを設定。
  * CLIフラグ：`--log-dir --log-format --no-console`。
* **確認**

  * 実行後に2ファイルが生成される。
  * JSONL は jq で解析可能。

---

### **タスク09. FFmpegログの構造化**

* **背景**
  現在は「実行コマンド」だけで進捗や失敗要因が見えない。
* **ゴール**
  `start/progress/end` を JSONL に分けて記録、stderr も保存。
* **実装イメージ**

  * `event="ffmpeg_start"`：cmd, encoder, filters, threads。
  * `event="ffmpeg_progress"`：fps, speed, bitrate, time\_ms。
  * `event="ffmpeg_end"`：elapsed\_ms, exit\_code, out\_streams。
  * stderr を `ffmpeg.stderr.log` に保存。
* **確認**

  * 成功時に `fps/speed` の推移が残る。
  * 失敗時に exit\_code と stderr\_tail が記録される。

---

### **タスク10. エンコーダ/フィルタ選定ログ**

* **背景**
  NVENCやQSVの可否やフォールバック理由が不明。
* **ゴール**
  なぜCPU/GPUを選んだか説明可能。
* **実装イメージ**

  * `encoder_probe`：nvenc\_available, qsv\_available, force\_flags。
  * `encoder_selected`：video\_encoder, why。
* **確認**

  * JSONLに選定理由が明示される。

---

### **タスク11. キャッシュヒット/ミスログ**

* **背景**
  キャッシュが効いているか不明。
* **ゴール**
  素材ごとに hit/miss を可視化。
* **実装イメージ**

  * `normalize_cache: key=xxx, result=hit, elapsed_ms=...`。
* **確認**

  * 同素材2回目で hit が増える。

---

### **タスク12. Finalize 判定ログ**

* **背景**
  copy concat できたのか理由が不明。
* **ゴール**
  判定理由を可視化。
* **実装イメージ**

  * `finalize_mode=copy|reencode, mismatch={fps:[30,29.97]}`。
* **確認**

  * JSONLに理由が残る。

---

## 🛠️ P2（運用・拡張）

---

### **タスク13. 並列処理ワーカー制御**

* **背景**
  ログには `Using 0 specified threads` と出ているが、最適かは不明。
* **ゴール**
  CPU/GPU使用率を効率化。
* **実装イメージ**

  * `max_workers` を CPUコア数やGPU数から動的算出。
  * `scheduler_snapshot` に workers, queue\_len, cpu\_util, gpu\_util を出力。
* **確認**

  * CPU/GPU使用率が安定して高水準。

---

### **タスク14. 品質プリセット**

* **背景**
  用途により速度/品質の要求が異なる。
* **ゴール**
  `--quality fast|std|hq` で切替。
* **実装イメージ**

  * fast：NVENC p6, 高速/低ビット
  * std：既定値
  * hq：NVENC p3, 高ビット/画質重視
* **確認**

  * ログに `quality=fast` などが残り、処理時間/画質が変化。

---

### **タスク15. CIでログ成果物保存**

* **背景**
  失敗時に再現できないと調査困難。
* **ゴール**
  GitHub Actions で `logs/**` をアーティファクト保存。
* **実装イメージ**

  * `actions/upload-artifact` を設定。
* **確認**

  * CI失敗時にログをDLできる。

---

### **タスク16. タイムラインCSV/HTML生成ツール**

* **背景**
  JSONLログが膨大で追いづらい。
* **ゴール**
  1クリックでどの工程が遅いか可視化。
* **実装イメージ**

  * JSONLをパースし、`scene/clip/step/elapsed_ms` のCSV/HTML生成。
  * HTMLでは長い処理を赤でハイライト。
* **確認**

  * 出力を開けば即ボトルネックが見える。
