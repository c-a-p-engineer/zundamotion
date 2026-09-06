# SVG Character Rig Authoring

Zundamotionで再利用するキャラクターを、瞬き・口パク・髪揺れ・頭部/身体・手足の簡易モーションへ対応させるためのSVGリグ仕様とQA手順です。

この機能は現時点では**authoring / QA補助ツール**です。既存のPNG立ち絵・表情差分レンダリング仕様は変更しません。

関連:

- [立ち絵・表情差分素材](./character_assets.md)
- [プロジェクト構造](./project_structure.md)
- [`tools/character_rig/validate_rig.py`](../../tools/character_rig/validate_rig.py)
- [`tools/character_rig/render_preview.py`](../../tools/character_rig/render_preview.py)

## 目的

単純なPNG→SVG変換ではなく、**パーツシート上の元パーツ単位を最終SVG・pivot・状態差分まで保持する**ことを目的とします。

最重要原則:

```text
parts sheet
  ↓ fixed pixel extraction
source parts
  ↓ direct SVG placement
semantic SVG hierarchy
  ↓ rig on the same source-part units
motion
```

次の経路は標準にしません。

```text
parts sheet
  ↓
merge to full body
  ↓
re-segment merged image
  ↓
SVG / rig
```

一度合体した画像から目・口・腕・脚を再分割すると、元パーツの座標・接続点・状態対応を失い、位置ズレを再推定する必要が生じるためです。

`fullbody_ref` は**完成見本・neutral pose比較用**です。最終SVGの可動ベースとして使いません。

## 標準フロー

```text
fixed-layout parts sheet
  ↓
parts_layout.json
  ↓
exact pixel extraction
  ↓
extracted parts contact sheet
  ↓
rig_config.json
  ↓
SVG assembly from source parts
  ↓
validate_rig.py
  ↓
neutral PNG vs fullbody_ref
  ↓
face-state contact sheet
  ↓
blink / lip-sync / hair / limb motion preview
  ↓
MP4 visual review
  ↓
iterate only failed source parts / placement / pivot
```

## Parts sheet contract v1

### 固定するもの

- sheet width / height
- grid / cell size
- パーツ数
- パーツ名
- 各パーツのrow / colまたはpixel rectangle
- 左右の命名
- facial state名
- limb segmentation

### 推奨パーツ

顔:

- `face_base`
- `eye_L_open`
- `eye_L_half`
- `eye_L_closed`
- `eye_R_open`
- `eye_R_half`
- `eye_R_closed`
- `brow_L_normal / angry / troubled / surprised`
- `brow_R_normal / angry / troubled / surprised`
- `mouth_closed`
- `mouth_small`
- `mouth_a`
- `mouth_i`
- `mouth_u`
- `mouth_e`
- `mouth_o`

髪:

- `hair_back`
- `hair_front`
- `hair_left`
- `hair_right`
- `ahoge`

身体:

- `neck`
- `torso`
- `waist` または `skirt_waist`
- `upper_arm_L`
- `forearm_L`
- `hand_L`
- `upper_arm_R`
- `forearm_R`
- `hand_R`
- `thigh_L`
- `calf_L`
- `foot_L`
- `thigh_R`
- `calf_R`
- `foot_R`

参照:

- `fullbody_ref`

### 生成条件

- 1セルに1パーツ
- セル境界をまたがない
- パーツ同士を接触させない
- 背景透過、または均一な単色
- ラベル・説明文・矢印をセル内へ描かない
- `face_base` に目・眉・口を焼き込まない
- facial stateは同じregistration pointへ置ける比率で揃える
- fullbody_refと各パーツのキャラクター・衣装・比率を一致させる

## parts_layout.json

抽出座標の正本です。

最低限:

```json
{
  "sheet": {
    "width": 4096,
    "height": 4096,
    "cell_width": 512,
    "cell_height": 512
  },
  "parts": {
    "mouth_a": {
      "row": 3,
      "col": 0,
      "rect": [0, 1536, 512, 512]
    }
  }
}
```

### Extraction rules

- 指定rectangleをそのままcropする
- 輪郭検出で毎回crop範囲を推定しない
- OCRやラベル認識でpart名を決めない
- 同じsheetの全partへ同じ規則を適用する
- 一度切り出したsource partをSVGへ直接入れる

