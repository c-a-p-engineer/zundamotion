# 📋 新タスクリスト（詳細版・統合版）

## P0（最優先：性能と安定性）

---

### 01. Video/Audio Params のデータクラス化

**詳細**
各フェーズで出力指定がバラけると仕様ズレが発生する。共通クラスで統一し、参照必須とする。

**ゴール**

* `VideoParams`, `AudioParams` を必ず経由してコマンド構築。
* `ffprobe` で全クリップが完全一致。
* copy concat のフォールバック率がゼロに近づく。

**実装イメージ**

```python
@dataclass
class VideoParams:
    width: int = 1920
    height: int = 1080
    fps: int = 30
    pix_fmt: str = "yuv420p"
    profile: str = "main"
```

* AudioParams も同様。
* ffmpeg コマンドは `CommandBuilder` を経由して生成。

---

### 02. 背景/挿入動画の Normalization キャッシュ

**詳細**
同じ素材を各シーンで毎回 `scale`/`fps`/`pix_fmt` 変換している。事前に正規化してキャッシュすれば再利用可能。

**ゴール**

* 同じ素材を2回目以降に使うとき、変換処理がスキップされる。
* プロジェクト2回目実行時の前処理時間がほぼゼロ。

**実装イメージ**

* 入力＋規格値でハッシュを作成。
* `cache/normalized_{hash}.mp4` を保存。
* 命中時は再利用。

---

### 03. NVENC 高速プリセット切替

**詳細**
現状 libx264（CPUエンコード）を使用。NVENC を使えば 1650 Max-Q でも 2〜3倍高速化が期待できる。

**ゴール**

* `--quality speed|balanced|quality` でプリセット切替可能。
* CPUエンコード比で 40〜60% 時間短縮。

**実装イメージ**

```sh
-c:v h264_nvenc -preset p7 -cq 30  # speed
-c:v h264_nvenc -preset p5 -cq 23  # balanced
-c:v h264_nvenc -preset p4 -cq 20  # quality
```

---

### 04. CUDA hwaccel 利用

**詳細**
フィルタ処理で CPU⇔GPU 間を往復している。`-hwaccel cuda` を明示し、転送を最小化。

**ゴール**

* ログで `hwupload_cuda` / `hwdownload` が最小回数に。
* CPU負荷が下がり、処理時間が 5〜15% 改善。

**実装イメージ**

```sh
ffmpeg -hwaccel cuda -hwaccel_output_format cuda ...
```

* GPU対応フィルタのみ CUDA 側で処理。

---

### 05. ジョブ並列（--jobs N）

**詳細**
シーンを直列処理している。ProcessPoolExecutor を使って並列化し、NVENCセッション数やVRAM使用を監視。

**ゴール**

* `--jobs 2` で総処理時間が 1.2〜1.6倍 短縮。
* セッション不足時はリトライして安全に完了。

**実装イメージ**

```python
with ProcessPoolExecutor(max_workers=N) as ex:
    ex.submit(run_ffmpeg, scene)
```

---

### 06. BGM統合処理

**詳細**
BGMを別フェーズで適用すると I/O が増える。可能なら Finalize に統合する。

**ゴール**

* 中間ファイル数が減り、全体時間が数％〜10％短縮。

**実装イメージ**

```sh
-filter_complex "[0:a][1:a]amix=inputs=2:duration=first[outa]"
```

* 単純ケースはワンパス化、複雑ケースは従来処理。

---

### 07. ベンチ/メトリクス出力

**詳細**
最適化の効果が見えにくい。実行時間・FFmpegの speed/fps を記録し、退行検知する。

**ゴール**

* `perf/YYYYMMDD.csv` が生成される。
* 前回比 +20% 以上で警告ログが出る。

**実装イメージ**

```csv
phase,start,end,duration,speed,fps
AudioPhase,00:00,00:09,9.48,—
```

---

## P1（中規模：負荷削減＆表現力強化）

---

### 01. 字幕の事前レンダ（PNG化）

**詳細**
`drawtext` はCPUフィルタ依存で重い。静的テキストを Pillow で事前生成し、`overlay` で合成すれば軽量化可能。

**ゴール**

* 同一シーンで `drawtext` 版より ≥1.4倍 高速。
* 縁取り・ボックス表現が正しく再現される。

**実装イメージ**

```python
from PIL import Image, ImageDraw, ImageFont
# テキストをレンダ → PNG → overlay
```

---

### 02. 立ち絵の事前スケール

**詳細**
毎フレーム `scale` をかけるのは無駄。事前に倍率別 PNG を生成してキャッシュする。

**ゴール**

* `scale` フィルタが消え、総処理時間が数％〜10％改善。

**実装イメージ**

