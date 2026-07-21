# セットアップと実行

このガイドはローカル実行、公式 Dev Container、Codex Cloud、CPU/GPU 起動を扱います。
固定値と更新手順は [runtime_version_policy.md](./runtime_version_policy.md) を参照してください。

## サポート範囲

公式環境は `runtime.lock.json` の CPython 3.14 系、固定 BtbN FFmpeg、固定 VOICEVOX、
IPA ゴシックを使用します。ローカル実行の最低条件は Python 3.14 と FFmpeg/ffprobe 7.0 です。
ローカル最低版は互換性の下限であり、公式 lock と同一出力を保証する値ではありません。

## 公式 Dev Container

単一の `.devcontainer/Dockerfile` が digest 固定 Python image を土台にし、
`scripts/install_locked_ffmpeg.py` で checksum 検証済み BtbN archive を導入します。

```bash
python scripts/check_runtime_lock.py
docker compose -f .devcontainer/docker-compose.yml config
docker compose -f .devcontainer/docker-compose.yml up -d --build app voicevox
```

GPU render:

```bash
docker compose -f .devcontainer/docker-compose.yml \
  -f .devcontainer/docker-compose.gpu.yml config
docker compose -f .devcontainer/docker-compose.yml \
  -f .devcontainer/docker-compose.gpu.yml up -d --build app voicevox
```

VOICEVOX も GPU 化する場合:

```bash
docker compose -f .devcontainer/docker-compose.yml \
  -f .devcontainer/docker-compose.gpu.yml \
  -f .devcontainer/docker-compose.voicevox-gpu.yml config
docker compose -f .devcontainer/docker-compose.yml \
  -f .devcontainer/docker-compose.gpu.yml \
  -f .devcontainer/docker-compose.voicevox-gpu.yml up -d --build app voicevox
```

## ランタイム確認

```bash
python --version
ffmpeg -version | head -n 1
ffprobe -version | head -n 1
curl http://voicevox:50021/version
test -f /usr/share/fonts/opentype/ipafont-gothic/ipag.ttf
fc-match IPAGothic
cat /opt/zundamotion-build-info/build-info.json
```

build-info には Python version/base image、FFmpeg version/archive/SHA256、VOICEVOX 固定参照、
必須フォントパス、主要 encoder/filter の実測結果を記録します。

## Codex Cloud

Docker が利用可能なら公式 Dev Container と同じ build を優先します。Docker を使えない場合:

```bash
sudo apt-get update
sudo apt-get install -y --no-install-recommends fontconfig fonts-ipafont-gothic
sudo python scripts/install_locked_ffmpeg.py \
  --lock .devcontainer/runtime.lock.json --prefix /opt/ffmpeg
python -m pip install -e '.[dev]'
python scripts/check_runtime_lock.py
test -f /usr/share/fonts/opentype/ipafont-gothic/ipag.ttf
```

この経路では Python 自体の image digest は固定できません。公式再現環境と区別して報告します。

## CLI 実行

```bash
python -m zundamotion.main scripts/sample.yaml -o output/sample.mp4
python -m zundamotion.main scripts/sample.yaml -o output/sample.mp4 --no-voice --no-cache
python -m zundamotion.main scripts/sample.yaml --log-json
python -m zundamotion.main scripts/sample.yaml --log-kv
python -m zundamotion.main scripts/sample.yaml --jobs auto --hw-encoder gpu --quality speed
```

`--project-root` または `ZUNDAMOTION_PROJECT_ROOT` を指定すると相対パスの基準を変更します。
submodule 利用は [submodule.md](./submodule.md) を参照してください。

## GPU / NVENC 確認

```bash
nvidia-smi
ffmpeg -hide_banner -encoders | rg nvenc
python scripts/verify_gpu_runtime.py --skip-render
```

GPU filter は optional です。NVENC が使えても filter は CPU へフォールバックできます。

## Docker ログで render を追う

```bash
ZUNDAMOTION_COMMAND='python -m zundamotion.main scripts/sample.yaml -o output/sample.mp4 --no-cache --hw-encoder cpu --log-kv' \
docker compose -f .devcontainer/docker-compose.yml --profile runner up --build render
```

## よくあるエラー

| エラー | 対処 |
| --- | --- |
| `ffmpeg` / `ffprobe` がない | 公式 image を build するか固定 installer を実行する |
| FFmpeg 7.0 未満 | 7.0 以上へ更新する。公式 lock は別途固定値を使う |
| IPA ゴシックがない | `fonts-ipafont-gothic` を導入し必須パスを確認する |
| `No module named 'zundamotion'` | `python -m pip install -e .` を実行する |
| VOICEVOX に接続できない | Compose service と `VOICEVOX_URL` を確認する |
