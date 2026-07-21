# Git submodule で取り込んで使う

Zundamotion 本体を submodule に置き、利用側の素材、台本、出力を親リポジトリで管理します。
公式 runtime は submodule の `.devcontainer/Dockerfile` と `runtime.lock.json` を正とし、
古い Dockerfile や FFmpeg build 手順を親側へ複製しません。

## 追加とインストール

```bash
git submodule add <GIT_URL> vendor/zundamotion
git submodule update --init --recursive
python -m venv .venv
. .venv/bin/activate
python -m pip install -e vendor/zundamotion
```

更新時は submodule の変更を確認してから、親リポジトリで参照 commit を記録します。

## 実行基準

親リポジトリをカレントディレクトリにして実行すると、`assets/`、`scripts/`、`output/` は
親側を基準に解決されます。

```bash
zundamotion scripts/example.yaml -o output/example.mp4
```

submodule 同梱サンプルを使う場合だけ基準を切り替えます。

```bash
zundamotion scripts/sample.yaml --project-root vendor/zundamotion
```

`--project-root` は `ZUNDAMOTION_PROJECT_ROOT` より優先します。どちらも未指定なら
実行時のカレントディレクトリが基準です。

## 親リポジトリの Dev Container

親側 Compose の `app` build は submodule の公式 Dockerfile を使用します。

```yaml
services:
  app:
    build:
      context: ../vendor/zundamotion
      dockerfile: .devcontainer/Dockerfile
    working_dir: /workspace
    volumes:
      - ..:/workspace
    command: sleep infinity
    environment:
      ZUNDAMOTION_PROJECT_ROOT: /workspace
      VOICEVOX_URL: http://voicevox:50021
      PYTHONPATH: /workspace/vendor/zundamotion
    depends_on: [voicevox]

  voicevox:
    image: voicevox/voicevox_engine:cpu-ubuntu22.04-0.24.1@sha256:a6a96326ffda12a7292b235a6ef43d299ca33849993e262b230320e17c8c2be8
    ports: ["50021:50021"]
```

VOICEVOX の参照は submodule の `runtime.lock.json` と一致させます。固定値更新時に親側へ
重複記載がある場合は同じコミットで同期し、`latest` を使いません。

GPU render は submodule の `.devcontainer/docker-compose.gpu.yml` と同じ NVIDIA runtime 設定を
親側 override に追加します。VOICEVOX も GPU 化する場合は lock の `voicevox.gpu_*` を使います。

## 起動前確認

```bash
python vendor/zundamotion/scripts/check_runtime_lock.py \
  --lock vendor/zundamotion/.devcontainer/runtime.lock.json
docker compose -f .devcontainer/docker-compose.yml config
docker compose -f .devcontainer/docker-compose.yml up -d --build
```

コンテナ内:

```bash
python --version
ffmpeg -version | head -n 1
ffprobe -version | head -n 1
test -f /usr/share/fonts/opentype/ipafont-gothic/ipag.ttf
curl http://voicevox:50021/version
zundamotion --help
```

## 依存関係

- Python 3.14
- FFmpeg / ffprobe 7.0 以上（公式環境は lock の固定版）
- VOICEVOX を使う場合は固定 engine service
- 字幕の標準前提は IPA ゴシックの必須パス

固定値、CPU/GPU 差、更新とロールバックは
[runtime_version_policy.md](./runtime_version_policy.md) を参照してください。
