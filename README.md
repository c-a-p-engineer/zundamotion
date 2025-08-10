# 🎬 Zundamotion: YAML台本から動画を自動生成する開発環境

Zundamotionは、VOICEVOXによる高品質な音声合成とFFmpegを用いた映像合成を組み合わせ、YAML形式の台本から`.mp4`動画を自動生成する強力な開発環境です。動画制作のワークフローを効率化し、コンテンツ作成を加速します。

---

## 🚀 機能概要

- **VOICEVOX連携**: Dockerを活用したVOICEVOXエンジンとの連携により、高品質な音声合成を実現します。
- **FFmpegによる動画合成**: 背景、立ち絵、字幕、音声をFFmpegでシームレスに合成し、プロフェッショナルな動画を生成します。
- **YAMLベースの台本**: 直感的で記述しやすいYAML形式の台本から、音声と字幕を自動生成します。
- **多様な字幕出力**: SRT形式とFFmpeg `drawtext`用のJSON形式字幕ファイルの両方を出力し、柔軟な動画編集に対応します。
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

## 🗣 VOICEVOX エンジン

DevContainer起動時にDocker ComposeによってVOICEVOXエンジンが自動的に起動し、`voicevox:50021`で利用可能になります。
**重要**: ローカル環境からアクセスする場合は`localhost:50021`ではなく、必ず`voicevox:50021`を指定してください。

---

## 🧪 動作確認

#### 1. 音声と字幕の生成
`scripts/sample.yaml` に記述された台本を元に、音声ファイルと字幕ファイルを生成します。
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
生成された音声と字幕、そして台本に指定された背景や立ち絵素材を組み合わせて`.mp4`動画を生成します。`zundamotion.main`は内部でシステムにインストールされたFFmpegコマンドを利用します。
```bash
python -m zundamotion.main scripts/sample.yaml
```
出力ファイルのパスを指定する場合は、`-o`または`--output`オプションを使用します。
```bash
python -m zundamotion.main scripts/sample.yaml -o output/my_video.mp4
```
中間ファイルを保持したい場合は、`--keep-intermediate`オプションを使用します。
```bash
python -m zundamotion.main scripts/sample.yaml --keep-intermediate
```

---

## 💡 今後の機能拡張予定

- [ ] **動画生成機能の追加**: `render_video.py` を実装し、生成された音声・字幕と背景画像を組み合わせて`.mp4`動画を出力する機能。
- [ ] **CLIツールの提供**: `zundamotion render script.yaml` のようなコマンドラインインターフェースを整備し、より手軽に動画生成を実行できるようにします。
- [ ] **キャラクター表現の強化**: 表情差分や口パクの自動生成に対応し、キャラクターの表現力を向上させます。
- [ ] **高度な動画編集機能**: エフェクト、BGM、トランジションの指定を台本に含めることで、よりリッチな動画コンテンツを制作可能にします。

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
