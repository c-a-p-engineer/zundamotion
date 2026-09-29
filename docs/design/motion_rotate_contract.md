# Motion Core Rotate Behavior Contract

更新日: 2026-09-30
対象: Zundamotion 0.2 Motion Core rotate track
Issue: #108
前提: PR #107 の x / y / scale multi-keyframe vertical slice

この文書は character rotate を Motion Core へ追加する前に、外部から観測できる挙動、既存 transform との合成規則、pivot / canvas 安全性を固定します。

関連:

- [Motion Core Behavior Contract](./motion_core_contract.md)
- [FFmpeg Filter Mapping](./ffmpeg_filter_mapping.md)
- [Current Project Status](../guides/project_status.md)
- [Compiler Interface](../guides/compiler_interface.md)

## 1. Objective

rotate を既存 x / y / scale と同じ property-track 時間モデルへ追加します。

優先順位:

1. PR #107 の x / y / scale 互換性を壊さない
2. character anchor を回転 pivot として維持する
3. 動的角度でも clipping / canvas size jump を起こさない
4. face overlay を character 本体と同じ transform へ追従させる
5. native Python + FFmpeg path を維持する

## 2. Non-goals

最初の rotate slice では次を行いません。

- opacity
- camera
- 3D rotation / perspective
- arbitrary transform matrix
- user-defined pivot
- shortest-path angle inference
- physics / spring rotation
- existing foreground overlay rotate plugin の Motion Core 移行
- browser runtime

## 3. Public authoring shape

rotate の最終値は line-local character field `rotate` が所有します。

```yaml
characters:
  - name: copetan
    position: {x: 120, y: -32}
    scale: 0.9

    # この line の最終回転角。degree。
    rotate: 0

    move:
      from:
        x: -240
        y: -32
        scale: 0.7
        rotate: -8
      start: 0.1
      duration: 1.0
      easing: ease_in_out
      keyframes:
        - at: 0.30
          x: -80
          rotate: 12
          easing: ease_out
        - at: 0.70
          scale: 1.0
          rotate: -4
          easing: ease_in
```

`move.keyframes[].rotate` は x / y / scale と同じ intermediate waypoint です。

## 4. Persistence

v1 の `rotate` は line-local render transform であり、character persistent state には追加しません。

- `position` / `scale`: 従来どおり persistent state
- `rotate`: line-local final transform
- `move.from.rotate`: transient start value
- `move.keyframes[].rotate`: transient intermediate values

`characters_persist: true` でも rotate は次 line へ自動継承しません。

rotate track を使う line は:

- final `rotate` を明示する
- start `move.from.rotate` を明示する

前 line の rotate を暗黙 start value として推測しません。

## 5. Unit and direction

user-facing unit は degree です。

- `0`: 無回転
- 正: 時計回り
- 負: 反時計回り

FFmpeg `rotate` へ lower するときだけ radians へ変換します。

値は finite number なら 360 度を超えても許可します。

```yaml
rotate: 360
move:
  from: {rotate: 0}
```

は 1 回転を意味し得るため、値を 0〜360 に canonicalize しません。

## 6. Angle interpolation

rotate は通常の scalar property として数値補間します。

- sparse waypoint rule は x / y / scale と同じ
- easing semantics も同じ
- angle wrapping を行わない
- shortest path を推測しない

例:

```yaml
move:
  from: {rotate: 350}
  duration: 1.0
  keyframes: []
rotate: 10
```

は `350 -> 10` を数値として補間します。

短い時計回り +20 度を意図する場合、作者が `350 -> 370` と書きます。

## 7. Pivot semantics

v1 の rotate pivot は character `anchor` と同一です。

例:

- `bottom_center`: 足元中央を pivot
- `middle_center`: 画像中央を pivot
- `top_left`: 左上を pivot

別の `pivot` field は v1 で追加しません。

理由:

- placement と rotation の基準点を分離すると authoring が急に複雑になる
- x / y motion と rotate を同じ world anchor 上で合成できる
- bottom-center character で足元を固定した傾き表現が可能

## 8. Transform order

v1 の概念順序は次です。

```text
source character / face layer
  -> color / source preprocessing
  -> flip
  -> scale around character anchor
  -> fixed pivot-safe transparent canvas
  -> rotate around character anchor
  -> x / y placement of the anchor
  -> existing character x/y effects
  -> scene composition
```

uniform scale と rotate は同じ anchor を共有します。

enter / leave slide や char:shake / bob / sway は position writer であり、rotate property writerではありません。
そのため v1 では rotate と併用できます。

## 9. Fixed rotation canvas

動的 rotate では output dimensions を angle ごとに変更しません。

1 clip 内で固定サイズの透明 rotation canvas を使います。

必要条件:

- scale track の最大倍率を考慮する
- character anchor を rotation canvas の回転中心へ置く
- anchor から source rectangle 四隅までの最大距離を cover する
- 任意の rotate keyframe angle で clipping しない
- angle 変化で overlay width / height が変化しない
- transparent fill を維持する

canvas の厳密な丸め・安全marginは implementation detail とします。

FFmpeg `rotate` の `out_w` / `out_h` は設定時評価であるため、per-frame angle に追従した可変サイズを前提にしません。

## 10. Anchor placement invariant

rotate 有無で character anchor の world position を変えません。

同じ:

```yaml
anchor: bottom_center
position: {x: 100, y: -32}
```

