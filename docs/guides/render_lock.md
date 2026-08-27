# Render Lock / Provenance

`zundamotion lock` は、1本の動画を再生成するときに重要な入力状態を決定論的な JSON として固定します。
生成AIや外部素材取得を render 中へ持ち込まず、素材確定後の状態を検証するための project-level provenance です。

## 基本操作

```bash
zundamotion lock scripts/sample.yaml -o zundamotion.lock.json
zundamotion verify-lock scripts/sample.yaml --lock-file zundamotion.lock.json
```

機械向け確認:

```bash
zundamotion verify-lock scripts/sample.yaml \
  --lock-file zundamotion.lock.json \
  --json
```

`verify-lock` は一致時に終了コード `0`、差分ありで `1`、入力や JSON 自体を処理できない場合は `2` です。

## lock v1 が固定するもの

`zundamotion.render-lock` v1 は次を記録します。

- Zundamotion package version
- source script path と SHA-256
- canonical compiled-config の SHA-256
- compiled configuration から参照され、実際に存在する file の path / SHA-256
- Repository checkout 上で確認できる `.devcontainer/runtime.lock.json` の SHA-256

`include` / `vars` の展開結果は compiled-config hash に含まれるため、include 先の内容変更も検出対象になります。

## 固定しないもの

v1 は次を自動取得しません。

- Git commit SHA
- OS 全体のpackage一覧
- GPU driver
- FFmpeg / VOICEVOX process の実稼働version問い合わせ
- ネットワーク上のURL内容
- 生成AIのpromptやseed

これらを固定したい場合は、生成物を先に local asset として確定し、Zundamotion が参照する file として lock 対象へ入れます。
公式 Docker / Dev Container の runtime version は `.devcontainer/runtime.lock.json` を正本とし、Render Lock はそのファイルhashを記録します。

## asset discovery

v1 は canonical compiled configuration 内の文字列を走査し、現在の project root から実在する file として解決できたものを hash 化します。
HTTP/HTTPS URL は取得しません。
project root 外の absolute path（例: font）も実在する場合は absolute path と hash を記録します。

これにより「設定に書いてあるが存在しないfile」をlockで隠しません。そもそも必須素材の欠損は通常の validation で先に失敗します。

## verification difference code

- `ZDM-L1000`: lock format 不一致
- `ZDM-L1001`: lock format version 不一致
- `ZDM-L1100`: Zundamotion version 不一致
- `ZDM-L1101`: source script hash 不一致
- `ZDM-L1102`: compiled-config hash 不一致
- `ZDM-L1103`: runtime lock 不一致
- `ZDM-L1200`: 既存assetのhash不一致
- `ZDM-L1201`: 現在側に新しいassetが追加
- `ZDM-L1202`: lock側にあったassetが現在見つからない

## 推奨フロー

```text
capabilities
  ↓
authoring
  ↓
validate
  ↓
compile / review
  ↓
素材を確定
  ↓
lock
  ↓
verify-lock
  ↓
render
```

`verify-lock` が成功したことは、最終 MP4 の framemd5 / audio PCM / A/V sync が成功したことを意味しません。
Render Lock は **入力 provenance**、既存 reproducibility test は **出力同等性** を担当します。
