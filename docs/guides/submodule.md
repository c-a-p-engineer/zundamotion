# Git submodule で取り込んで使う

このドキュメントは、Zundamotion を **利用側プロジェクトに git submodule として取り込み**、動画生成機能を呼び出すための手順をまとめたものです。

## 推奨構成

```
your-project/
  vendor/
    zundamotion/        # git submodule
  scripts/              # 利用側の台本置き場（任意）
  assets/               # 利用側の素材置き場（任意）
  output/               # 出力先（任意）
```

## 1) submodule 追加（利用側リポジトリで実行）

```bash
git submodule add <GIT_URL> vendor/zundamotion
git submodule update --init --recursive
```

更新する場合:

```bash
git submodule update --remote --merge
```

## 2) インストール（推奨: editable）

利用側の仮想環境に、サブモジュールを editable install します。

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e vendor/zundamotion
```

フォールバック（editable を使わない場合）:

```bash
pip install -r vendor/zundamotion/requirements.txt
```

さらに最小のフォールバック（環境依存で動く場合）:

```bash
PYTHONPATH=vendor/zundamotion python -m zundamotion.main --help
```

## 3) 実行

### 利用側プロジェクトを基準に実行（推奨）

相対パス（`assets/...` など）は **利用側プロジェクト基準**で解決します。

```bash
zundamotion path/to/script.yaml -o output/out.mp4
```

### サブモジュール同梱サンプルを試す

相対パス基準をサブモジュールに切り替えるには `--project-root` を使います。

```bash
zundamotion scripts/sample.yaml --project-root vendor/zundamotion
```

## 相対パスの基準（`--project-root` / `ZUNDAMOTION_PROJECT_ROOT`）

- 未指定: 実行時のカレントディレクトリ基準
- 指定: `--project-root`（または `ZUNDAMOTION_PROJECT_ROOT`）のディレクトリへ移動してから処理を開始します

用途:
- 利用側プロジェクトに素材を置く（例: `assets/`） → `--project-root` は不要（または `--project-root .`）
- サブモジュール側の `assets/` や `scripts/` をそのまま使う → `--project-root vendor/zundamotion`

## 依存関係について（重要）

- FFmpeg / ffprobe は実行環境に必要です（`ffmpeg` と `ffprobe` が PATH にあること）
- VOICEVOX エンジン連携を使う場合、利用側で VOICEVOX の利用規約・実行環境（Docker 等）を整備してください

## zundamotion-video-workspace のような開発環境を作る

`zundamotion-video-workspace` のように、**エンジン本体は `vendor/zundamotion` に閉じ込め、素材・台本・出力は利用側リポジトリ直下で管理する**構成にすると運用しやすくなります。

### 目的

- `vendor/zundamotion` はアップデートしやすい
- `assets/` と `scripts/` を利用側プロジェクトの資産として管理できる
- Dev Container から `/workspace` をそのまま作業ディレクトリとして扱える
- `zundamotion scripts/...` を利用側リポジトリ基準でそのまま実行できる

### 推奨ディレクトリ構成

```text
your-project/
  .devcontainer/
    .env.example
    Dockerfile.cpu
    Dockerfile.gpu
    devcontainer.json
    docker-compose.yml
    post-create.sh
  assets/
  scripts/
  output/
  vendor/
    zundamotion/
```

### 1) 利用側リポジトリを作る

```bash
mkdir your-project
cd your-project
git init
mkdir -p assets scripts output vendor .devcontainer
git submodule add https://github.com/c-a-p-engineer/zundamotion.git vendor/zundamotion
git submodule update --init --recursive
```

必要に応じて、サンプル素材や台本をサブモジュールから取り込みます。

```bash
cp -r vendor/zundamotion/assets/. assets/
cp -r vendor/zundamotion/scripts/. scripts/
```

### 2) Dev Container を用意する

`your-project/.devcontainer/.env.example`

```dotenv
# CPU を標準にしています。GPU を使う場合は Dockerfile.gpu に切り替えてください。
ZUNDA_DOCKER=Dockerfile.cpu

# VOICEVOX は標準で CPU イメージです。
VOICEVOX_IMAGE=voicevox/voicevox_engine:cpu-ubuntu22.04-latest

