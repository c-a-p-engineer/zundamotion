# Motion Core Camera / Coordinate Space Behavior Contract

更新日: 2026-09-30
対象: Zundamotion 0.2 Motion Core camera track
Issue: #110
前提: PR #107 x/y/scale、PR #112 rotate、PR #114 opacity

この文書は camera motion の world-space / screen-space、既存 background pan/zoom、viewport clipping、A/V timing の正規契約です。first bounded-camera runtime は #110 / PR #116 で実装・CI検証済みです。

関連:

- [Motion Core Behavior Contract](./motion_core_contract.md)
- [Rotate Behavior Contract](./motion_rotate_contract.md)
- [Opacity Behavior Contract](./motion_opacity_contract.md)
- [FFmpeg Filter Mapping](./ffmpeg_filter_mapping.md)
- [Current Project Status](../guides/project_status.md)
- [Compiler Interface](../guides/compiler_interface.md)

## 1. Objective

camera は character movement の別名ではなく、**合成済み world view に対する view transform** とします。

first camera slice の目的:

1. background / insert / image layer / character / face を同じcameraで動かす
2. subtitle 等の screen-space layer を camera の影響から外す
3. 既存 `bg:pan_zoom` を壊さず、責務を分離する
4. current viewport-sized renderer の範囲内で deterministic に実装する
5. Node.js / browser / GPU を必須化しない

## 2. Non-goals

first camera sliceでは次を行いません。

- true 3D camera
- perspective projection
- camera rotation
- depth / parallax
- infinite world canvas
- cameraで「元viewport外にあった未描画pixel」を復元すること
- arbitrary crop expression
- browser scene graph
- automatic migration of `bg:pan_zoom`
- camera persistence across lines
- world-space subtitle
- user-defined layer-space override

## 3. Bounded world viewport

v1 の world extent は output viewport と同じ `W x H` です。

camera transform 前に world layers を `W x H` の1枚へ合成します。

```text
background
+ insert
+ image layers
+ characters
+ face overlays
        ↓
bounded world frame (W x H)
        ↓ camera
output viewport (W x H)
```

重要:

- camera適用前に viewport外へclipされたpixelは復元できない
- cameraは offscreen world discovery mechanism ではない
- characterを完全に画面外へ置き、camera panで後から表示する用途はv1非対応
- この制約を隠して「world canvas実装済み」と表現しない

将来 offscreen reveal が必要になった場合は、overscan/world canvasを別契約として追加します。

## 4. Space classification

### 4.1 World-space

first sliceでcameraの影響を受けるもの:

- prepared background
- background-local effects適用後のbackground
- standard insert image / video
- image layers
- character base
- character face overlays

これらを合成した後にcameraを1回だけ適用します。

### 4.2 Screen-space

cameraの影響を受けないもの:

- subtitles
- badges
- screen UI / screen-fixed annotation

screen-space layerはcamera適用後に合成します。

### 4.3 Screen effects

既存 `screen_effects` はcameraとは別ownerです。

現在のpipelineでは subtitle 合成後に screen effect を適用できるため、screen effect はworldとscreen-space layerの両方へ作用し得ます。

これはcamera space分類と矛盾しません。

```text
world -> camera -> subtitle/badge -> screen effect
```

screen effectの既存挙動をcamera導入時に変更しません。

## 5. Existing pipeline boundary

current clip graphは概念上:

```text
background graph
insert / image layers / characters / faces
        ↓ overlay composition
subtitle
screen effects
final
```

です。

camera first sliceは **overlay composition と subtitle の間** に1stage追加することを基本とします。

```text
background graph
insert / image layers / characters / faces
        ↓ overlay composition
camera view transform
subtitle
screen effects
final
```

個別character x/yへcamera offsetを加算する方式は採用しません。

理由:

- insert / image layer / characterで実装が分散する
- face追従漏れを起こす
- cameraが「view」ではなく個別object rewriteになる
- world/screen境界が曖昧になる

## 6. Public authoring shape

cameraは line-level field とします。

