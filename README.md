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

## 🎬 画像・動画の挿入

セリフ中に、指定した画像や動画を画面に挿入することができます。これにより、参考資料を提示したり、視覚的なエフェクトを追加したりすることが可能です。

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

  - text: "（動画を再生するのだ！）"
    speaker_id: 3
    insert:
      path: "assets/bg/countdown.mp4" # 挿入する動画
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

#### 1. 動画の生成
台本に指定された情報（音声、字幕、背景、キャラクター素材など）を元に、`.mp4`動画を生成します。このプロセスでは、VOICEVOXによる音声合成、字幕生成、FFmpegによる動画合成がすべて一括で行われます。実行中、CLIに進捗バーと残り時間が表示されます。
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

キャラクターごとのデフォルト設定は、台本ファイル内の`defaults`セクションで定義します。

```yaml
defaults:
  characters:
    zundamon:
      speaker_id: 3
      pitch: 0.1
      speed: 1.1
    metan:
      speaker_id: 6
      speed: 0.95
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
- [ ] **高度な動画編集機能**: エフェクト、トランジションの指定を台本に含めることで、よりリッチな動画コンテンツを制作可能にします。
- [x] **シーン間のトランジション効果**: シーンとシーンの間にフェードイン/アウト、クロスフェード、ワイプなどの切り替え効果を適用できるようにする。
  - **実装**: `scene` 定義に `transition` プロパティを追加し、`ffmpeg` の `xfade` フィルタ機能を使って実現。
  - **価値**: 動画の品質を大きく向上させ、視聴者を飽きさせない演出が可能になる。

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