### Tight crop

透明余白を詰めること自体は許容しますが、trim前のcell原点を失ってはいけません。

trimする場合は、最低限次を保持します。

```json
{
  "source_cell": [1024, 1536, 512, 512],
  "trim_offset": [84, 116],
  "trim_size": [188, 96],
  "registration": [178, 164]
}
```

trim後の画像中心から配置位置を再推定する方式は採用しません。

## rig_config.json

元パーツとSVG配置・可動設定を結ぶ正本です。

各partの最低情報:

- `source_part`
- `svg_id`
- `parent`
- `x / y`
- `scale`
- `pivot_x / pivot_y`
- `z`

状態slotには、全stateが共有するregistrationを持たせます。

例:

```json
{
  "slots": {
    "mouth": {
      "x": 416,
      "y": 320,
      "states": {
        "closed": "mouth_closed",
        "small": "mouth_small",
        "a": "mouth_a",
        "i": "mouth_i",
        "u": "mouth_u",
        "e": "mouth_e",
        "o": "mouth_o"
      }
    }
  }
}
```

## Hybrid SVG policy

`<image>`を使うハイブリッドSVGは許容します。ただし、標準形は次です。

```text
per-part raster assets
+
semantic SVG hierarchy
+
explicit placement / pivot metadata
```

次は標準にしません。

```text
monolithic fullbody raster
+
empty semantic groups
+
small overlay patches
```

`fullbody_ref` をSVGへ含める場合は、QA用の非表示 `reference` group等へ置き、`character` animation hierarchyへ入れません。

純ベクターが必要な場合は、元パーツ単位でClean Vector Reconstructionへ置換します。画像全体の多色オートトレース結果を最終SVGへ採用しません。

ハイブリッドSVGを純ベクターと報告してはいけません。

## Source traceability

可能なら各assetに元パーツ名を保持します。

```xml
<image
  id="asset-mouth-a"
  data-source-part="mouth_a"
  ... />
```

これにより、visual QAで失敗した箇所をsource cellまで戻れます。

## SVG ID contract v2 authoring model

既存validator v1の必須IDは互換wrapperとして維持しつつ、authoringでは手足をjoint単位へ分けます。

```xml
<svg viewBox="0 0 1024 1536" ...>
  <g id="character">
    <g id="body">
      <g id="torso"/>
      <g id="waist"/>

      <g id="arm-left">
        <g id="upper-arm-left"/>
        <g id="forearm-left"/>
        <g id="hand-left"/>
      </g>
      <g id="arm-right">
        <g id="upper-arm-right"/>
        <g id="forearm-right"/>
        <g id="hand-right"/>
      </g>

      <g id="leg-left">
        <g id="thigh-left"/>
        <g id="calf-left"/>
        <g id="foot-left"/>
      </g>
      <g id="leg-right">
        <g id="thigh-right"/>
        <g id="calf-right"/>
        <g id="foot-right"/>
      </g>
    </g>

    <g id="head" data-pivot-x="512" data-pivot-y="320">
      <g id="hair-back"/>
      <g id="face">
        <g id="face-base"/>
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
      </g>
      <g id="hair-front"/>
      <g id="hair-left"/>
      <g id="hair-right"/>
      <g id="ahoge"/>
    </g>
  </g>
</svg>
```

### Current validator compatibility

`tools/character_rig/validate_rig.py` は現在、v1の最小IDを強制しています。

- `character`
- `body`
- `head`
- `face`
- `eyes`
- `eyes-open`
- `eyes-closed`
- `mouth`
- `mouth-closed`

v2のjoint分割はauthoring contractです。validatorでのjoint-level enforcementは別実装変更として扱います。

## Pivot / hierarchy

pivotは画像矩形の中心ではなく、**接続上の根元**へ置きます。

- `head` → 首
- `hair-left/right` → 生え際
- `ahoge` → 根元
- `upper-arm-*` → 肩
- `forearm-*` → 肘
- `hand-*` → 手首
- `thigh-*` → 股関節
- `calf-*` → 膝
- `foot-*` → 足首

手足はparent chainで動かします。