```yaml
camera:
  focus:
    x: 0.65
    y: 0.45
  zoom: 1.35
  move:
    from:
      focus:
        x: 0.50
        y: 0.50
      zoom: 1.00
    start: 0.10
    duration: 1.20
    easing: ease_in_out
    keyframes:
      - at: 0.40
        focus:
          x: 0.58
        zoom: 1.18
        easing: ease_out
      - at: 0.85
        focus:
          x: 0.65
          y: 0.45
        zoom: 1.30
        easing: ease_in
```

final camera values:

- `camera.focus.x`
- `camera.focus.y`
- `camera.zoom`

transient motion:

- `camera.move.from.focus.x`
- `camera.move.from.focus.y`
- `camera.move.from.zoom`
- `camera.move.keyframes[]`

## 7. Neutral camera

camera fieldが無い場合のneutral state:

```text
focus.x = 0.5
focus.y = 0.5
zoom    = 1.0
```

neutral cameraではcamera filterを追加しません。

既存scriptのfilter graphを不要に変更しないことを互換条件とします。

## 8. Focus semantics

focusは normalized coordinateです。

- x=0.0: world frame左端寄り
- x=0.5: 中央
- x=1.0: 右端寄り
- y=0.0: 上端寄り
- y=0.5: 中央
- y=1.0: 下端寄り

domain:

```text
0.0 <= focus.x <= 1.0
0.0 <= focus.y <= 1.0
```

clampしません。範囲外はvalidation errorです。

character `position.x/y` のpx offsetと意味が異なるため、camera authoringで単に `x` / `y` と呼びません。

## 9. Zoom semantics

zoom domain:

```text
1.0 <= zoom <= 4.0
```

- 1.0: neutral
- >1.0: zoom in
- <1.0: v1ではvalidation error

v1でzoom-outを許可しない理由:

- bounded world viewportの外側を埋める意味が未定義
- transparent/black/edge-fillを暗黙選択しない
- low-spec pathでworld canvasを不要に保つ

将来world canvas contract導入後にzoom < 1.0を再評価できます。

## 10. Focus at zoom=1

zoom=1.0ではviewport全体が見えるため、focus値を変えてもobservable imageは変化しません。

これはerrorではありません。

例:

```yaml
focus: {x: 0.2, y: 0.8}
zoom: 1.0
```

はneutral imageと同じ見た目です。

作者の入力を別値へcanonicalizeはしません。cache identityはauthoring configを保持できます。

## 11. Camera interpolation

camera property track:

- `camera.focus.x`
- `camera.focus.y`
- `camera.zoom`

を独立scalar MotionTrackとして扱います。

既存vocabulary:

- linear
- ease_in
- ease_out
- ease_in_out

を再利用します。

sparse waypoint ruleもcharacter Motion Coreと同じです。

例:

```yaml
keyframes:
  - at: 0.3
    zoom: 1.2
  - at: 0.7
    focus: {x: 0.7}
```

なら:

- zoom: start -> zoom@0.3 -> final
- focus.x: start -> focus.x@0.7 -> final
- focus.y: start -> final

です。

省略propertyを人工的hold keyframeへ変換しません。

## 12. Camera persistence

v1 cameraはline-localです。

- `camera`: current lineのview設定
- `camera.move`: transient
- next lineへ自動継承しない
- scene / global camera defaultsはfirst sliceで追加しない
- `camera_persist` は追加しない

camera motionを使うlineでは final values と必要な `move.from` values を明示します。

default previous-camera inferenceは行いません。

## 13. Static camera

moveを持たない:

```yaml
camera:
  focus: {x: 0.65, y: 0.45}
  zoom: 1.4
```

も有効です。

static cameraも world composition後、subtitle前に適用します。

## 14. FFmpeg lowering

first implementationは合成済みworld streamへ1回の view transformをloweringします。

候補:

```text
[world]
zoompan=
  z=<zoom track>:
  x=(iw-iw/zoom)*<focus.x track>:
  y=(ih-ih/zoom)*<focus.y track>:
  d=1:
  s=WxH:
  fps=<output fps>
[camera_view]
```

原則:

- output sizeは常に W x H
- camera filterでline durationを延長しない
- output fpsを既存video fpsへ固定
- camera MotionTrack clockはclip-local
- current implementationの `zoompan` background semanticsと式の意味を共有できるが、ownerは別