なら、rotate track を追加しても pivot の world coordinate は同じでなければなりません。

透明 canvas が拡大したことを理由に character 全体が上下左右へずれる実装は禁止します。

## 11. Face overlay invariant

mouth / eyes 等の face overlay は character base と同じ:

- scale
- pivot
- rotate
- x / y placement

を使用します。

base character だけが回転し、face overlay が未回転で残る出力は禁止します。

実装途中で face overlay 追従を保証できない場合は、rotate + active face animation を明示的に reject し、silent degradation は行いません。

正式な rotate capability を true にする完了条件では face overlay 追従を要求します。

## 12. Existing rotate effect boundary

現在の built-in overlay plugin `rotate` は foreground / overlay effect pipeline の filter です。

character Motion Core rotate と同一 owner ではありません。

v1:

- existing overlay `effects: [{type: rotate, ...}]` の挙動を変更しない
- overlay rotate を character MotionPlan へ自動移行しない
- character `effects` の `char:shake_char` / `char:bob_char` / `char:sway_char` と rotate track は別 property として共存可能
- 同じ character rotate property を別 writer が書く新機能が追加された場合は validation error を基本とする

暗黙 precedence は導入しません。

## 13. Validation

rotate track 使用時:

- character final `rotate` は必須
- `move.from.rotate` は必須
- どちらも finite number
- `move.keyframes[].rotate` は finite number
- easing / at / ordering は既存 Motion Core rule
- unknown property rule は既存どおり

invalid:

```yaml
# final rotate missing
move:
  from: {rotate: -5}
  duration: 1.0
  keyframes:
    - {at: 0.5, rotate: 10}
```

```yaml
# start rotate missing
rotate: 0
move:
  duration: 1.0
  keyframes:
    - {at: 0.5, rotate: 10}
```

```yaml
# non-numeric
rotate: "10deg"
move:
  from: {rotate: 0}
  duration: 1.0
```

## 14. Compatibility

rotate field / rotate keyframe が無い既存 script:

- current x / y expression を維持
- current scale canvas path を維持
- additional rotate filter を追加しない
- cache/output semanticsを変更しない

既存 overlay rotate plugin も変更しません。

## 15. A/V invariant

rotate は video transform のみです。

- line durationを延長しない
- audio timingを変更しない
- subtitle timingを変更しない
- scene transition offsetを変更しない
- fps / timebaseを変更しない

## 16. Cache / reproducibility

rotate により映像が変わるため、既存 motion cache identity に次を含めます。

- final rotate
- move.from.rotate
- rotate keyframe order
- at
- value
- easing
- start / duration

0 と 360 は interpolation pathが異なり得るため、同一値へ canonicalize しません。

## 17. Compiler / capability

compiled-config v1 は additive configuration として:

- character `rotate`
- `move.from.rotate`
- `move.keyframes[].rotate`

を保持できます。

renderer-native radians expression / canvas geometryは公開しません。

runtime implementation と tests が完了した後だけ capability を:

```json
{
  "motion": {
    "version": 1,
    "character": {
      "multi_keyframe": true,
      "properties": ["position.x", "position.y", "scale", "rotate"]
    },
    "camera": {
      "multi_keyframe": false
    }
  }
}
```

へ更新します。

contract PR だけでは rotate を capability に追加しません。

## 18. FFmpeg lowering constraint

FFmpeg `rotate` は:

- angle expressionをframeごとに評価可能
- angleはradian
- positive angleはclockwise
- output width / height expressionはconfiguration時に評価

という前提で lowering します。

そのため fixed transparent canvas を必須設計とします。

## 19. Acceptance mapping

| Acceptance | Verification |
| --- | --- |
| positive degree is clockwise | pure lowering + actual frame |
| no shortest-path inference | MotionTrack numeric unit |
| anchor pivot stays fixed | geometry unit + representative frames |
| scale + rotate compose | fixed-canvas unit + actual render |
| no clipping | 90/135/180 degree representative frames |
| face follows rotate | face overlay FFmpeg integration |
| legacy no-rotate unchanged | existing movement + render regression |
| invalid start/final rejected | validation tests |
| cache changes on rotate | cache fingerprint |
| compiled-config remains v1 | authoring CLI test |
| capability truthful | capability test after implementation |
| A/V duration unchanged | FFmpeg integration / probe |

## 20. Minimal implementation slice

Input:

- line-local character `rotate`
- `move.from.rotate`
- optional `move.keyframes[].rotate`
- existing easing vocabulary

Internal:

- existing MotionTrack with property `rotate`
- pure rotation canvas geometry helper
- degree -> radian FFmpeg expression lowering

Output:

- fixed transparent pivot-safe character stream
- base + face transforms kept aligned
- existing x / y overlay motion preserved

Not included:

- opacity
- camera
- pivot DSL
- overlay plugin migration
- preset composition

## 21. Decision record

v1 rotate は次を採用します。

1. rotate は x / y / scale と同じ scalar MotionTrack
2. user-facing unitはdegree、positiveはclockwise
3. shortest-path inferenceをしない
4. pivotはcharacter anchor
5. rotateはline-localでpersistしない
6. scale -> pivot-safe canvas -> rotate -> placement の責務順を採用
7. fixed canvasでangle-dependent dimension jumpを防ぐ
8. face overlayは同じtransformへ追従させる
9. existing overlay rotate effectは別ownerとして維持する
10. capabilityはruntime検証後だけ公開する
