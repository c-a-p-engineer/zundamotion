# セットアップと実行

このガイドは、Zundamotion のセットアップ、CLI 実行、ログ確認、GPU/NVENC 確認までをまとめた利用者向け手順です。

関連:

- [docs 入口](../README.md)
- [README](../../README.md)
- [submodule 利用](./submodule.md)
- [パフォーマンスと運用](./performance_tuning.md)
- [プロジェクト構造](./project_structure.md)

## 必要なもの

- Python
- FFmpeg / ffprobe
- VOICEVOX Engine
- 必要に応じて Docker / Dev Container

## セットアップ

### 1. 必要ツールのインストール

- [Docker](https://www.docker.com/get-started/)
- [FFmpeg](https://ffmpeg.org/download.html)
- [VS Code](https://code.visualstudio.com/)
- [Remote - Containers 拡張機能](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)

CLI 起動時には `ffmpeg` / `ffprobe` の存在とバージョンを確認します。FFmpeg 7.x 未満や未インストールの場合は実行前に停止します。

### 2. リポジトリのクローン

```bash
git clone https://github.com/c-a-p-engineer/zundamotion.git
cd zundamotion
```

### 3. Dev Container の起動

VS Code でプロジェクトを開き、「Reopen in Container」を選択します。

GPU を使う場合:

- `.env` で `ZUNDA_DOCKER=Dockerfile.gpu` を指定
- ホスト側で NVIDIA Container Toolkit と GPU ドライバを有効化
- コンテナ内で `nvidia-smi` と `ffmpeg -filters` の確認を実施

Docker ログで追いたい場合:

- `docker compose exec app ...` の実行は `docker logs` に流れません
- 前面実行用の `render` サービスを使ってください

```bash
ZUNDAMOTION_COMMAND='python -m zundamotion.main scripts/sample.yaml -o output/sample.mp4 --no-cache --hw-encoder cpu --log-kv' \
docker compose --env-file .devcontainer/.env -f .devcontainer/docker-compose.yml --profile runner up --build render
```

別ターミナル:

```bash
docker compose --env-file .devcontainer/.env -f .devcontainer/docker-compose.yml logs -f render
```

### 4. Codex Cloud 環境向けセットアップ

```bash
set -euo pipefail

sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  curl git xz-utils ca-certificates \
  gnupg2 software-properties-common \
  fonts-ipafont-gothic

python -m ensurepip --upgrade || true
python -m pip install --no-cache-dir --upgrade pip setuptools wheel
python -m pip install --no-cache-dir -r requirements.txt

FFMPEG_URL="https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-linux64-gpl-shared.tar.xz"
curl -L -o /tmp/ffmpeg.tar.xz "$FFMPEG_URL"
sudo mkdir -p /opt/ffmpeg
sudo tar -xJf /tmp/ffmpeg.tar.xz -C /opt/ffmpeg --strip-components=1
sudo ln -sf /opt/ffmpeg/bin/ffmpeg /usr/local/bin/ffmpeg
sudo ln -sf /opt/ffmpeg/bin/ffprobe /usr/local/bin/ffprobe
rm -f /tmp/ffmpeg.tar.xz
echo "/opt/ffmpeg/lib" | sudo tee /etc/ld.so.conf.d/ffmpeg.conf >/dev/null
sudo ldconfig
echo 'export LD_LIBRARY_PATH="/opt/ffmpeg/lib:${LD_LIBRARY_PATH:-}"' >> ~/.bashrc
```

動作確認:

```bash
python --version
pip --version
ffmpeg -hide_banner -encoders | grep -E 'libx264|libx265'
ffmpeg -hide_banner -filters | grep -E 'overlay_opencl|scale_opencl' || true
```

## 基本実行

### 動画生成

```bash
python -m zundamotion.main scripts/sample.yaml
python -m zundamotion.main scripts/sample.yaml -o output/my_video.mp4
```

### ログ形式

```bash
python -m zundamotion.main scripts/sample.yaml --log-json
python -m zundamotion.main scripts/sample.yaml --log-kv
```

### キャッシュ制御

```bash
python -m zundamotion.main scripts/sample.yaml --no-cache
python -m zundamotion.main scripts/sample.yaml --cache-refresh
```

### 音声なし

```bash
python -m zundamotion.main scripts/sample.yaml --no-voice --no-cache
```

### 並列数と HW エンコーダ

```bash
python -m zundamotion.main scripts/sample.yaml --jobs auto
python -m zundamotion.main scripts/sample.yaml --jobs 4
python -m zundamotion.main scripts/sample.yaml --hw-encoder gpu
python -m zundamotion.main scripts/sample.yaml --quality quality
```

### 最終連結を `-c copy` に限定

```bash
python -m zundamotion.main scripts/sample.yaml --final-copy-only
```

### タイムライン出力

```bash
python -m zundamotion.main scripts/sample.yaml --timeline
python -m zundamotion.main scripts/sample.yaml --timeline csv
python -m zundamotion.main scripts/sample.yaml --timeline both
python -m zundamotion.main scripts/sample.yaml --no-timeline
```

### 字幕ファイル出力

```bash
python -m zundamotion.main scripts/sample.yaml --subtitle-file
python -m zundamotion.main scripts/sample.yaml --subtitle-file ass
python -m zundamotion.main scripts/sample.yaml --no-subtitle-file
```

## `--project-root` の基準

- 未指定: カレントディレクトリ基準
- 指定: `--project-root` または `ZUNDAMOTION_PROJECT_ROOT` を基準に `assets/`, `scripts/`, `output/` などの相対パスを解決

例:

```bash
zundamotion path/to/script.yaml -o output/out.mp4
zundamotion scripts/sample.yaml --project-root vendor/zundamotion
```

submodule 利用の詳細は [`submodule.md`](./submodule.md) を参照してください。

## VOICEVOX Engine

Dev Container では Docker Compose により VOICEVOX Engine が起動し、通常は `voicevox:50021` で利用できます。  
ローカルでは通常 `http://127.0.0.1:50021` を使います。必要に応じて `VOICEVOX_URL` で上書きできます。

## GPU / NVENC 確認

```bash
nvidia-smi
ldconfig -p | rg libnvidia-encode
ffmpeg -hide_banner -encoders | rg nvenc
```

`libnvidia-encode.so.1` が見つからない場合は、Docker 起動時に `--gpus all` と `NVIDIA_DRIVER_CAPABILITIES=compute,utility,video` または `all` を指定してください。

## 速度優先で回すとき

- `--quality speed`
- `--jobs auto`
- `--hw-encoder gpu`

長尺動画で字幕が多い場合は、最終字幕合成だけ自動で CPU フィルタへフォールバックします。進捗ログは 15 秒ごとに出ます。

## よくあるエラー

| エラー | 対処 |
| --- | --- |
| `ModuleNotFoundError: No module named 'yaml'` | `pip install -r requirements.txt` |
| `ffprobe not found` | FFmpeg / ffprobe を PATH に入れる |
| `No module named 'zundamotion'` | `pip install -e .` または `PYTHONPATH=.` を指定 |
| `Validation Error: ...` | YAML 構文、素材パス、パラメータ値を確認 |
