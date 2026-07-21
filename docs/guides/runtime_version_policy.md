# ランタイムのバージョン方針

ランタイムの唯一の正本は [`.devcontainer/runtime.lock.json`](../../.devcontainer/runtime.lock.json) です。Python、FFmpeg、公式ソースの SHA256、ベースイメージ digest、NVENC ヘッダ、GHCR runtime image digest をここだけで管理します。

通常の Docker / Dev Container build は GHCR の digest 固定 runtime image を土台にするため、FFmpeg をコンパイルしません。CPU は CPU runtime、GPU override は GPU runtime を選択します。GPU 経路の正式要件は NVENC エンコードと CPU フィルタであり、CUDA フィルタは要求しません。

初回 publish 前の lock は runtime image digest が未設定です。この状態では `scripts/export_runtime_env.py` が失敗し、可変タグでの起動を防ぎます。管理者が Runtime update workflow を手動実行して image を publish した後、workflow が digest を lock に記録します。

## 月次更新

Runtime update workflow は、Python と FFmpeg の公式安定版だけを比較します。更新がない場合はそこで終了します。更新がある場合だけ runtime image を再ビルドし、metadata、エンコーダー、Python テスト、パッケージ build を検査してから GHCR へ push し、digest を記録した PR を作成します。自動マージはしません。

既定の確認は dry-run です。

```bash
python scripts/check_runtime_updates.py
```

更新候補の lock 作成は明示指定します。

```bash
python scripts/check_runtime_updates.py --write
```

## Dev Container とロールバック

公開済み lock から shell 環境変数を生成してから Compose を実行します。

```bash
eval "$(python scripts/export_runtime_env.py --shell)"
docker compose -f .devcontainer/docker-compose.yml up --build
```

GPU は `-f .devcontainer/docker-compose.gpu.yml` を追加します。VOICEVOX の GPU 化は既存の専用 override を追加した場合だけです。

ロールバックは runtime lock だけを revert して、再度環境変数を生成してから pull/build します。旧 digest は少なくとも 2 世代保持します。