* 立ち絵ごとに `scale-0.8.png`, `scale-1.0.png` を用意。
* クリップではそのまま `overlay`。

---

### 03. 静的レイヤーの事前合成＋静止レンダモード

**詳細**
背景＋立ち絵など「動かない組み合わせ」を毎フレーム overlay するのは無駄。事前に合成PNGにして `-loop 1`。

**ゴール**

* 静止シーンの生成が I/O 中心になり、極端に軽量化。

**実装イメージ**

```sh
convert bg.png char.png -composite static.png
ffmpeg -loop 1 -i static.png -t 5 -c:v libx264 ...
```

---

### 04. トランジションの部分再エンコード

**詳細**
全体を再エンコードせず、トランジション部分だけ再エンコードして前後は copy。

**ゴール**

* トランジションが多い作品でも総エンコード時間が線形増加しにくい。

**実装イメージ**

* `xfade` 区間のみ再エンコード。
* `concat demuxer` で前後を copy 結合。

---

### 05. トランジション結果キャッシュ

**詳細**
同じA→B＋同じ設定のトランジションは毎回再計算する必要がない。

**ゴール**

* 2回目以降はキャッシュを利用し再生成スキップ。

**実装イメージ**

* ハッシュ `(hash(A), hash(B), type, duration)` をキーに保存。

---

### 06. 複数キャラ表示＆レイアウトプリセット

**詳細**
1キャラ固定だと表現が貧弱。相対位置で複数キャラを配置できるようにする。

**ゴール**

* 9:16 / 1:1 でもレイアウト崩れなく2人以上を表示可能。

**実装イメージ**

* `left/right/center` → `x,y` を算出して `overlay`。

---

### 07. キャラ入退場アニメ（slide/fade/zoom）

**詳細**
静止表示だけでは単調。シンプルな動きをプリセット化する。

**ゴール**

* `enter: {type: slide_in, dur: 0.4s, from: left}` のように指定可能。
* 動きが破綻なく再生。

**実装イメージ**

* `slide` → `overlay=x='-w+t*speed'`
* `fade` → `fade=in:0:30`

---

### 08. シナリオ記法（二段構え）

**詳細**
初心者は簡易記法、上級者は詳細記法を使えるようにする。

**ゴール**

* どちらのYAMLでも等価な動画が生成される。

**実装イメージ**

* `script_loader` で省略記法を詳細記法へ展開。

---

### 09. SE相対トリガー

**詳細**
固定秒指定だとセリフ変更でズレる。行基準の相対指定を導入。

**ゴール**

* 台詞が変わっても SE が正しい位置で鳴る。

**実装イメージ**

```yaml
se:
  file: se.wav
  at: line_end - 0.2s
```

---

### 10. 素材リゾルバ

**詳細**
実行開始後に「ファイルなし」で落ちるのを防ぐ。

**ゴール**

* 実行前に不足ファイルが警告される。
* `--strict` で即エラー終了。

**実装イメージ**

* 実行前に `Path.exists()` チェック。
* 結果をまとめて警告出力。

---

## P2（拡張・利便性向上）

---

### 01. プロファイル切替（Speed/Balanced/Quality）

**詳細**
開発デバッグ用と本番出力用で求める速度・品質が違う。

**ゴール**

* `--profile speed` で低画質高速、`--profile quality` で高品質が選べる。

**実装イメージ**

* `profiles.yaml` を定義して fps/preset/crf を切り替え。

---

### 02. ワンパス filter\_complex ビルダー

**詳細**
フェーズごとに書き出すのではなく、可能な場合は一本の `filter_complex` で処理。

**ゴール**

* 中間ファイル数が減少。
* 1分サンプルで Finalize 所要が 1/2〜1/3。

**実装イメージ**

* `xfade/overlay/trim` を自動生成して filter\_complex にまとめる。

---

### 03. 表示UI/エディタ連携

**詳細**
YAML記述が煩雑なので、GUI補助やプレビューUIを追加する。

**ゴール**

* CLIに不慣れな人でも操作可能。

**実装イメージ**

* Streamlit/Gradio でプレビューUI。
* YAML編集 → 即時プレビュー。

---

### 04. メトリクスの可視化ダッシュボード

**詳細**
CSV出力されたベンチ結果をグラフ化して履歴管理。

**ゴール**

* 性能改善/退行を一目で確認できる。

**実装イメージ**

* Pythonで matplotlib / seaborn で自動プロット。
* `perf/summary.png` を生成。

---

### 05. 多言語TTS/字幕対応

**詳細**
英語や他言語でも自然に読めるよう辞書や音声設定を整備。

**ゴール**

* YAMLで `lang: en` 指定 → 英語字幕＋英語音声。

**実装イメージ**

* TTS設定に辞書ロード追加。
* drawtext/PNGレンダでフォント切替。
