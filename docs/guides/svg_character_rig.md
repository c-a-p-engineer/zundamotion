# SVG Character Rig Authoring

Zundamotionで再利用するキャラクターを、瞬き・口パク・髪揺れ・簡易身体モーションへ対応させるためのSVGリグ仕様とQA手順です。

この機能は現時点では**authoring / QA補助ツール**です。既存のPNG立ち絵・表情差分レンダリング仕様は変更しません。

関連:

- [立ち絵・表情差分素材](./character_assets.md)
- [プロジェクト構造](./project_structure.md)
- [`tools/character_rig/validate_rig.py`](../../tools/character_rig/validate_rig.py)
- [`tools/character_rig/render_preview.py`](../../tools/character_rig/render_preview.py)

## 目的

単純なPNG→SVG変換ではなく、後工程で意味のある部位を個別制御できることを目的とします。

標準フロー:

```text
reference image / parts sheet
  ↓
rig-friendly character asset
  ↓
semantic SVG groups
  ↓
validate_rig.py
  ↓
static PNG render
  ↓
blink / lip-sync / hair motion preview
  ↓
MP4 visual review
```

## Vectorization policy

画像全体を多色オートトレースした結果を、そのまま最終SVGへ採用することは推奨しません。

理由:

- アンチエイリアスや影まで大量のpathになる
- 白抜け・斑点・色崩れが出やすい
- 部位境界とpath境界が一致しない
- 後から目・口・髪を意味単位で編集しにくい

見た目の維持が優先の場合、次のハイブリッドを許容します。

```text
high-fidelity raster base
+
semantic SVG animation groups
```

`<image>`を含むSVGは純ベクターではありません。validatorはhybridとしてwarningを出します。

純ベクターが必要な場合は、必要部位からClean Vector Reconstructionで段階的に置き換えます。

## SVG ID contract v1

### 必須ID

- `character`
- `body`
- `head`
- `face`
- `eyes`
- `eyes-open`
- `eyes-closed`
- `mouth`
- `mouth-closed`

### 推奨ID

- `eyes-half`
- `mouth-small`
- `mouth-a`
- `mouth-i`
- `mouth-u`
- `mouth-e`
- `mouth-o`
- `hair-back`
- `hair-front`
- `hair-left`
- `hair-right`
- `ahoge`
- `arm-left`
- `arm-right`

標準形:

```xml
<svg viewBox="0 0 1024 1536" ...>
  <g id="character">
    <g id="body"/>
    <g id="head" data-pivot-x="512" data-pivot-y="320">
      <g id="hair-back" data-pivot-x="512" data-pivot-y="300"/>
      <g id="face"/>
      <g id="eyes">
        <g id="eyes-open"/>
        <g id="eyes-half"/>
        <g id="eyes-closed"/>
      </g>
      <g id="mouth">
        <g id="mouth-closed"/>
        <g id="mouth-small"/>
        <g id="mouth-a"/>
        <g id="mouth-i"/>
        <g id="mouth-u"/>
        <g id="mouth-e"/>
        <g id="mouth-o"/>
      </g>
      <g id="hair-front" data-pivot-x="512" data-pivot-y="260"/>
      <g id="hair-left" data-pivot-x="390" data-pivot-y="310"/>
      <g id="hair-right" data-pivot-x="634" data-pivot-y="310"/>
      <g id="ahoge" data-pivot-x="512" data-pivot-y="160"/>
    </g>
    <g id="arm-left" data-pivot-x="380" data-pivot-y="520"/>
    <g id="arm-right" data-pivot-x="644" data-pivot-y="520"/>
  </g>
</svg>
```

## Pivot metadata

回転・揺れを想定する部位には以下を付けます。

```xml
data-pivot-x="120" data-pivot-y="180"
```

pivotは画像矩形の中心ではなく、頭なら首、横髪なら生え際、腕なら肩など**接続上の根元**へ置きます。

## 検証

構造検証:

```bash
python tools/character_rig/validate_rig.py assets/characters/tsuzuri/tsuzuri.svg
```

JSON出力:

```bash
python tools/character_rig/validate_rig.py assets/characters/tsuzuri/tsuzuri.svg --json
```

終了コード:

- `0`: 必須契約を満たす
- `2`: parse失敗、必須ID不足、ID重複、viewBox不足など

推奨IDやpivot不足、hybrid rasterはwarningであり、必須契約だけを理由に失敗にはしません。

## PNG / MP4 preview

`render_preview.py`は本体レンダラーとは分離したauthoring QAツールです。

追加依存:

```bash
python -m pip install cairosvg
```

FFmpegもPATH上に必要です。

実行:

```bash
python tools/character_rig/render_preview.py \
  assets/characters/tsuzuri/tsuzuri.svg \
  -o output/character_rig
```

既定値:

- duration: `5.0` 秒
- fps: `20`
- width: `768`

変更例:

```bash
python tools/character_rig/render_preview.py character.svg \
  --duration 8 \
  --fps 30 \
  --width 1080
```

出力:

```text
output/character_rig/
  character.png
  character_preview.mp4
```

previewでは以下を自動的に試します。

- 2回のblink
- `mouth-closed / a / i / u / e / o / small` の簡易cycle
- 左右髪の異位相な小角度揺れ
- 前髪の微小上下移動
- アホ毛のやや大きい揺れ
- character全体の微揺れ

これは音素同期アルゴリズムではなく、**リグ構造が実際に動かせるかを見るQA motion**です。

## Visual QA

MP4を実際に確認し、次を見ます。

- 瞬き時に眼鏡・前髪との位置関係が破綻しない
- 口差分がパッチや髭のように見えない
- 髪の根元が頭から外れない
- 左右髪が完全同期して機械的に見えない
- アホ毛の振幅が過大でない
- character全体がフレーム外へ切れない
- static PNGと初期フレームで見た目が不必要に変わらない

失敗した場合は、その部位だけを修正します。完成している部位まで画像生成やリグ作成からやり直さないことを原則とします。

## 既存PNG表情差分との関係

既存の以下の契約は引き続き有効です。

```text
assets/characters/<name>/<expr>/base.png
assets/characters/<name>/<expr>/mouth/{close,half,open}.png
assets/characters/<name>/<expr>/eyes/{open,close}.png
```

SVGリグはこの仕様を置き換えません。今後、本体レンダラーへ直接SVG animationを統合する場合は、別の利用者向け挙動変更としてcompiler / YAML / render contractを設計します。
