# Motion Core Background Pan/Zoom Integration Contract

更新日: 2026-09-30
対象: Zundamotion 0.2 Motion Core background-local motion
Issue: #117
前提: character Motion Core (#107/#112/#114) と bounded camera (#116)

この文書は、既存 `bg:pan_zoom` / `bg:ken_burns` の単一区間互換を壊さず、background-only motion に複数keyframeとsegment easingを追加する境界を定義します。

関連:

- [Motion Core Behavior Contract](./motion_core_contract.md)
- [Camera / Coordinate Space Contract](./motion_camera_contract.md)
- [FFmpeg Filter Mapping](./ffmpeg_filter_mapping.md)
- [Current Project Status](../guides/project_status.md)
- [YAML Cheatsheet](../../scripts/script_cheatsheet.md)

## 1. Evaluation conclusion

実装します。

理由:

1. background pan/zoom は camera では代替できません。
   - background effect: 背景だけが動く
   - camera: background / insert / image layer / character / face をまとめて動かす
2. 既存ownerはすでに `zoompan` loweringを持ち、MotionTrackを追加してもrenderer layerを増やしません。
3. multi-keyframe + easing は、低スペックnative FFmpeg pathのまま表現量を増やします。
4. cache payloadはauthoring `background_effects` を保持しており、新規keyframeのcache identity追加コストが小さいです。
5. legacy single-segment pathを分離すれば、既存silent clamp / fallback互換を維持できます。

## 2. Non-goals

このsliceでは次を行いません。

- `bg:pan_zoom` を line-level camera のaliasへ変更
- background pan/zoomをcameraへ自動migration
- generic public `motion.targets[]` DSL
- arbitrary frame callback
- browser / Canvas / Remotion runtime
- zoom < 1.0
- camera rotation
- background rotation
- overscan / offscreen world recovery
- existing `bg:shake_bg` のMotionTrack化
- deterministic motion preset
- effect registry全面再設計

## 3. Existing compatibility root

現行入力:

```yaml
background_effects:
  - type: bg:pan_zoom
    zoom:
      from: 1.0
      to: 1.2
    pan:
      from: {x: 0.2, y: 0.5}
      to: {x: 0.8, y: 0.5}
    fps: 30
```

現行observable behavior:

- clip duration全体を1区間としてlinear補間
- `zoom.from/to` と `pan.from/to`
- `zoom` は1.0〜4.0へsilent clamp
- focus x/yは0.0〜1.0へsilent clamp
- parse失敗時はfallback値を使う
- `fps` は1〜120へsilent clamp
- background streamだけへ適用
- character / insert / image layer / subtitleへは直接適用しない

**`keyframes` が無い入力は、このpathをそのまま維持します。**

legacy pathをMotionTrackへ置換して出力式・clamp・fallback semanticsを変えません。

## 4. Multi-keyframe activation gate

新しいstrict Motion Core pathは、effectに **non-empty `keyframes`** が存在する場合だけ有効です。

```yaml
background_effects:
  - type: bg:pan_zoom
    zoom: {from: 1.0, to: 1.25}
    pan:
      from: {x: 0.25, y: 0.50}
      to: {x: 0.70, y: 0.45}

    start: 0.10
    duration: 1.50
    easing: ease_in_out
    keyframes:
      - at: 0.40
        zoom: 1.12
        easing: ease_out

      - at: 1.00
        pan: {x: 0.55}
        zoom: 1.20
        easing: ease_in
```

`start` / `duration` / `easing` が書かれていても `keyframes` が無ければlegacy pathは変更しません。

理由:

過去scriptが未知fieldを含んでいても、今回の追加で既存出力を変えないためです。

## 5. Supported properties

strict multi-keyframe pathのproperty track:

- `zoom`
- `pan.x`
- `pan.y`

domain:

| property | domain |
| --- | --- |
| zoom | finite number, 1.0〜4.0 |
| pan.x | finite number, 0.0〜1.0 |
| pan.y | finite number, 0.0〜1.0 |

範囲外をclampしません。validation errorです。

## 6. Start / final values

multi-keyframe pathでも既存authoring ownerを再利用します。

start/final:

- zoom start: `zoom.from`（既存 `zoom.start` aliasも許可）
- zoom final: `zoom.to`（既存 `zoom.end` aliasも許可）
- pan start: `pan.from`
- pan final: `pan.to`

legacy compatibility shorthand:

- scalar `zoom: 1.25` は start=1.0 / final=1.25 としてmulti-keyframe pathでも許可する
- static `pan: {x: ..., y: ...}` は start=finalとして扱える

ただし、keyframeで実際にanimationするpropertyには必要なstart/final値が解決できなければvalidation errorとします。

### 6.1 Sparse axes

pan.x keyframeだけがある場合:

- pan.xはMotionTrack
- pan.yは既存final/static値
- zoomはzoom keyframe / start-final差分があればMotionTrack、なければstatic

省略axisへ人工的keyframeを追加しません。

## 7. Timing

strict path:

- clock: clip-local
- `start >= 0`
- `duration > 0` を必須
- `keyframes[].at` は `start` からの相対秒
- `0 < at < duration`
- keyframe時刻はinput順でstrictly increasing
- inputを暗黙sortしない
- effect end = `start + duration`

before start:

- start valuesを保持

during:

- MotionTrack interpolation

after end:

- final valuesを保持

motionのためにclip durationを延長しません。

clipがmotion endより短い場合はrender可能範囲まで評価します。

## 8. Easing

v1 vocabularyは既存Motion Coreと同じです。

- `linear`
- `ease_in`
- `ease_out`
- `ease_in_out`

意味:

- keyframeの `easing` は「直前の同property pointからそのkeyframeへ到達するsegment」
- keyframe easing省略時はtop-level `easing`
- 最後のkeyframeからfinal値までもtop-level `easing`

legacy no-keyframe pathは従来どおりlinearです。
今回、legacy pathで `easing` を新たに解釈しません。

## 9. Keyframe shape

```yaml
keyframes:
  - at: 0.3
    zoom: 1.1

  - at: 0.7
    pan: {x: 0.6}

  - at: 1.0
    pan: {y: 0.4}
    zoom: 1.2
    easing: ease_out
```

各keyframe:

- mapping必須
- `at` 必須
- `zoom` / `pan` の少なくとも1つ
- `pan` はmapping
- `pan` はx/yの少なくとも1つ
- unknown propertyはvalidation error
- valuesはstrict domain validation

## 10. FFmpeg lowering

strict pathも existing background `zoompan` ownerを使います。

概念:

```text
[prepared_background]
  -> zoompan(
       z=<zoom MotionTrack>,
       x=(iw-iw/zoom)*<pan.x MotionTrack>,
       y=(ih-ih/zoom)*<pan.y MotionTrack>,
       d=1,
       s=WxH,
       fps=<resolved fps>
     )
[background_motion]
```

MotionTrack time variableは `zoompan` output frame indexから算出したclip-local秒を使います。

```text
time = on / fps
```

character / cameraで確立したsegment easing式を再利用します。

## 11. FPS

legacy no-keyframe path:

- 現行 `effect.fps` parsing / default / clampを変更しない

strict multi-keyframe path:

- renderer output fpsを既定clockとする
- explicit `effect.fps` を許可する場合はfinite 1〜120をstrict validationする
- silent clampしない

first implementationではresolverへoutput fpsを渡せるようにし、未指定時30固定を新規pathへ持ち込まないことを推奨します。

## 12. Composition / owner boundary

background pan/zoomはbackground-local ownerです。

順序:

```text
background source
  -> fit / normalize
  -> bg:pan_zoom / bg:ken_burns
  -> other background effects in configured order
  -> insert / image layers / character / face
  -> line-level camera
  -> subtitle / badge
  -> screen effects
```

cameraとの組み合わせ:

- background pan/zoom: 背景だけを動かす
- camera: 合成済みworld全体を動かす
- 自動統合・打ち消し・最適化しない

## 13. Alias boundary

`bg:pan_zoom` と `bg:ken_burns` は現在同じresolver ownerです。

multi-keyframe pathでも同じcontractを共有できます。

ただし:

- camera aliasにはしない
- type名を自動rewriteしない
- capabilityはbackground pan/zoom ownerとして表現する

## 14. Validation placement

legacy no-keyframe effectは既存互換のため新しいhard validationを要求しません。

non-empty `keyframes` を持つ `bg:pan_zoom` / `bg:ken_burns` だけ、script validationでstrictに検証します。

検証対象:

- effect mapping
- start
- duration
- easing
- keyframe list / ordering / at
- zoom / pan values
- required start/final property
- explicit fps when present
- unknown multi-keyframe control field

他のbackground effectへvalidation責務を拡張しません。

## 15. Cache / reproducibility

talk / wait cache payloadは現在 `background_effects` authoring configを保持します。

そのため:

- keyframe order
- at
- values
- easing
- start / duration

はauthoring dictによりcache identityへ入ります。

renderer-native MotionTrack / expressionをcache keyへ重複追加しません。

legacy no-keyframe cache payload shapeを変更しません。

## 16. A/V invariant

background motionはvideo transformだけです。

- clip durationを延長しない
- audio timingを変更しない
- subtitle timingを変更しない
- camera timingを変更しない
- scene transition offsetを変更しない
- target output fps / timebaseを変更しない

actual FFmpeg regressionでdurationを確認します。

## 17. CPU / GPU policy

現状、background effectが存在するclipはfilter policyでCPU-compatible pathへfallbackします。

multi-keyframe追加はこの方針を変更しません。

このsliceでは:

- GPU-native background MotionTrackを要求しない
- no-background-effect clipのGPU policyを変更しない
- capabilityにGPU対応を記載しない

## 18. Compiled-config

compiled-config v1はauthoring fieldsをそのまま保持できます。

保持対象:

- legacy zoom / pan
- start / duration / easing
- keyframes

公開しない:

- MotionTrack内部frame
- zoompan expression
- FFmpeg label
- resolved time variable
- CPU fallback flag

format versionは1のままです。

## 19. Capability

runtime + tests完了後だけ、`motion` capabilityへbackground ownerをadditiveに追加します。

候補:

```json
{
  "motion": {
    "version": 1,
    "background": {
      "pan_zoom_multi_keyframe": true,
      "effect_types": ["bg:pan_zoom", "bg:ken_burns"],
      "properties": ["pan.x", "pan.y", "zoom"],
      "easings": ["linear", "ease_in", "ease_out", "ease_in_out"],
      "zoom_range": [1.0, 4.0],
      "focus_range": [0.0, 1.0],
      "legacy_single_segment_compatible": true
    }
  }
}
```

contract PRだけでは追加しません。

## 20. Acceptance mapping

| Acceptance | Verification |
| --- | --- |
| legacy no-keyframe path unchanged | exact expression/unit regression |
| legacy clamp/fallback unchanged | compatibility unit regression |
| strict new domain | validation tests |
| sparse zoom/pan axes | MotionTrack unit |
| segment easing | expression/evaluation unit |
| background-only motion | actual FFmpeg representative frames |
| character/insert not directly moved by background effect | composition regression |
| camera remains after background motion | graph + actual combined render |
| duration unchanged | ffprobe integration |
| cache identity changes with keyframes | cache test |
| compiled-config stays v1 | authoring CLI |
| capability truthful | capability test after runtime green |
| no-effect path unchanged | existing CI/render regression |

## 21. Minimal implementation slice

Change:

- strict multi-keyframe validator for `bg:pan_zoom` / `bg:ken_burns`
- MotionTrack-backed background zoom / pan.x / pan.y lowering
- renderer output fps passed to new path
- tests / sample / docs / capability after runtime green

Do not change:

- legacy no-keyframe lowering
- background-local owner
- camera semantics
- other background effects
- character Motion Core
- generic target model

## 22. Decision record

1. Multi-keyframe background pan/zoom is worth implementing because it adds background-only motion not expressible by camera.
2. Legacy single-segment behavior remains a separate compatibility path.
3. `keyframes` presence is the strict-path activation gate.
4. New path reuses MotionTrack and existing `zoompan` owner.
5. New path is strict; legacy path keeps silent clamp/fallback.
6. Background motion remains before world overlays and before camera.
7. No generic motion DSL is introduced.
8. Capability is published only after runtime CI and actual FFmpeg verification.
