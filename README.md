# 🎬 Zundamotion: YAML台本から動画を自動生成する開発環境

Zundamotionは、VOICEVOXによる高品質な音声合成とFFmpegを用いた映像合成を組み合わせ、YAML形式の台本から`.mp4`動画を自動生成する強力な開発環境です。動画制作のワークフローを効率化し、コンテンツ作成を加速します。

---

## 🚀 機能概要

- **VOICEVOX連携**: Dockerを利用したVOICEVOXエンジンとの連携により、高品質な音声合成を実現します。
- **FFmpegによる動画合成**: 背景、キャラクター、字幕、音声をFFmpegでシームレスに統合し、プロフェッショナルな動画を生成します。
- **BGM挿入（フェードイン・フェードアウト対応）**: シーン単位または動画全体のBGMを、フェードイン/アウト、音量、開始位置を指定して挿入できます。
- **YAMLベースの台本**: 直感的で記述しやすいYAML形式の台本から、音声と字幕を自動生成します。
- **多様な字幕出力**: SRT形式とFFmpeg `drawtext`用のJSON形式字幕ファイルの両方を出力し、柔軟な動画編集に対応します。
- **堅牢なバリデーション**: 実行前にYAML構文、参照される素材ファイル（背景、BGM、キャラクター画像など）の存在、および音声パラメータ（速度、ピッチ、音量など）の有効範囲を自動でチェックします。エラー発生時には、具体的なエラーメッセージと該当する行番号・列番号が表示され、問題の特定と修正を支援します。
- **進捗バー＋ETA表示**: CLI上で動画生成の全体進捗率と残り時間をリアルタイムで表示し、ユーザー体験を向上させます。
- **ファイルログ出力**: すべてのログは `./logs/YYYYMMDD_HHMMS_MS.log` の形式でファイルに出力されます。
- **JSONログ出力**: `--log-json`オプションを使用することで、機械可読なJSON形式でログをコンソールに出力し、GUIや外部ツールとの連携を容易にします。
- **KVログ出力**: `--log-kv`オプションを使用することで、人間が読みやすいKey-Value形式でログをコンソールに出力し、ログの解析とボトルネックの特定を容易にします。
- **並列レンダリングとハードウェアエンコードの自動検出**: CPUコア数やGPU（NVENC/VAAPI/VideoToolbox）を検出し、最適なジョブ数を自動設定します。ハードウェアエンコードが利用可能な場合は自動的に活用し、失敗時はソフトウェアにフォールバックします。
- **キャラクター配置の柔軟性**: キャラクターの表示位置をX/Y座標で指定できるだけでなく、スケーリング（拡大縮小）やアンカーポイント（画像の基準点）を設定することで、より細かくキャラクターの配置を制御できます。
  - `scale`: キャラクター画像の拡大縮小率を指定します（例: `0.8` で80%のサイズ）。
  - `anchor`: キャラクター画像を配置する際の基準点（アンカーポイント）を指定します。以下のいずれかの値を設定できます。
    - `top_left`: 画像の左上を基準点とします。
    - `top_center`: 画像の上辺中央を基準点とします。
    - `top_right`: 画像の右上を基準点とします。
    - `middle_left`: 画像の左辺中央を基準点とします。
    - `middle_center`: 画像の中心を基準点とします。
    - `middle_right`: 画像の右辺中央を基準点とします。
    - `bottom_left`: 画像の左下を基準点とします。
    - `bottom_center`: 画像の底辺中央を基準点とします（デフォルト）。
    - `bottom_right`: 画像の右下を基準点とします。
  - `position`: `x`, `y` 座標は、指定された `anchor` からのオフセットとして機能します。例えば、`anchor: bottom_center` で `position: {x: 0, y: 0}` の場合、キャラクターの底辺中央が背景の底辺中央に配置されます。`position: {x: 100, y: -50}` の場合、底辺中央から右に100ピクセル、上に50ピクセル移動します。

- **ゆっくり的 口パク/目パチ（最小版）**: 音声の音量（RMS）に基づき、`mouth={close,half,open}` を切替。目パチは2–5秒間隔でランダムに閉じるスケジュール。差分PNGを `overlay:enable=between(t,...)` で重畳します（アセットが無い場合は自動で無効化）。

