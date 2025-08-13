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
- **JSONログ出力**: `--log-json`オプションを使用することで、機械可読なJSON形式でログを出力し、GUIや外部ツールとの連携を容易にします。
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
- **DevContainer対応**: VSCode DevContainerをサポートしており、どこでも一貫した開発環境を簡単に構築できます。

---

## 🧱 ファイル構成（概要）

```plaintext
.devcontainer/ # 開発環境設定
scripts/       # 台本ファイル
voices/        # 生成された音声・字幕
assets/        # 動画素材（背景、立ち絵など）
output/        # 最終出力動画
zundamotion/   # Pythonソースコード
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
  - id: intro_scene
    bg: "assets/bg/intro_bg.mp4"
    bgm:
      path: "assets/bgm/intro_music.wav" # このシーンのBGMファイルパス
      volume: 0.5                       # このシーンのBGM音量
      start_time: 2.0                   # このシーンのBGM開始時間
      fade_in_duration: 3.0             # このシーンのフェードイン時間
      fade_out_duration: 2.5            # このシーンのフェードアウト時間
    lines:
      - text: "これはイントロシーンです。"

  - id: main_content_scene
    bg: "assets/bg/main_bg.png"
    bgm:
      path: "assets/bgm/main_music.wav"
      volume: 0.4
    lines:
      - text: "メインコンテンツが始まります。"
```

- `path`: BGMファイルのパス。
- `volume`: BGMの音量（0.0から1.0の範囲）。
- `start_time`: BGMが動画のどの時点から開始するか（秒）。
- `fade_in_duration`: BGMのフェードインの長さ（秒）。
- `fade_out_duration`: BGMのフェードアウトの長さ（秒）。

---

## 🖼️ キャラクター画像の設定

キャラクター画像は、`assets/characters/` ディレクトリ以下に、キャラクター名と表情ごとに配置します。
ファイルパスは `assets/characters/{キャラクター名}/{表情}.png` の形式に従います。

**例:**
- ずんだもんの通常の表情: `assets/characters/zundamon/normal.png`
- ずんだもんのささやき表情: `assets/characters/zundamon/whisper.png`

もし指定された表情の画像ファイルが存在しない場合、システムは自動的に `assets/characters/{キャラクター名}/default.png` を探してフォールバックします。
そのため、各キャラクターには少なくとも `default.png` を用意しておくことを推奨します。

---

## 🗣 VOICEVOX エンジン

DevContainer起動時にDocker ComposeによってVOICEVOXエンジンが自動的に起動し、`voicevox:50021`で利用可能になります。
**重要**: ローカル環境からアクセスする場合は`localhost:50021`ではなく、必ず`voicevox:50021`を指定してください。

---

## 🧪 動作確認

Zundamotionは、YAML台本から最終的な動画ファイルを生成することを目的としています。ここでは、その基本的なワークフローを説明します。

#### 1. 音声と字幕の生成
`scripts/sample.yaml` に記述された台本を元に、VOICEVOXエンジンを利用して音声ファイルと字幕ファイル（SRT形式およびFFmpeg `drawtext`用JSON形式）を生成します。この際、台本のYAML構文、素材ファイルの存在、およびパラメータの有効範囲が自動的に検証されます。
```bash
python -m zundamotion.render_audio scripts/sample.yaml
```
実行後、`voices/` ディレクトリに以下のファイルが生成されます。
```plaintext
voices/
├── intro_1.drawtext.json
├── intro_1.srt
├── intro_1.wav
├── intro_2.drawtext.json
├── intro_2.srt
└── intro_2.wav
```

#### 2. 動画の生成
生成された音声と字幕、そして台本に指定された背景やキャラクター素材を組み合わせて`.mp4`動画を生成します。このプロセスでは、システムにインストールされたFFmpegコマンドが内部的に利用されます。実行中、CLIに進捗バーと残り時間が表示されます。
```bash
python -m zundamotion.main scripts/sample.yaml
```
機械可読なJSON形式でログを出力したい場合は、`--log-json`オプションを使用します。
```bash
python -m zundamotion.main scripts/sample.yaml --log-json
```
出力ファイルのパスを指定する場合は、`-o`または`--output`オプションを使用します。デフォルトの出力パスは `output/final.mp4` です。
```bash
python -m zundamotion.main scripts/sample.yaml -o output/my_video.mp4
```
中間ファイルを保持したい場合は、`--keep-intermediate`オプションを使用します。
```bash
python -m zundamotion.main scripts/sample.yaml --keep-intermediate
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

---

## 💡 今後の機能拡張予定

- [ ] **キャラクター表現の強化**: 表情差分や口パクの自動生成に対応し、キャラクターの表現力を向上させます。
- [ ] **高度な動画編集機能**: エフェクト、トランジションの指定を台本に含めることで、よりリッチな動画コンテンツを制作可能にします。

---

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