```text
upper-arm
  └─ forearm
      └─ hand

thigh
  └─ calf
      └─ foot
```

完成立ち絵を回転させた後に再切り出して疑似関節を作らないでください。

## State replacement policy

### Blink

標準遷移:

```text
open → half → closed → half → open
```

- 全stateを同じeye slotで置換する
- 開眼画像の上へ閉眼パッチを重ねて隠す方式を標準にしない
- state切替で目以外の顔座標を変えない

### Lip sync

標準state:

- `mouth-closed`
- `mouth-small`
- `mouth-a`
- `mouth-i`
- `mouth-u`
- `mouth-e`
- `mouth-o`

- 全stateを同じmouth slotで置換する
- skin-color patchで元口を消して別口を重ねる方式を標準にしない
- `face_base`に口が残っている場合はsource assetの不備として修正する
- previewではstate cycleで位置ズレとscale差を先に確認する

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

現在のpreviewは次を確認します。

- blink
- `mouth-closed / a / i / u / e / o / small` cycle
- 左右髪の異位相な小角度揺れ
- 前髪の微小上下移動
- アホ毛の揺れ
- character全体の微揺れ

joint-level limb previewはv2 authoring designに含みますが、現在の`render_preview.py`にはまだ統合していません。実装時は`upper-arm / forearm / hand`と`thigh / calf / foot`のparent/pivotを小振幅で確認します。

これは音素同期や演技生成ではなく、**リグ構造が実際に動かせるかを見るQA motion**です。

## QA artifacts

parts-sheet rigでは、MP4だけで合否を決めません。

標準成果物:

```text
parts_layout.json
extracted_parts/
extracted_parts_contact_sheet.png
rig_config.json
character.svg
character.png
face_state_contact_sheet.png
character_preview.mp4
video_contact_sheet.png
validation.json
```

### 1. Extracted-parts QA

- part名と画像内容が一致する
- 罫線・文字・別partが混入していない
- 左右が逆でない
- 必須partが欠けていない
- trim offset / registrationが保持されている

### 2. Neutral assembly QA

SVGからneutral pose PNGをレンダリングし、`fullbody_ref`と比較します。

確認:

- 頭・首・肩・腰・膝・足首
- scale
- 髪の前後関係
- 目・眉・口のregistration
- 手足の接続

`fullbody_ref`は比較用であり、animation sourceではありません。

### 3. Face-state contact sheet

同じcropで最低限以下を並べます。

- open / half / closed
- closed / small / a / i / u / e / o
- 必要な眉差分

確認:

- state切替で中心が飛ばない
- 目の高さと左右間隔が変わらない
- 口の中心とbaselineが変わらない
- 口サイズが極端に暴れない
- patch境界が見えない

### 4. Motion visual QA

- blink時に前髪・眼鏡との関係が破綻しない
- mouth stateが髭/パッチのように見えない
- 髪の根元が頭から外れない
- joint motion実装後は肩・肘・手首が外れない
- joint motion実装後は股関節・膝・足首が外れない
- character全体がフレーム外へ切れない
- static PNGと初期フレームで見た目が不必要に変わらない

## Failure-directed iteration

失敗した**source part / slot / placement / pivot**だけを直します。

例:

- 目だけズレる → `eye_*` source partまたはeye slot registrationのみ修正
- 口だけズレる → `mouth_*` source partまたはmouth slotのみ修正
- 口パッチが必要になる → `face_base`に口が残っていないか確認
- 髪の根元が外れる → hair source境界またはpivotを修正
- 肘が外れる → upper-arm / forearmのjoint registrationを修正
- 全体がガビガビ → auto traceを捨て、per-part rasterまたはClean Vector Reconstructionへ戻る

完成済みpartまで毎回再生成しません。

## 既存PNG表情差分との関係

既存契約は引き続き有効です。

```text
assets/characters/<name>/<expr>/base.png
assets/characters/<name>/<expr>/mouth/{close,half,open}.png
assets/characters/<name>/<expr>/eyes/{open,close}.png
```

SVG parts-sheet rigはこの仕様を置き換えません。今後、本体レンダラーへ直接SVG animationを統合する場合は、別の利用者向け挙動変更としてcompiler / YAML / render contractを設計します。