actual filter選択はimplementation detailですが、observable semanticsはこのcontractへ従います。

## 15. Background pan/zoom boundary

`bg:pan_zoom` / `bg:ken_burns` はbackground-local effectです。

cameraとは別ownerのまま維持します。

composition order:

```text
background source
  -> fit / normalize
  -> bg:pan_zoom / bg:ken_burns
  -> other world layersをoverlay
  -> camera
  -> screen-space layers
```

両方指定した場合:

- bg pan/zoomはbackgroundだけを動かす
- cameraは合成済みworld全体を動かす
- character / insertはbg pan/zoomには追従しない
- character / insertはcameraには追従する

`bg:pan_zoom` をcameraへ自動変換・aliasしません。

## 16. Character motion boundary

character `move` と camera は独立ownerです。

例:

- characterが右へ移動
- camera focusも右へ移動

した場合、character motionをworld frameへ描画した後、その結果にcameraを適用します。

camera値をcharacter `position.x/y` へ加算しません。

これにより character persistent stateはcameraから独立します。

## 17. Face overlay invariant

face overlayはcamera前のworld compositionに含まれます。

character baseとfaceを別々にcamera transformしません。

```text
character base + face
        ↓ world composition
        ↓ camera once
```

したがって mouth / eyes がcameraからずれる実装は禁止します。

## 18. Insert / image layer invariant

standard insertとimage layerはfirst sliceではworld-spaceです。

cameraを適用すると:

- position
- scale
- opacity
- source content

を含む既存render結果全体がcamera viewに入ります。

screen-fixed insert / image layerをauthoringで選ぶ機能はfirst slice非対応です。

必要性が確認された場合、明示的 `space: screen` 等を別契約で追加します。

## 19. Subtitle invariant

subtitleはscreen-spaceです。

camera focus / zoomが変化しても:

- subtitle baseline
- subtitle box position
- subtitle font size
- screen-relative subtitle coordinates

は変化しません。

ASS / PNGのどちらでも同じです。

camera導入のためにsubtitleをworld streamへ先焼きしません。

## 20. Badge invariant

badgeはscreen-spaceです。

cameraでbadge位置やサイズを変えません。

badge pipelineがclip外の後段にある場合もこの意味を維持します。

## 21. Screen effect boundary

`screen:shake_screen` 等は最終screen writerです。

camera後のscreen-space subtitleを含めて揺らす現在のscreen effect semanticsは維持します。

camera導入を理由に screen effectをworld-onlyへ変更しません。

## 22. GPU / CPU policy

camera first sliceはGPU-nativeを要求しません。

`zoompan` 等のcamera loweringをGPU overlay chainへ安全に混ぜられない場合:

- cameraを含むclipだけCPU compositionへfallbackしてよい
- Node / Chromiumを導入しない
- no-camera clipのGPU pathを変更しない
- capabilityにGPU camera対応を記載しない

正しさと再現性を性能より優先します。

## 23. Validation

cameraが存在する場合:

- mappingであること
- final `focus.x`, `focus.y`, `zoom` はfinite number
- focusは0.0〜1.0
- zoomは1.0〜4.0
- move使用時はduration > 0
- start >= 0
- move easingは既存4種
- keyframe atはstrictly increasing
- `0 < at < duration`
- keyframeは `focus` または `zoom` の少なくとも1propertyを持つ
- unknown propertyはerror
- animated propertyに必要な start valueが無ければerror
- input順を暗黙sortしない
-値を暗黙clampしない

## 24. Partial start values

camera moveで実際に動かすpropertyだけ start valueを要求します。

例:

```yaml
camera:
  focus: {x: 0.7, y: 0.5}
  zoom: 1.0
  move:
    from:
      focus: {x: 0.5}
    duration: 1.0
```

は focus.x motionとして有効です。

focus.y / zoomはstatic final valueを使います。

ただし keyframeでzoomを書くなら `move.from.zoom` が必要です。

## 25. Compatibility

camera fieldが無い既存script:

- camera filterを追加しない
- background effect graphを変更しない
- insert / image layer / character / face位置を変更しない
- subtitle pipelineを変更しない
- GPU/CPU policyを変更しない
- cache/output semanticsを変更しない

