# 🎬 Zundamotion Dev Environment

**Zundamotion** は、VOICEVOX による自動音声合成と FFmpeg を用いた映像合成で、  
YAMLベースの台本から `.mp4` 動画を自動生成する開発環境です。

---

## 🚀 機能概要

- ✅ VOICEVOX による高品質な音声合成（Docker連携）
- ✅ FFmpeg による動画合成（背景・立ち絵・字幕・音声）
- ✅ 台本（YAML形式）から音声と字幕を自動生成
- ✅ SRT形式・FFmpeg drawtext用字幕ファイルの両方を出力
- ✅ DevContainer対応でどこでも同じ開発環境

---

## 🧱 ファイル構成（概要）

```plaintext
.devcontainer/          # VSCode + Docker開発環境
scripts/                # 台本ファイル（YAML）
voices/                 # 合成された音声・字幕ファイル
assets/                 # 背景や立ち絵素材（未使用でも可）
output/                 # 最終出力の動画など
zundamotion/            # Pythonモジュール群
````

---

## 📦 セットアップ手順

### 1. 必要ツールのインストール

* Docker
* VSCode + [Remote - Containers 拡張](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)

### 2. リポジトリをクローン

```bash
git clone https://github.com/yourname/zundamotion.git
cd zundamotion
```

### 3. DevContainer を起動（VSCode）

「Reopen in Container」を選択すると、開発環境が自動構築されます。

---

## 🗣 VOICEVOX エンジンについて

Docker Compose により、VOICEVOXエンジンは `voicevox:50021` に自動起動されます。

> 🚫 `localhost:50021` ではなく、`voicevox:50021` を指定してください

---

## 🧪 動作確認：音声＋字幕生成

### 1. 台本ファイルの例（`scripts/sample.yaml`）

```yaml
meta:
  title: "自己紹介"

defaults:
  voice:
    speaker: 1
    speed: 1.0
    pitch: 0.0

scenes:
  - id: intro
    lines:
      - character: zundamon
        text: "こんにちは！ずんだもんです。"
      - character: zundamon
        text: "今日は自己紹介するのだ！"
```

### 2. 音声＋字幕を一括生成

```bash
python -m zundamotion.render_audio scripts/sample.yaml
```

### 3. 出力されるファイル例（`voices/` ディレクトリ）

```plaintext
intro_1.wav
intro_1.srt
intro_1.drawtext.json
intro_2.wav
intro_2.srt
intro_2.drawtext.json
```

---

## 💡 今後の機能拡張予定

* [ ] `render_video.py`: 音声 + 背景 + 字幕 → `.mp4` を出力
* [ ] `zundamotion render script.yaml` のようなCLIツール化
* [ ] キャラクター表情差分・口パク対応
* [ ] エフェクト・BGM・トランジション指定

---

## ⚠️ ライセンスと利用ガイドライン

* VOICEVOX はキャラクターごとに商用利用可否が異なります。

  * [VOICEVOX 利用規約](https://voicevox.hiroshiba.jp/)

---

## 🧑‍💻 制作者・連絡先

* 👤 c_a_p_engineer ([https://x.com/c_a_p_engineer](https://x.com/c_a_p_engineer))
* Zundamotion Project

---

## ✅ よくあるエラーと対処法

| エラー                                           | 対処法                                                   |
| --------------------------------------------- | ----------------------------------------------------- |
| `ModuleNotFoundError: No module named 'yaml'` | `pip install -r requirements.txt`                     |
| `ffprobe not found`                           | Dockerfile に `apt install ffmpeg` を追加                 |
| `No module named 'zundamotion'`               | `PYTHONPATH=.` を指定 or `python -m zundamotion.xxx` で実行 |

---