# GPU 例
# ZUNDA_DOCKER=Dockerfile.gpu
# VOICEVOX_IMAGE=voicevox/voicevox_engine:nvidia-ubuntu24.04-latest
```

`your-project/.devcontainer/devcontainer.json`

```json
{
  "name": "zundamotion-video-workspace",
  "dockerComposeFile": ["docker-compose.yml"],
  "service": "app",
  "workspaceFolder": "/workspace",
  "workspaceMount": "source=${localWorkspaceFolder},target=/workspace,type=bind,consistency=cached",
  "shutdownAction": "stopCompose",
  "remoteUser": "root",
  "containerEnv": {
    "ZUNDAMOTION_PROJECT_ROOT": "/workspace",
    "VOICEVOX_URL": "http://voicevox:50021",
    "PYTHONPATH": "/workspace/vendor/zundamotion"
  },
  "postCreateCommand": "bash .devcontainer/post-create.sh"
}
```

`your-project/.devcontainer/docker-compose.yml`

```yaml
name: zundamotion-video-workspace

services:
  app:
    build:
      context: ..
      dockerfile: .devcontainer/${ZUNDA_DOCKER:-Dockerfile.cpu}
    working_dir: /workspace
    volumes:
      - ..:/workspace
    command: sleep infinity
    init: true
    tty: true
    stdin_open: true
    environment:
      ZUNDAMOTION_PROJECT_ROOT: /workspace
      VOICEVOX_URL: http://voicevox:50021
      PYTHONPATH: /workspace/vendor/zundamotion
      PYTHONUNBUFFERED: "1"
      PYTHONDONTWRITEBYTECODE: "1"
    depends_on:
      - voicevox

  voicevox:
    image: ${VOICEVOX_IMAGE:-voicevox/voicevox_engine:cpu-ubuntu22.04-latest}
    ports:
      - "50021:50021"
    init: true
```

`your-project/.devcontainer/post-create.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

cd /workspace
python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install -e /workspace/vendor/zundamotion[dev]
mkdir -p /workspace/output
```

`your-project/.devcontainer/Dockerfile.cpu`

```dockerfile
FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    curl \
    fonts-ipafont-gothic \
    git \
    xz-utils \
 && rm -rf /var/lib/apt/lists/*

COPY vendor/zundamotion /tmp/zundamotion
COPY vendor/zundamotion/requirements.txt /tmp/requirements.txt

ARG FFMPEG_URL="https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-linux64-gpl-shared.tar.xz"

RUN curl -L -o /tmp/ffmpeg.tar.xz "${FFMPEG_URL}" \
 && mkdir -p /opt/ffmpeg \
 && tar -xJf /tmp/ffmpeg.tar.xz -C /opt/ffmpeg --strip-components=1 \
 && ln -sf /opt/ffmpeg/bin/ffmpeg /usr/local/bin/ffmpeg \
 && ln -sf /opt/ffmpeg/bin/ffprobe /usr/local/bin/ffprobe \
 && rm -f /tmp/ffmpeg.tar.xz

ENV LD_LIBRARY_PATH="/opt/ffmpeg/lib:${LD_LIBRARY_PATH}"

RUN python -m pip install --upgrade pip setuptools wheel \
 && echo "/opt/ffmpeg/lib" > /etc/ld.so.conf.d/ffmpeg.conf \
 && ldconfig \
 && python -m pip install --no-cache-dir -r /tmp/requirements.txt \
 && python -m pip install --no-cache-dir /tmp/zundamotion \
 && rm -f /tmp/requirements.txt

WORKDIR /workspace
CMD ["sleep", "infinity"]
```

GPU 版は、利用側プロジェクトの運用方針に合わせて NVIDIA ランタイム設定を追加してください。CPU 版で最初に動作確認してから分岐するのが安全です。

### 3) 起動する

```bash
cp .devcontainer/.env.example .devcontainer/.env
docker compose --env-file .devcontainer/.env -f .devcontainer/docker-compose.yml up -d --build
docker compose --env-file .devcontainer/.env -f .devcontainer/docker-compose.yml exec app bash
```

VS Code / Codex から使う場合は、利用側リポジトリを開いて Dev Container を起動します。

### 4) 動作確認

コンテナ内で以下を確認します。

```bash
cd /workspace
python3 --version
ffmpeg -version
ffprobe -version
zundamotion --help
curl http://voicevox:50021/version
```

音声なしでまず 1 本生成:

```bash
zundamotion scripts/sample.yaml \
  -o output/sample.mp4 \
  --no-cache \
  --no-voice \
  --hw-encoder cpu
```

### 運用のコツ

- `vendor/zundamotion` はエンジン更新専用として扱う
- 利用側プロジェクトでは `assets/` `scripts/` `output/` を主に編集する
- サブモジュール更新時は `vendor/zundamotion` 側を pull したあと、利用側リポジトリでサブモジュール参照更新をコミットする
- `PYTHONPATH` を通すだけでも動きますが、Dev Container の `post-create` で `pip install -e /workspace/vendor/zundamotion[dev]` しておく方が安定します
