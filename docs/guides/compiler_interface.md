# Machine-readable compiler interface

Zundamotion を AI / CI から安全に扱うための、レンダー前の機械可読 CLI 契約です。
通常レンダーの YAML / Markdown loader、`include` / `vars` resolver、default / export preset 適用、validation を再利用し、別系統の解釈器を持ちません。
レンダー後の成果物検査は [output_qa.md](./output_qa.md) の `inspect` 契約へ分離します。

## コマンド一覧

| コマンド | 目的 | FFmpeg / VOICEVOX 起動 |
| --- | --- | --- |
| `zundamotion validate SCRIPT` | 入力を resolver + validation まで確認 | しない |
| `zundamotion validate SCRIPT --json` | validation 結果を安定 JSON で返す | しない |
| `zundamotion compile SCRIPT` | canonical compiled-config v1 を標準出力へ出す | しない |
| `zundamotion compile SCRIPT -o FILE` | compiled-config をファイルへ保存 | しない |
| `zundamotion capabilities --json` | package が公開する能力を JSON で取得 | しない |
| `zundamotion render SCRIPT ...` | 従来レンダーを明示的に呼ぶ | する |
| `zundamotion inspect VIDEO ...` | レンダー済み成果物を probe / 比較し、任意で contact sheet を生成 | ffprobe。contact sheet 時は FFmpeg |

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

## `inspect` との境界

`inspect` は compiler interface の前処理ではなく **post-render QA** です。
`--script` を指定した場合だけ canonical config を再利用し、生成済み MP4 の observable media parameter と照合します。

```bash
zundamotion inspect output/sample.mp4 \
  --script scripts/sample.yaml \
  --contact-sheet \
  --json
```

machine-readable 出力は `zundamotion.output-inspection` v1 です。
`machine_valid` は ffprobe で確認できる条件だけの合否であり、contact sheet の目視確認を含みません。
詳細は [output_qa.md](./output_qa.md) を正とします。

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
        ↓
inspect --script ... --contact-sheet --json
        ↓
machine_valid を確認し、contact sheet を実際に見る
```

`validate` / `compile` を使っても render 自体の A/V sync、FFmpeg compatibility、VOICEVOX availability を検証したことにはなりません。
`inspect` の machine check を使っても transition / motion / subtitle placement 等を目視したことにはなりません。
最終成果物の確認には smoke / integration / reproducibility と [video_direction_and_qa.md](./video_direction_and_qa.md) の実動画 QA を併用します。