以下は、台本ファイルでのキャラクター設定の記述例です。

```yaml
lines:
  - text: "これから自己紹介の動画をはじめるのだ。"
    speaker_name: "zundamon"
    characters: # キャラクター設定リスト
      - name: "zundamon"
        expression: "whisper"
        position: {"x": "0", "y": "0"}
        scale: 0.8
        anchor: "bottom_center"
        visible: true
```

- **DevContainer対応**: VSCode DevContainerをサポートしており、どこでも一貫した開発環境を簡単に構築できます。
- **外部設定ファイル**: `config.yaml`を通じて、キャッシュディレクトリや動画拡張子などのシステム設定を柔軟に変更できます。
- **タイムライン出力**: 動画の各シーンやセリフの開始時刻を記録し、YouTubeのチャプターなどに利用できるタイムラインファイルを自動生成します。出力形式はMarkdown (`.md`)、CSV (`.csv`)、またはその両方を選択できます。
- **字幕ファイル出力**: 焼き込み字幕とは別に、`.srt`または`.ass`形式の独立した字幕ファイルを動画と同時に出力します。これにより、YouTubeへのアップロードや、他言語への翻訳作業が容易になります。
- **キャラクターごとのデフォルト設定**: 台本ファイル内でキャラクターごとのデフォルト設定（話者ID、ピッチ、速度など）を定義できます。これにより、セリフごとの記述を簡潔にし、台本の可読性を向上させます。設定は「セリフごとの指定 > キャラクターごとのデフォルト > グローバルなデフォルト」の順に優先されます。

---

## 🛠️ 技術スタック

- **言語**: Python 3.x
- **主要ライブラリ**:
    - `PyYAML`: YAML設定ファイルの読み込みと解析
    - `requests`: VOICEVOX APIとのHTTP通信
    - `httpx` / `tenacity`: VOICEVOX API呼び出しの非同期通信とリトライ制御
    - `pysubs2`: 字幕ファイルの生成
    - `Pillow`: 画像処理・背景透過
- **外部ツール**:
    - `FFmpeg`: 動画および音声の処理、結合、レンダリング
    - `VOICEVOX`: 音声合成エンジン (ローカルで実行されている必要があります)

---

## 🧱 プロジェクト構造

```
.
├── assets/                 # 動画生成に使用されるアセット（背景動画、キャラクター画像、BGM、効果音）
│   ├── bg/                 # 背景動画/画像
│   ├── bgm/                # 背景音楽
│   ├── characters/         # キャラクター画像
│   └── se/                 # 効果音
├── cache/                  # 生成された中間ファイルやキャッシュデータ
├── output/                 # 最終的な出力動画
├── scripts/                # サンプルスクリプトや設定ファイル
│   └── sample.yaml         # サンプルスクリプト
├── zundamotion/            # メインアプリケーションのソースコード
│   ├── __init__.py
│   ├── cache.py            # キャッシュ管理 (`CacheManager` クラス)
│   ├── exceptions.py       # カスタム例外定義
│   ├── main.py             # エントリーポイント (`main` 関数)
│   ├── pipeline.py         # 動画生成パイプラインの定義 (`GenerationPipeline` クラス, `run_generation` 関数)
│   ├── components/         # パイプラインの各ステップで使用されるコンポーネント
│   │   ├── audio.py        # 音声生成 (`AudioGenerator` クラス)
│   │   ├── script_loader.py# スクリプトと設定の読み込み、マージ、検証
│   │   ├── subtitle.py     # 字幕生成 (`SubtitleGenerator` クラス)
│   │   ├── video.py        # 動画レンダリング (`VideoRenderer` クラス)
│   │   └── voicevox_client.py # VOICEVOX APIクライアント (`generate_voice` 関数)
│   ├── pipeline_phases/    # 動画生成パイプラインの各フェーズ
│   │   ├── audio_phase.py  # 音声生成フェーズ (`AudioPhase` クラス)
│   │   ├── bgm_phase.py    # BGM追加フェーズ (`BGMPhase` クラス)
│   │   ├── finalize_phase.py # 最終化フェーズ (`FinalizePhase` クラス)
│   │   └── video_phase.py  # 動画生成フェーズ (`VideoPhase` クラス)
│   ├── reporting/          # レポート生成関連
│   │   └── voice_report_generator.py # VOICEVOX使用情報レポート生成
│   ├── templates/          # 設定テンプレート
│   │   └── config.yaml     # デフォルト設定テンプレート
│   └── utils/              # ユーティリティ関数
│       ├── ffmpeg_utils.py # FFmpeg関連ユーティリティ
│       └── logger.py       # ロギングユーティリティ
└── requirements.txt        # Pythonの依存関係
```