## 26. A/V invariant

cameraはvideo view transformのみです。

- line durationを延長しない
- audio timingを変更しない
- subtitle timingを変更しない
- scene transition offsetを変更しない
- target fps / timebaseを変更しない

actual FFmpeg testで duration / representative framesを確認します。

## 27. Cache / reproducibility

cameraにより映像が変わるためcache identityに含めます。

- final focus.x/y
- final zoom
- move.from values
- keyframe order
- keyframe at / values / easing
- start / duration

neutral camera fieldを「field無し」へ暗黙canonicalizeしません。

renderer結果が同じ場合でもauthoring identityは保持できます。

## 28. Compiler / capability

compiled-config v1は additive configurationとしてline-level `camera` を保持できます。

renderer-native:

- zoompan expression
- labels
- fps lowering
- CPU fallback flag

は公開しません。

runtime implementationとtests完了後の現在の capability は:

```json
{
  "motion": {
    "version": 1,
    "character": {
      "multi_keyframe": true,
      "properties": [
        "position.x",
        "position.y",
        "scale",
        "rotate",
        "opacity"
      ]
    },
    "camera": {
      "multi_keyframe": true,
      "properties": ["focus.x", "focus.y", "zoom"],
      "zoom_range": [1.0, 4.0],
      "bounded_world_viewport": true
    }
  }
}
```

へ更新します。

PR #116 の runtime / FFmpeg / build / reproducibility 検証後に camera capability を true にしています。

## 29. Acceptance mapping

| Acceptance | Verification |
| --- | --- |
| world layers move together | background + insert + character representative render |
| subtitle remains screen-fixed | PNG/ASS camera regression |
| bg:pan_zoom stays background-local | composition graph unit + actual render |
| character state unaffected | tracker/cache regression |
| face remains aligned | world composition ordering test |
| focus domain 0..1 | validation |
| zoom domain 1..4 | validation |
| sparse camera keyframes | MotionTrack unit |
| neutral script has no camera filter | graph regression |
| camera clip can CPU fallback | filter policy test |
| A/V duration unchanged | ffprobe integration |
| compiled-config stays v1 | authoring CLI |
| capability truthful | capability test after runtime pass |
| offscreen reveal is not claimed | docs/current-status boundary |

## 30. First runtime slice

Input:

- line-level `camera`
- final focus.x / focus.y / zoom
- optional `camera.move`
- existing 4 easing values

Internal:

- property tracks for focus.x / focus.y / zoom
- one camera stage after world overlay composition
- CPU fallback where required

Output:

- W x H
- existing fps
- screen-space subtitle unaffected
- no offscreen-world recovery

Not included:

- zoom-out
- camera rotation
- persistent camera
- layer `space` authoring
- overscan world canvas
- depth/parallax

## 31. Future world canvas gate

次の要件が必要になった場合、bounded viewport cameraを拡張せず別contractを作ります。

- neutral viewport外のcharacterをcamera panで後から見せる
- zoom < 1.0
- large pan with no crop limitation
- parallax
- world-space subtitles
- explicit world/screen layer authoring

この場合は少なくとも:

- world canvas dimensions
- overscan budget
- existing viewport-relative anchorのworld embedding
- background edge/source expansion policy
- memory/resource bound
- cache identity

を決める必要があります。

この契約無しに巨大なtransparent canvasを暗黙生成しません。

## 32. Decision record

v1 cameraは次を採用します。

1. cameraはcharacter moveの別名ではなくview transform
2. world layerを合成してからcameraを1回適用する
3. subtitle / badgeはscreen-space
4. screen effectはcamera後の既存semanticsを維持する
5. world extentはW x Hのbounded viewport
6. offscreen pixel復元をclaimしない
7. focusはnormalized 0..1
8. zoomは1.0〜4.0、zoom-outは未対応
9. `bg:pan_zoom` はbackground-localの別owner
10. cameraはline-local、persistしない
11. camera clipだけCPU fallback可能
12. capabilityはruntime検証後にのみ公開し、現在は検証済みの bounded camera capability を公開する
