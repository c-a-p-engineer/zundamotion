# 立ち絵・表情差分素材メモ

このメモは、Zundamotion 用のキャラクター立ち絵や表情差分を作るときの注意点をまとめる。

関連:

- [docs 入口](../README.md)
- [README](../../README.md)
- [台本チートシート](../../scripts/script_cheatsheet.md)
- [プロジェクト構造](./project_structure.md)

## 推奨ディレクトリ構成

```text
assets/
  characters/
    copetan/
      default/
        base.png
        mouth/
          close.png
          half.png
          open.png
        eyes/
          open.png
          close.png
      smile/
        base.png
        mouth/
          close.png
          half.png
          open.png
        eyes/
          open.png
          close.png
```

探索順:

1. `assets/characters/<name>/<expr>/base.png`
2. 互換: `assets/characters/<name>/<expr>.png`
3. `assets/characters/<name>/default/base.png`
4. 互換: `assets/characters/<name>/default.png`

差分探索順:

- 口: `assets/characters/<name>/<expr>/mouth/{close,half,open}.png` → `assets/characters/<name>/mouth/{...}` → 互換: `assets/characters/<name>/mouth/<expr>/{...}`
- 目: `assets/characters/<name>/<expr>/eyes/{open,close}.png` → `assets/characters/<name>/eyes/{...}` → 互換: `assets/characters/<name>/eyes/<expr>/{...}`

## 表情差分作成時の注意

- 背景は透過 PNG を優先する。
- 透過が難しい場合は、クロマキー合成しやすい単色背景にする。
- 表情差分では、キャラクターの大きさと位置を変更しない。
- 足、腰、肩の位置を固定し、表情や口・目だけを変える。
- 目の色など、キャラクター設定で固定されている要素は変更しない。
- 口パクや目パチ用の差分は、同じポーズと同じキャンバス位置で作る。

## 口パク / 目パチ差分

用意すると自動適用される差分:

- 口: `assets/characters/<name>/<expr>/mouth/{close,half,open}.png`
- 目: `assets/characters/<name>/<expr>/eyes/{open,close}.png`

ルール:

- 元の立ち絵と同じキャンバスサイズ
- 同じ座標系
- 背景は透過 PNG
- 口や目の差分以外は描かない

`flip_x: true` または `flip_y: true` を指定した場合、差分も同じ向きで反転されます。

## 表情変更と表示状態の継承

`characters_persist: true` の同一シーンでは、表情だけを変更しても直前の `scale`、`position`、`anchor`、`visible`、`z`、反転、`asset_name`、`color_filter` を維持します。口パク・目パチ差分も解決後の同じ scale と position で合成されます。

状態の優先順位は、行の明示値、同一シーン内の直前状態、`scene.character_defaults`、`defaults.characters`、システム標準値の順です。`move`、`enter`、`leave` と各 duration は一時的な命令なので次行へ永続化しません。

`reset_characters: true` を付けると直前状態を破棄し、シーン標準値から再解決します。新しいシーンでは前シーンの状態を引き継ぎません。

## Copetan 表情セット

| 表情ID | ディレクトリ | ニュアンス | 備考 |
| --- | --- | --- | --- |
| `default` | `assets/characters/copetan/default/` | 通常ポーズ | フォールバック表情 |
| `smile` | `assets/characters/copetan/smile/` | 素直な笑顔 | 喜び・挨拶向け |
| `angry` | `assets/characters/copetan/angry/` | ぷんすか顔 | 抗議中 |
| `exasperated` | `assets/characters/copetan/exasperated/` | 呆れ顔 | 旧 `deadpan` |
| `embarrassed_blush` | `assets/characters/copetan/embarrassed_blush/` | 真っ赤に照れる | 照れ・動揺 |
| `flustered_coldsweat` | `assets/characters/copetan/flustered_coldsweat/` | 冷や汗の焦り顔 | 緊張向け |
| `sad` | `assets/characters/copetan/sad/` | 落ち込み | 涙目 |
| `smug` | `assets/characters/copetan/smug/` | 得意げ | 余裕の笑み |

## 運用ルール

- キャンバスサイズと原点を全ファイルで統一する。
- `expression` 名は小文字英字で YAML と一致させる。
- 最低限 `default/base.png` を用意する。
- 口パクや目パチを使うなら `default/mouth/` と `default/eyes/` も用意する。

## 背景除去

写真や複雑な背景では AI ベースの除去が有効です。

- ファイル: `tools/remove_bg_ai.py`
- 依存: `pip install rembg`

```bash
python ./tools/remove_bg_ai.py \
  --input /workspace/assets/characters/engy/default \
  --output /workspace/assets/characters/engy/default \
  --model isnet-anime \
  --force-gpu \
  --recursive
```

## 生成依頼プロンプト例

```text
添付画像を解析して、キャラクターの大きさと位置を変更せずに表情差分を作成してください。
可能であれば背景は透過、難しい場合はクロマキー合成用の単色背景にしてください。
足、腰、肩の位置は固定してください。
表情差分以外の服装、髪型、目の色、体の位置は変更しないでください。

以下の指定部分のみ変更してください。

1. 目開け、口閉じ
2. 1 を元にして、口だけ少し開く
3. 1 を元にして、口だけ喋り中の形にする
4. 1 を元にして、目だけ閉じる
```

## 背景透過 PNG 作成コマンド例

```bash
python ./tools/remove_bg_ai.py \
  --input /workspace/assets/characters/engy/default \
  --output /workspace/assets/characters/engy/default \
  --model isnet-anime \
  --force-gpu \
  --recursive
```
