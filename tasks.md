# 📋 Zundamotion ログ解析後タスクリスト

## P0（必須・最優先）

### 01. **libmp3lameを確実に有効化**

* **背景**: ログに `libmp3lame encoder not found` が多数。すべて PCM にフォールバックし、中間ファイルが肥大化＆処理効率が悪化。
* **ゴール**: ffmpegの `-encoders` に `libmp3lame` が表示され、音声は `pcm_s16le` ではなく `libmp3lame` が使われる。
* **実装イメージ**:

  * DockerfileでPATHとLD\_LIBRARY\_PATHを整理し、`ffmpeg` が /opt/ffmpeg のビルドを指すようにする。
  * ビルド時に `RUN ffmpeg -hide_banner -encoders | grep -i libmp3lame` を実行し、存在を確認する。
  * コード側の音声エンコード指定を `-c:a libmp3lame -b:a 192k -ar 48000 -ac 2` に統一。
* **確認方法**:

  * コンテナ内で `ffmpeg -encoders | grep -i libmp3lame` を実行し、出力を確認。
  * 動画生成ログに「libmp3lame encoder not found」が出ないこと。

---

### 02. **FinalizePhase の async バグ修正**

* **背景**: ログに `NoneType can't be used in 'await' expression` → 成功しているのに再エンコードへフォールバック。不要な処理が走り数十秒ロス。
* **ゴール**: `-c copy concat` 成功時は即returnし、再エンコードへ落ちない。
* **実装イメージ**:

  * `concat_copy()` の戻り値を必ず bool / Task に統一。
  * 成功時に `return True` を返して処理終了。
  * `await None` が発生しないよう修正。
* **確認方法**:

  * FinalizePhaseのログに「Falling back to re-encode」が出ないこと。
  * 処理時間が数十秒短縮される。

---

### 03. **NVENCスモークテストの冗長実行を抑制**

* **背景**: VideoPhase内で毎回 `Performing a quick smoke test for h264_nvenc...` が走っている。重複して無駄。
* **ゴール**: パイプライン全体で1回だけスモークテストを実行。以降はキャッシュされた結果を利用。
* **実装イメージ**:

  * モジュールスコープの変数 `nvenc_checked = False` を導入。
  * 初回だけテスト → 結果を保持。2回目以降はスキップ。
* **確認方法**:

  * ログで「smoke test」が最初の1回だけ表示されること。

---

## P1（高速化）

### 04. **字幕クリップ生成の高速化**

* **背景**: VideoPhaseで170秒。字幕PNG→動画焼き込みが直列で重い。
* **ゴール**: 字幕付きクリップ生成が並列処理され、処理時間が短縮。
* **実装イメージ**:

  * `ProcessPoolExecutor` でPNG生成を並列化。
  * overlay合成もまとめ処理を検討（drawtext/ASSの利用など）。
* **確認方法**:

  * 同じ素材で再生成したときに処理時間が半減する。

---

### 05. **キャッシュ有効化のデフォルト化**

* **背景**: `--no-cache` で毎回生成 → 無駄。
* **ゴール**: デフォルトではキャッシュ利用。差分だけ処理。
* **実装イメージ**:

  * `--no-cache` はデバッグ時のみ使用。
  * normalized素材や音声はハッシュ再利用。
* **確認方法**:

  * 2回目以降の実行が数十秒以内で完了する。

---

## P2（将来的改善）

### 06. **音声エンコーダの自動フォールバック**

* **背景**: libmp3lameが無い環境でPCMに落ちてしまう。
* **ゴール**: 環境に合わせて `libmp3lame` / `aac` を自動切替。
* **実装イメージ**:

  * ffmpeg -encoders の出力をチェック。
  * libmp3lameが無ければ `aac` に切り替え。
* **確認方法**:

  * どの環境でも `pcm_s16le` ではなく圧縮音声で出力される。

---
