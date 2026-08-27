# Machine-readable compiler interface

Zundamotion を AI / CI から安全に扱うための、レンダー前の機械可読 CLI 契約です。
通常レンダーの YAML / Markdown loader、`include` / `vars` resolver、default / export preset 適用、validation を再利用し、別系統の解釈器を持ちません。

## コマンド一覧

| コマンド | 目的 | FFmpeg / VOICEVOX 起動 |
| --- | --- | --- |
| `zundamotion validate SCRIPT` | 入力を resolver + validation まで確認 | しない |
| `zundamotion validate SCRIPT --json` | validation 結果を安定 JSON で返す | しない |
| `zundamotion compile SCRIPT` | canonical compiled-config v1 を標準出力へ出す | しない |
| `zundamotion compile SCRIPT -o FILE` | compiled-config をファイルへ保存 | しない |
| `zundamotion capabilities --json` | package が公開する能力を JSON で取得 | しない |
| `zundamotion render SCRIPT ...` | 従来レンダーを明示的に呼ぶ | する |

従来の `zundamotion SCRIPT ...` も互換のため維持します。
`python -m zundamotion` は同じ unified CLI を使用し、`python -m zundamotion.main` は従来 render entrypoint として残ります。

## `validate`

```bash
zundamotion validate scripts/sample.yaml
zundamotion validate scripts/sample.yaml --json
```

成功時の JSON:

```json
{
  "errors": [],
  "format": "zundamotion.validation",
  "format_version": 1,
  "valid": true
}
```

validation failure は終了コード `1` です。
機械向け error code は v1 では次を使用します。

- `ZDM-E1000`: `ValidationError` に正規化された YAML / script validation failure
- `ZDM-E1001`: input / value error

error code の細分化は、既存 validation を壊さず安定分類できるケースから追加します。
巨大な stack trace を machine contract として扱いません。

### `--project-root`

`validate` / `compile` の `--project-root` は、asset / include 等の相対パス解決基準を一時的に変更します。
指定なしでは現在の working directory を使用します。
通常 render の `--project-root` と同じ意味ですが、authoring command の処理終了後は元の working directory へ戻します。

## `compile`

```bash
zundamotion compile scripts/sample.yaml -o build/sample.compiled.json --pretty
```

出力の最上位契約:

```json
{
  "format": "zundamotion.compiled-config",
  "format_version": 1,
  "zundamotion_version": "0.1.0",
  "config": {}
}
```

`config` は次を通過した、実レンダーと同じ canonical configuration です。

1. package default config 読み込み
2. YAML / Markdown input 読み込み
3. `include` / `vars` 解決
4. defaults / character defaults 適用
5. export preset 適用
6. scene / line 正規化
7. plugin 由来 default sound effect 解決
8. validation

### compiled-config と renderer-native IR の境界

`zundamotion.compiled-config` v1 は **現在の renderer へ渡る解決済み設定の固定表現**です。
`docs/design/parser_and_builder.md` にある Scene / Clip / Overlay 等の renderer-native IR 草案を実装済みとみなすものではありません。

将来 renderer-native IR を正式化する場合は、`compiled-config` の format/version と別契約にし、既存 v1 JSON の意味を上書きしません。

## `capabilities`

```bash
zundamotion capabilities
zundamotion capabilities --json
```

JSON には少なくとも次を含みます。

- Zundamotion version
- 対応 input 種別
- machine-readable command
- export preset ID
- subtitle render mode
- TTS provider ID
- built-in plugin metadata
  - id / version / kind
  - provides
  - `params_schema`
  - capabilities

`capabilities` は外部 runtime を起動せず、package と built-in manifest から決定論的に生成します。
ユーザー drop-in plugin を勝手に import して能力一覧へ混ぜません。

## AI authoring の標準ループ

```text
capabilities --json
        ↓
YAML / Markdown を生成・修正
        ↓
validate --json
        ↓
失敗箇所だけ局所修正
        ↓
compile
        ↓
canonical config を必要時に監査
        ↓
render
```

`validate` / `compile` を使っても render 自体の A/V sync、FFmpeg compatibility、VOICEVOX availability を検証したことにはなりません。
最終成果物の確認には従来の smoke / integration / reproducibility 契約を使用します。
