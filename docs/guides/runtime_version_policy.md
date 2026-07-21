# ランタイムのバージョン方針

公式 Dev Container と CI のランタイム契約は
[`.devcontainer/runtime.lock.json`](../../.devcontainer/runtime.lock.json) を正本とします。
可変タグや未検証値へ自動更新せず、lock の変更はレビューと検証を経て手動でマージします。

## lock が管理するもの

- CPython の厳密なバージョン、ベース image タグ、image digest
- BtbN FFmpeg の固定 release tag、archive 名、SHA256、期待 version prefix
- FFmpeg の必須 encoder と configure flag
- CPU/GPU VOICEVOX の固定タグと multi-arch digest
- IPA ゴシックのパッケージ名と必須ファイルパス
- GPU 環境で参考確認する optional filter

Python image は `image@sha256:...` で固定します。FFmpeg は
`scripts/install_locked_ffmpeg.py` が固定 BtbN release から archive を取得し、SHA256 を照合して
`/opt/ffmpeg` へ展開します。展開後に version、必須 encoder、configure flag を検証します。
ソースリポジトリからの手動 build や GHCR runtime image は公式経路ではありません。

`.devcontainer/Dockerfile` は `fonts-ipafont-gothic` と `fontconfig` を導入し、
`/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf` の存在を build 中に検査します。
同じパスを CI と標準サンプルも使用します。build の実測情報は
`/opt/zundamotion-build-info/build-info.json` に記録されます。

## CPU/GPU の違い

base Compose は CPU render と CPU VOICEVOX を使用します。GPU render は
`.devcontainer/docker-compose.gpu.yml`、GPU VOICEVOX はさらに
`.devcontainer/docker-compose.voicevox-gpu.yml` を重ねます。GPU 経路の正式要件は
NVENC encode と CPU filter です。CUDA/OpenCL filter は optional で、正式要件にしません。

## lock の検証

```bash
python scripts/check_runtime_lock.py
docker compose -f .devcontainer/docker-compose.yml config
docker compose -f .devcontainer/docker-compose.yml \
  -f .devcontainer/docker-compose.gpu.yml config
docker compose -f .devcontainer/docker-compose.yml \
  -f .devcontainer/docker-compose.gpu.yml \
  -f .devcontainer/docker-compose.voicevox-gpu.yml config
```

`tests/test_runtime_lock.py` は必須キー、空文字列、digest/SHA256 形式、`latest` 拒否、
CPU/GPU VOICEVOX、フォント、Compose との一致を検証します。

## 更新手順

1. Python と FFmpeg の公式安定版、BtbN の実在 archive、VOICEVOX の実在タグを確認する。
2. Registry から image digest、配布元から archive SHA256 を実測する。推測値は使わない。
3. `runtime.lock.json` と Compose を更新し、上記 lock/Compose 検証を実行する。
4. Docker image を build し、build-info、必須フォント、encoder、configure flag を確認する。
5. 非 smoke、FFmpeg integration、package build、CPU smoke を実行する。
6. GPU がある場合だけ NVENC smoke を実行し、未実行ならその旨を明記する。
7. 検証結果をレビューし、手動でマージする。自動マージしない。

## ロールバック

問題のある lock と Compose の変更を、直前に検証済みだったコミットへ同時に戻して
image を再 build します。FFmpeg archive URL、VOICEVOX image、フォント契約を部分的に
混在させません。戻した後も lock/Compose 検証と CPU smoke を再実行します。