---

## 📦 セットアップ手順

### 1. 必要ツールのインストール
- [Docker](https://www.docker.com/get-started/)
- [FFmpeg](https://ffmpeg.org/download.html) (システムにインストールされている必要があります)
- [VS Code](https://code.visualstudio.com/)
- [Remote - Containers 拡張機能](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers) (VS Code)

### 2. リポジトリのクローン
```bash
git clone https://github.com/c-a-p-engineer/zundamotion.git
cd zundamotion
```

### 3. DevContainerの起動
VS Codeでプロジェクトを開き、プロンプトが表示されたら「Reopen in Container」を選択します。これにより、必要な依存関係が自動的にインストールされ、開発環境が構築されます。

---

## 🎵 BGM設定

BGMは、グローバル設定またはシーンごとに設定できます。シーンごとの設定はグローバル設定を上書きします。

### グローバルBGM設定 (config.yaml)

`zundamotion/templates/config.yaml` またはカスタム設定ファイルで、動画全体に適用されるデフォルトのBGMを設定できます。

```yaml
# BGM settings
bgm:
  path: "assets/bgm/default_bgm.wav" # デフォルトのBGMファイルパス
  volume: 0.3                       # デフォルトのBGM音量 (0.0-1.0)
  start_time: 0.0                   # デフォルトのBGM開始時間 (秒)
  fade_in_duration: 1.0             # デフォルトのフェードイン時間 (秒)
  fade_out_duration: 1.0            # デフォルトのフェードアウト時間 (秒)
```

### シーンごとのBGM設定 (scripts/your_script.yaml)

各シーンで個別のBGMを設定できます。これにより、シーンごとに異なる雰囲気を作り出すことが可能です。

```yaml
scenes:
  - id: intro
    bg: "assets/bg/sample_video.mp4"    # シーン背景 (動画ファイル)
    bgm:                                # BGM設定
      path: "assets/bgm/intro.wav"      # BGMファイルパス
      volume: 0.1                       # BGM音量 (0.0-1.0, オプション)
      fade_in_duration: 2.0             # フェードインの長さ (秒, オプション)
      fade_out_duration: 1.5            # フェードアウトの長さ (秒, オプション)
    lines:
      - text: "こんにちは！ずんだもんです。"
```

- `path`: BGMファイルのパス。
- `volume`: BGMの音量（0.0から1.0の範囲）。
- `start_time`: BGMが動画のどの時点から開始するか（秒）。
- `fade_in_duration`: BGMのフェードインの長さ（秒）。
- `fade_out_duration`: BGMのフェードアウトの長さ（秒）。

---

## 🔊 効果音設定

効果音は、各セリフ（`line`）に紐付けて設定できます。これにより、セリフの再生と同時に、またはセリフの開始からの相対的な時間で効果音を挿入することが可能です。

```yaml
lines:
  - text: "こんにちは！ずんだもんです。"
    speaker_id: 3
    sound_effects: # セリフと同時に再生する効果音
      - path: "assets/se/rap_fanfare.mp3"
        start_time: 3.0 # セリフ開始から3.0秒後に再生
        volume: 0.5

  - text: "" # セリフなしで効果音のみを再生する場合
    sound_effects:
      - path: "assets/se/rap_fanfare.mp3"
        start_time: 0.0 # このlineが開始されると同時に再生
        volume: 0.7
```

- `path`: 効果音ファイルのパス。
- `start_time`: 効果音がセリフの開始から何秒後に再生を開始するかを指定します。デフォルトは `0.0` で、セリフと同時に再生されます。
- `volume`: 効果音の音量（0.0から1.0の範囲）。デフォルトは `1.0` です。

---

### AIベースでの背景除去（rembg）

写真や複雑な背景では、AIベースの除去が高精度です。

- ファイル: `remove_bg_ai.py`
- 依存関係: `pip install rembg`（GPU利用時は `onnxruntime-gpu` を別途インストール）

使い方:

```bash
# 一括処理（デフォルトモデル: isnet-general-use）
python remove_bg_ai.py --input ./path/to/input_images --output ./path/to/output_png

# サブフォルダも含めて処理
python remove_bg_ai.py --input ./in --output ./out --recursive

# モデル切替（アニメ調に強い）
python remove_bg_ai.py --input ./in --output ./out --model isnet-anime

# 現在のONNX Runtimeプロバイダを確認
python remove_bg_ai.py --input ./in --output ./out --show-providers

# CPU/GPUを強制（GPUが不可ならCPUにフォールバック）
python remove_bg_ai.py --input ./in --output ./out --force-cpu
python remove_bg_ai.py --input ./in --output ./out --force-gpu
```

備考:
- 出力は常に透過PNGです。
- GPU環境では `pip install onnxruntime-gpu` で高速化できます。


## 🎬 画像・動画の挿入

セリフ中に、指定した画像や動画を画面に挿入することができます。これにより、参考資料を提示したり、視覚的なエフェクトを追加したりすることが可能です。
挿入動画では `chroma_key` で特定色を透明化するクロマキー合成が行えます（デフォルトは黒）。

```yaml
lines:
  - text: "（画像を右下に小さく表示するのだ）"
    speaker_id: 3
    insert:
      path: "assets/bg/room.png"      # 挿入する画像・動画のパス
      duration: 3.0                   # 表示時間 (秒, 画像の場合のみ有効)
      scale: 0.3                      # 拡大縮小率 (オプション)
      anchor: "bottom_right"          # アンカーポイント (オプション)
      position: {"x": "-20", "y": "-20"} # 位置オフセット (オプション)

  - text: "（桜の動画を重ねるのだ！）"
    speaker_id: 3
    insert:
      path: "assets/overlay/sakura_bg_black.mp4" # 挿入する動画
      chroma_key: "#000000"        # 指定色を透過させる
      scale: 0.8
      anchor: "middle_center"
      position: {"x": "20", "y": "20"}
      volume: 0.2                     # 挿入動画の音量 (オプション)
```

- `path`: 挿入する画像または動画ファイルのパス。
- `duration`: 画像を表示する時間（秒）。動画の場合は無視されます。
- `scale`: 画像・動画の拡大縮小率。
- `anchor`: 配置の基準点。キャラクター配置と同様のアンカーポイントが利用可能です。
- `position`: アンカーポイントからの相対的な位置オフセット（x, y座標）。
- `volume`: 挿入する動画の音量（0.0から1.0の範囲）。画像の場合は無視されます。
- `chroma_key`: 挿入動画で透過させる色。省略時は無効で、`true` を指定すると黒が透過色になります。

---

## 🖼️ キャラクター画像の設定

キャラクター画像は、`assets/characters/` ディレクトリ以下に、キャラクター名と表情ごとに配置します。
ファイルパスは `assets/characters/{キャラクター名}/{表情}.png` の形式に従います。

**例:**
- ずんだもんの通常の表情: `assets/characters/zundamon/normal.png`
- ずんだもんのささやき表情: `assets/characters/zundamon/whisper.png`

もし指定された表情の画像ファイルが存在しない場合、システムは自動的に `assets/characters/{キャラクター名}/default.png` を探してフォールバックします。
そのため、各キャラクターには少なくとも `default.png` を用意しておくことを推奨します。

### 口パク/目パチ用の差分PNG（任意）

「ゆっくり」的な最小アニメーションに対応するため、以下の差分PNGを用意すると、口パク・目パチが自動で適用されます（存在しない場合は無効化）。

- 口パク: `assets/characters/<name>/mouth/{close,half,open}.png`
- 目パチ: `assets/characters/<name>/eyes/{open,close}.png`

差分PNGは、元の立ち絵と同一キャンバスサイズ・座標系で作成してください（透明背景の「差分」レイヤ）。キャラクターの拡大率・配置に追従し、音声に同期して `half/open` を切替、`close` はベースとして常時合成、`half`/`open` が上から被さる構成です。目は `open` を常時合成し、`close` を点滅区間のみ上書きします。

設定（`config.yaml` またはスクリプトの `video:` セクション）

```yaml
video:
  fps: 30
  face_anim:
    mouth_fps: 15           # 口パク判定のサンプリングFPS
    mouth_thr_half: 0.2     # 半開き閾値（RMSのmax比）
    mouth_thr_open: 0.5     # 全開閾値（RMSのmax比）
    blink_min_interval: 2.0 # 目パチの最小間隔（秒）
    blink_max_interval: 5.0 # 目パチの最大間隔（秒）
    blink_close_frames: 2   # 瞬きの閉眼フレーム数（動画FPS基準）
```

対象キャラクターは、各セリフの `speaker_name`（未指定時は最初の `visible: true` のキャラ）です。

#### 差分PNG配置ガイド（具体例）

- 準備するファイル（ずんだもんの例）:
  - `assets/characters/zundamon/default.png`（既存の立ち絵）
  - `assets/characters/zundamon/mouth/close.png`
  - `assets/characters/zundamon/mouth/half.png`
  - `assets/characters/zundamon/mouth/open.png`
  - `assets/characters/zundamon/eyes/open.png`
  - `assets/characters/zundamon/eyes/close.png`
- ファイル仕様:
  - キャンバス: 立ち絵 `default.png` と同じ幅・高さ。
  - 背景: 透明（PNGのアルファ）。
  - 描画範囲: 口/目の差分部分のみ描画し、それ以外は完全に透明にします。
  - 位置合わせ: `default.png` に対してピクセル単位で一致させてください（同一座標系）。
  - ネーミング: 上記の固定ファイル名のみを参照します。大文字/拡張子違いは不可。
- 動作メモ:
  - 口は `close` が常時、`half`/`open` は音量しきい値を満たす時間だけ重なります。
  - 目は `open` が常時、`close` はランダムな点滅時間だけ重なります。
  - 差分PNGが存在しない場合は、その要素（口 or 目）は自動的に無効化されます（既存の静止立ち絵のみ）。

---

## 🗣 VOICEVOX エンジン

DevContainer起動時にDocker ComposeによってVOICEVOXエンジンが自動的に起動し、コンテナ内からは `voicevox:50021` で利用可能です。
ローカル環境（コンテナ外）からアクセスする場合は、通常 `http://127.0.0.1:50021` を使用してください。
必要に応じて環境変数 `VOICEVOX_URL` で接続先を上書きできます（例: DevContainer内では `http://voicevox:50021`）。

---

## 🧪 動作確認

Zundamotionは、YAML台本から最終的な動画ファイルを生成することを目的としています。ここでは、その基本的なワークフローを説明します。

#### 1. 動画の生成
台本に指定された情報（音声、字幕、背景、キャラクター素材など）を元に、`.mp4`動画を生成します。このプロセスでは、VOICEVOXによる音声合成、字幕生成、FFmpegによる動画合成がすべて一括で行われます。実行中、CLIに進捗バーと残り時間が表示されます。
```bash
python -m zundamotion.main scripts/sample.yaml
```
機械可読なJSON形式でログを出力したい場合は、`--log-json`オプションを使用します。
```bash
python -m zundamotion.main scripts/sample.yaml --log-json
```
人間が読みやすいKey-Value形式でログを出力したい場合は、`--log-kv`オプションを使用します。
```bash
python -m zundamotion.main scripts/sample.yaml --log-kv
```
出力ファイルのパスを指定する場合は、`-o`または`--output`オプションを使用します。デフォルトの出力パスは `output/final.mp4` です。
```bash
python -m zundamotion.main scripts/sample.yaml -o output/my_video.mp4
```
キャッシュを無効にしてすべての中間ファイルを再生成したい場合は、`--no-cache`オプションを使用します。
```bash
python -m zundamotion.main scripts/sample.yaml --no-cache
```
すべての中間ファイルを再生成し、キャッシュを更新したい場合は、`--cache-refresh`オプションを使用します。
```bash
python -m zundamotion.main scripts/sample.yaml --cache-refresh
```

並列レンダリングジョブ数を指定したい場合は、`--jobs`オプションを使用します。`auto`を指定するとCPUコア数を自動検出し、最適なジョブ数を設定します。
```bash
python -m zundamotion.main scripts/sample.yaml --jobs auto
```
特定のジョブ数を指定することも可能です（例: 4コアを使用する場合）。
```bash
python -m zundamotion.main scripts/sample.yaml --jobs 4
```

ハードウェアエンコーダーを指定したい場合は、`--hw-encoder`オプションを使用します。`auto`を指定すると利用可能な場合にGPUを使用し、`gpu`はGPUを強制（CPUフォールバックあり）、`cpu`はCPUを強制します。
```bash
python -m zundamotion.main scripts/sample.yaml --hw-encoder gpu
```

エンコード品質を指定したい場合は、`--quality`オプションを使用します。`speed`, `balanced`, `quality`から選択できます。
```bash
python -m zundamotion.main scripts/sample.yaml --quality quality
```

最終的な連結を`-c copy`のみに強制し、再エンコードが必要な場合は失敗させたい場合は、`--final-copy-only`オプションを使用します。
```bash
python -m zundamotion.main scripts/sample.yaml --final-copy-only
```

タイムライン出力を有効にするには、`--timeline`オプションを使用します。フォーマットを指定しない場合、デフォルトでMarkdown形式で出力されます。
```bash
python -m zundamotion.main scripts/sample.yaml --timeline
```
出力フォーマットをCSVに指定する場合：
```bash
python -m zundamotion.main scripts/sample.yaml --timeline csv
```
両方のフォーマットで出力する場合：
```bash
python -m zundamotion.main scripts/sample.yaml --timeline both
```
タイムライン出力を無効にするには、`--no-timeline`オプションを使用します。
```bash
python -m zundamotion.main scripts/sample.yaml --no-timeline
```

字幕ファイルの出力も同様に制御できます。
```bash
# SRT形式で字幕ファイルを出力（デフォルト）
python -m zundamotion.main scripts/sample.yaml --subtitle-file

# ASS形式で字幕ファイルを出力
python -m zundamotion.main scripts/sample.yaml --subtitle-file ass

# 字幕ファイル出力を無効化
python -m zundamotion.main scripts/sample.yaml --no-subtitle-file
```

キャラクターごとのデフォルト設定は、台本ファイル内の`defaults`セクションで定義します。音声設定だけでなく、字幕の色などもキャラクターに紐付けて設定できます。

```yaml
defaults:
  characters:
    zundamon:
      speaker_id: 3
      pitch: 0.1
      speed: 1.1
      subtitle:
        font_color: "#90EE90"
        stroke_color: "white"
    metan:
      speaker_id: 6
      speed: 0.95
      subtitle:
        font_color: "#E6E6FA"
        stroke_color: "black"
```

これらの設定は、`config.yaml`でも指定可能です。

```yaml
system:
  timeline:
    enabled: true
    format: "md" # "md", "csv", "both", "none" から選択
  subtitle_file:
    enabled: true
    format: "srt" # "srt", "ass", "both", "none" から選択
```

---

## 💡 今後の機能拡張予定

- [ ] **キャラクター表現の強化**: 表情差分や口パクの自動生成に対応し、キャラクターの表現力を向上させます。
- [x] **シーン間トランジション**: YAMLの `scene.transition` を適用（映像 xfade ＋ 音声 acrossfade）。

以下は、台本ファイルでのトランジション設定の記述例です。

```yaml
scenes:
  - id: intro
    bg: "assets/bg/sample_video.mp4"
    lines:
      - text: "最初のシーンです。"
    transition: # このシーンの後に適用されるトランジション
      type: "fade" # トランジションの種類 (例: fade, dissolve, wipeleftなど)
      duration: 1.0 # トランジションの期間 (秒)

  - id: topic
    bg: "assets/bg/street.png"
    lines:
      - text: "次のシーンです。"
```

---

## ⚙️ 最適化オプション（config.yaml）

動画背景で静的オーバーレイのないシーンにおけるベース映像生成の最適化を制御できます。

```yaml
video:
  # 静的オーバーレイが無いシーンでベース映像を生成する最小行数
  # N未満ならベースを作らず、背景を一度だけ正規化して各行へ伝搬（重複スケール回避）
  scene_base_min_lines: 6
```

挙動:
- 静的オーバーレイが1つ以上ある場合は常にベース映像を生成（静的レイヤを事前合成）。
- 静的オーバーレイが無い場合、行数が `scene_base_min_lines` 未満ならベース生成をスキップし、背景動画を一度だけ正規化して各行の合成に使います（`normalized=True`/`pre_scaled=True` 伝搬）。
- 行数がしきい値以上なら、再利用効率の観点からベース映像を生成します。

---

## 🚀 パフォーマンスと運用（上級者向け）

- GPUオーバーレイ方針: 字幕はPNG（RGBA）で合成するため、既定ではCPU overlayを使用します。RGBAを含まない場合はGPU（overlay_cuda/scale_cuda or scale_npp）を利用します。実験的にGPUで字幕を重ねたい場合は設定で `video.gpu_overlay_experimental: true` を有効化してください。
- CUDA診断とフォールバック: CUDAフィルタのスモーク/実行時に失敗した場合、初回のみ `ffmpeg -buildconf` / `ffmpeg -filters` / `nvidia-smi -L` / `nvcc --version` をINFOで自動出力し、CPUフィルタにフォールバックします。`scale_cuda` が無い環境では自動で `scale_npp` を使用します。
- スレッドとプロファイル:
  - `FFMPEG_PROFILE_MODE=1` で `-benchmark -stats` を付与し、FFmpegの所要・スループットを収集できます。
  - `FFMPEG_THREADS` で `-threads` を明示上書き可能。
  - CPUフィルタ経路では `-filter_threads`/`-filter_complex_threads` を保守的にキャップ（既定=4）。`FFMPEG_FILTER_THREADS_CAP`/`FFMPEG_FILTER_COMPLEX_THREADS_CAP` で上限を調整できます。
- 自動チューニング（初期クリップ計測）:
  - `video.auto_tune: true` で初回数クリップ（既定4）を計測し、CPU overlay が支配的なら `filter_threads` の上限と `clip_workers` を保守的に調整します。
  - `video.profile_first_clips: 4` で計測クリップ数を変更可能。
  - CPU overlay が支配的な場合は、フィルタ経路をCPUに統一（`set_hw_filter_mode('cpu')`）し、以降の安定性と一貫性を優先します（NVENCエンコードは継続）。
- 一時ディレクトリ（RAMディスク）: `USE_RAMDISK=1`（既定）で空き容量が十分なら `/dev/shm` を一時ディレクトリに使用し、I/Oを高速化します。
- 正規化の再実行抑止: 正規化出力に `<name>.meta.json` を隣接保存し、同一 `target_spec` の入力は再正規化をスキップします。
- no-cache時の重複抑止: `--no-cache` でも同一キー生成はプロセス内でin-flight集約し、同一ラン内の重複生成を避けます。生成物は `temp_dir` のEphemeralとして再利用されます。
- concat最適化: `-f concat -c copy` のリストファイルは出力ディレクトリに配置し、I/O局所性を改善しています。

設定例（GPUで字幕のGPUオーバーレイを試す）:
```yaml
video:
  gpu_overlay_experimental: true
  auto_tune: true
  profile_first_clips: 4
```


## ⚠️ ライセンスと利用ガイドライン

本プロジェクトはMITライセンスの下で公開されています。詳細については[LICENSE](LICENSE)ファイルをご確認ください。
VOICEVOXの利用に関しては、キャラクターごとに商用利用の可否が異なります。必ず[VOICEVOX公式サイトの利用規約](https://voicevox.hiroshiba.jp/)をご確認ください。

---

## 🧑‍💻 制作者

- c_a_p_engineer ([X (旧Twitter)](https://x.com/c_a_p_engineer))

---

## ✅ よくあるエラーと対処法

| エラー                                           | 対処法                                                   |
| --------------------------------------------- | ----------------------------------------------------- |
| `ModuleNotFoundError: No module named 'yaml'` | `pip install -r requirements.txt`                     |
| `ffprobe not found`                           | Dockerfile に `apt install ffmpeg` を追加                 |
| `No module named 'zundamotion'`               | `PYTHONPATH=.` を指定 or `python -m zundamotion.xxx` で実行 |
| `Validation Error: ...`                       | YAML台本の構文、素材パス、またはパラメータ値を確認してください。エラーメッセージに行番号と列番号が示されます。 |
