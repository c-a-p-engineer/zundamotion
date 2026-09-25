# Motion Core Behavior Contract

更新日: 2026-09-25
対象: Zundamotion 0.2 Motion Core
Issue: #102

この文書は、Zundamotion の Motion Core が外部から観測できる挙動と、既存 `move` から内部 Motion Model へ移行する境界を定義します。

実装構造そのものは固定しません。class名、module名、FFmpeg式の具体形は Technical Plan / 実装側の責務です。

関連:

- [Product Roadmap](../guides/product_roadmap.md)
- [Current Project Status](../guides/project_status.md)
- [YAML Cheatsheet](../../scripts/script_cheatsheet.md)
- [Compiler Interface](../guides/compiler_interface.md)
- [FFmpeg Filter Mapping](./ffmpeg_filter_mapping.md)
- [Video Direction and QA](../guides/video_direction_and_qa.md)

## 1. Objective

0.2 Motion Core の目的は、ブラウザruntimeや任意frame callbackを導入せず、現在の Python + FFmpeg native path のまま複数keyframeとeasingを扱える共通時間モデルを作ることです。

優先順位:

1. 既存 `move` の互換性
2. A/V durationを変えないこと
3. deterministic / cacheableであること
4. FFmpegへloweringできること
5. 将来の rotate / opacity / camera / preset を同じ内部モデルへ載せられること

## 2. Non-goals

0.2 の最初の縦切りでは、次を実装完了条件にしません。

- Remotion / Chromium / Node.js の導入
- Web Canvas / WebGL runtime
- arbitrary JavaScript / Python frame callback
- cubic-bezier editor
- physics simulation
- particle system
- SVG rig runtimeそのもの
- true 3D camera
- 既存 character effects の全面置換
- compiled-config v1 の無条件な破壊変更

## 3. Compatibility root

現在の `move` 契約は次です。

```yaml
characters:
  - name: copetan
    position: {x: 240, y: -32}
    scale: 0.82
    move:
      from: {x: -420, y: -32, scale: 0.60}
      start: 0.2
      duration: 0.8
      easing: ease_out
```

意味:

- `position` / `scale` は移動後の最終状態
- `move.from` は一時的な開始状態
- `move.start` はline clip開始からの遅延秒数
- `move.duration` は移動時間
- `move.easing` は補間
- `characters_persist: true` では直前stateから `move.from` を補完できる
- `move` 自体は次lineへ永続化しない
- 最終 `position` / `scale` は通常のcharacter stateとして永続化できる

Motion Core はこの意味を維持します。

## 4. Architecture contract

Motion Core は user-facing YAML と renderer-specific FFmpeg expression を直接同一視しません。

```text
legacy/new authoring input
        ↓
validation / resolution
        ↓
renderer-native MotionPlan
        ↓
property tracks
        ↓
FFmpeg lowering
```

`compiled-config` は現在「解決済み・検証済みconfiguration」であり renderer-native IR ではありません。

そのため、Motion Core の内部 `MotionPlan` を `compiled-config v1` の公開形式としてそのまま露出することを必須にしません。

## 5. Internal MotionPlan semantic model

内部モデルは最低限、次の意味を表現できる必要があります。

```text
MotionPlan
  target
  target_space
  tracks[]
    property
    keyframes[]
      time
      value
      easing_to_here
```

### 5.1 Target

最低限:

- character
- object / overlay
- camera（将来）

同一targetの識別子はrender中に安定していなければなりません。

### 5.2 Target space

- `object`: 対象そのもののtransform
- `camera`: world-spaceを観測するview transform
- `screen`: 字幕・badge等の画面固定要素

0.2最初の縦切りは character/object motion を実装対象とし、cameraは意味境界だけ先に固定します。

## 6. Property model

内部 MotionPlan は次を表現できる設計とします。

| property | unit / domain | 0.2 first vertical slice | note |
| --- | --- | --- | --- |
| `position.x` | px, finite number | 実装対象 | anchorからのoffset |
| `position.y` | px, finite number | 実装対象 | anchorからのoffset |
| `scale` | finite number > 0 | 実装対象 | uniform scale |
| `rotate` | degree, finite number | model対象 / 実装後続 | canvas size / pivot設計が必要 |
| `opacity` | 0.0〜1.0 | model対象 / 実装後続 | alpha path |

任意文字列式を新しいmulti-keyframe値として許可しません。

既存single-moveで互換上許される文字列表現は legacy compatibility path に残せますが、新規multi-keyframe interpolationは数値を要求します。

## 7. Time semantics

### 7.1 Clock

Motionの時刻はline clipのlocal timeを基準とします。

- line clip開始 = `t=0`
- audio / subtitle / motionは同じclip duration上に存在する
- motionのためにline durationを自動延長しない

### 7.2 Existing move fields

- `move.start >= 0`
- `move.duration > 0` when enabled
- end = `start + duration`

現在の単一補間では:

```text
before start          -> from
start ... end         -> interpolate(from, target)
after end             -> target
```

### 7.3 Clip shorter than motion

TTS等で確定したclip durationが `move.start + move.duration` より短い場合:

- clip自体をmotionのために延長しない
- render可能な範囲までmotionを評価する
- 次lineのpersistent stateは従来どおり解決済みcharacter stateを基準にする
- diagnosticでmotion truncationを観測可能にすることを推奨する

これは現行 `move` の互換性を優先するため、初期実装でhard errorにはしません。

## 8. Multi-keyframe authoring: minimal extension

最初の公開拡張は、新しい巨大DSLを追加せず、既存 `move` をmulti-keyframe対応へ拡張することを第一候補とします。

```yaml
characters:
  - name: copetan

    # 最終state。従来と同じ。
    position: {x: 240, y: -32}
    scale: 0.82

    move:
      from: {x: -420, y: -32, scale: 0.60}
      start: 0.2
      duration: 1.0
      easing: ease_in_out

      # startからの相対秒。中間点のみ。
      keyframes:
        - at: 0.25
          x: -180
          y: -70
          easing: ease_out

        - at: 0.65
          x: 40
          y: -20
          scale: 0.90
          easing: ease_in_out
```

この例は内部的にproperty別trackへloweringします。

```text
position.x:
  start: -420
  at .25: -180
  at .65: 40
  end 1.0: 240

position.y:
  start: -32
  at .25: -70
  at .65: -20
  end 1.0: -32

scale:
  start: .60
  at .65: .90
  end 1.0: .82
```

## 9. Why keyframes are intermediate waypoints

`position` / `scale` を最終stateとして扱う既存契約を維持するため、`move.keyframes` は **中間waypoint** と定義します。

これにより:

- legacy `move.from -> position/scale` はそのまま1segment MotionPlanになる
- `characters_persist` のstate modelを二重化しない
- `move` が一時命令である現在の原則を維持できる
- 最終stateを `motion` 内とcharacter本体へ二重記述しなくてよい

## 10. Keyframe validation

`move.keyframes` が存在する場合:

- listであること
- 各要素はmappingであること
- `at` は必須
- `at` はfinite number
- `0 < at < move.duration`
- `at` はstrictly increasing
- duplicate timeは禁止
- 少なくとも `x`, `y`, `scale` の1つを持つ
- `x` / `y` はfinite number
- `scale > 0`
- 未知propertyはvalidation error
- easingは許可されたvocabularyのみ

入力順を暗黙sortしません。

理由:
作者の誤記を「たまたま動く」状態に変換すると、再現性より意図推定が優先されるためです。

## 11. Sparse waypoint rule

中間keyframeでpropertyが省略された場合、その時刻にそのpropertyのkeyframeは存在しないものとします。

例:

```yaml
keyframes:
  - {at: 0.3, x: -100}
  - {at: 0.6, y: -80}
```

この場合:

- x は start -> x@0.3 -> final x
- y は start -> y@0.6 -> final y

省略propertyを直前値で人工的に固定するkeyframeへ変換しません。

## 12. Easing semantics

v1 vocabulary:

- `linear`
- `ease_in`
- `ease_out`
- `ease_in_out`

既存 `move.easing` と同じ集合です。

### 12.1 Intermediate keyframe

keyframeの `easing` は「直前の同property keyframeから、そのkeyframeへ到達するsegment」のeasingです。

### 12.2 Final segment

最後の中間keyframeから最終 `position` / `scale` へのsegmentは `move.easing` を使います。

### 12.3 Missing intermediate easing

中間keyframeに `easing` が無い場合も `move.easing` を使います。

この規則により、top-level easingはsegment defaultとして後方互換に使えます。

## 13. Legacy lowering

keyframesが無い既存move:

```yaml
position: {x: 240, y: -32}
move:
  from: {x: -420, y: -32}
  start: 0.2
  duration: 0.8
  easing: ease_out
```

は、意味上次のtrackへloweringされます。

```text
position.x:
  t=.2  value=-420
  t=1.0 value=240 easing_to_here=ease_out

position.y:
  t=.2  value=-32
  t=1.0 value=-32 easing_to_here=ease_out
```

既存YAMLを新形式へ書き換えることは要求しません。

## 14. Previous-state resolution

`characters_persist: true` で `move.from` が省略される既存挙動を維持します。

- start x/y: previous resolved character position
- start scale: previous resolved scale when needed
- final x/y/scale: current lineのresolved character state

previous stateが存在せず、必要なstart propertyも `move.from` に無い場合はvalidation/render errorとします。

推測で0や1へ置き換えません。

## 15. State persistence

Motion Coreはcharacter stateとmotion commandを分離します。

- character `position` / `scale`: state
- `move`: transient command
- `move.keyframes`: transient command
- MotionPlan: transient render plan

`characters_persist: true` の次lineへ残るのは、これまでどおりcurrent lineで解決されたcharacter stateです。

中間keyframe値をpersistent stateへ書き込みません。

これにより、clipがmotion途中で終了しても、次lineのstate semanticsは既存と同じです。

## 16. rotate / opacity

内部MotionPlanは将来 `rotate` / `opacity` trackを持てるようにしますが、最初の `move.keyframes` 公開schemaへ無理に追加しません。

理由:

- rotateはpivot / transparent canvas / bounding boxとの責務を持つ
- opacityはfade / enter / leaveとの合成順序を決める必要がある
- 現在のcharacter persistent stateにはrotate / opacityが正式なstate fieldとして存在しない

追加時はそれぞれBehavior Contract差分を作り、既存effectとの競合規則を先に決めます。

## 17. Composition rules

v1では同じpropertyへ複数のMotion Core writerを暗黙合成しません。

例:

- explicit keyframe track + presetが同じ `position.x` を同一区間で書く
- 2つのpresetが同じ `scale` を同時に書く

この場合、優先順位を推測せずvalidation errorを基本とします。

将来compositionを導入する場合は、少なくとも次を明示します。

- replace
- add
- multiply

ただしv1に早期導入しません。

## 18. Existing effects boundary

現在の:

- `char:shake_char`
- `char:bob_char`
- `char:sway_char`
- enter / leave
- fade
- background pan / zoom

を0.2初期で自動的にMotion Coreへmigrationしません。

既存挙動を維持しつつ、内部MotionPlanが安定した後に統合利益を評価します。

特に「同時に動く」ことと「同じownerへ統合すべき」ことを同一視しません。

## 19. Camera semantics

camera motion は character motion の別名ではありません。

将来のcamera trackは概念上:

```text
world layers
  background
  world-space insert
  characters
      ↓ camera transform
screen-space layers
  subtitles
  badges
  screen UI
```

を基本とします。

ただし現在のlayer systemには全assetの world/screen space分類がないため、camera implementationをmulti-keyframe vertical sliceへ混ぜません。

`bg:pan_zoom` を「camera」と改名するだけの変更もしません。

## 20. Preset semantics

presetは独立rendererではなく、deterministicなMotionPlan生成器とします。

候補:

- breathe
- float
- nod
- head_tilt
- pop
- bounce
- shake
- slide_in / slide_out
- emphasis
- gentle_zoom

同じ入力parameterとclip contextから同じMotionPlanを作る必要があります。

乱数を使う場合は再現性契約に従うstable seedを必要とします。

presetを arbitrary FFmpeg filter文字列として公開しません。

## 21. A/V invariant

Motion Coreは映像transformであり、通常はaudio timelineを変更しません。

必須Invariant:

- motion追加だけでline durationを変えない
- audio start/endを変えない
- scene transition offsetを変えない
- subtitle timingを変えない
- fps / timebase変更を暗黙に行わない
- motion無しの既存YAMLは意味上同じ出力を維持する

## 22. Cache / reproducibility contract

Motion設定は映像結果へ影響するため、該当するscene / clip cache identityへ含まれなければなりません。

最低条件:

- keyframe順序
- at
- value
- easing
- start
- duration
- resolved from / final stateのうち出力へ影響する値

canonical化後の同じ意味入力は同じcache identityを作ることを目指します。

Python process-randomized `hash()` を利用しません。

## 23. Compiler / capabilities impact

### 23.1 compiled-config

0.2 first vertical sliceでは:

- existing `move` shapeを破壊しない
- `move.keyframes` を解決済みconfigurationとして保持できる
- renderer-native FFmpeg expressionをcompiled-configへ露出しない

compiled-configの意味が変わる破壊変更が必要になった場合はformat versionを上げます。

### 23.2 capabilities

Motion Core実装後は machine-readable capability に、少なくとも次を公開できる形を目指します。

```json
{
  "motion": {
    "version": 1,
    "character": {
      "multi_keyframe": true,
      "properties": ["position.x", "position.y", "scale"],
      "easings": ["linear", "ease_in", "ease_out", "ease_in_out"]
    },
    "camera": {
      "multi_keyframe": false
    }
  }
}
```

実装していないpropertyをcapabilityでtrueにしません。

## 24. Invalid cases

少なくとも次をvalidation errorにします。

```yaml
# duplicate / non-increasing
keyframes:
  - {at: 0.4, x: 10}
  - {at: 0.4, x: 20}
```

```yaml
# outside duration
duration: 1.0
keyframes:
  - {at: 1.2, x: 10}
```

```yaml
# endpoint should remain owned by from / final state
duration: 1.0
keyframes:
  - {at: 0.0, x: 10}
```

```yaml
# no animated property
keyframes:
  - {at: 0.4, easing: ease_out}
```

```yaml
# unsupported interpolation input
keyframes:
  - {at: 0.4, x: "(W-w)/2"}
```

```yaml
# invalid scale
keyframes:
  - {at: 0.4, scale: 0}
```

## 25. Minimal vertical slice

最初の実装単位は次へ限定します。

### Input

- existing character `move`
- optional `move.keyframes`
- x / y / scale
- existing four easings

### Internal

- immutable/pure MotionTrack representation
- legacy `move` lowering
- multi-keyframe lowering

### Output

- FFmpeg expressions for x / y
- dynamic scale expression
- current transparent fixed-canvas safetyを維持

### Not in first slice

- rotate
- opacity
- camera
- preset
- generic public `motion` DSL
- effects migration

## 26. Acceptance mapping

| Acceptance | Verification |
| --- | --- |
| legacy move unchanged | existing movement tests + representative render regression |
| 3+ waypoint x/y works | unit expression tests + actual render representative frames |
| sparse x/y waypoint works | pure MotionPlan unit test |
| scale keyframes work | dynamic canvas unit + actual render |
| easing per segment works | expression/plan unit tests at boundary/midpoints |
| duplicate/out-of-order rejected | validation tests |
| invalid numeric/domain rejected | validation tests |
| state persistence unchanged | CharacterTracker regression |
| cache changes when motion changes | scene/clip cache fingerprint test |
| no motion preserves cache/output semantics | existing regression |
| A/V duration unchanged | FFmpeg integration / probe |
| capability truthful | authoring CLI test |

## 27. Representative visual QA

actual renderでは最低限:

```text
before motion start
first segment midpoint
intermediate keyframe
next segment midpoint
motion end
adjacent next line
```

を確認します。

特に:

- overlayがframe外へ不意に飛ばない
- scale canvasでanchorが飛ばない
- keyframe境界で1frame jumpしない
- face animation overlayがcharacter motionへ追従する
- characters_persistの次line開始位置が期待stateと一致する

## 28. Migration policy

### Existing scripts

変更不要です。

### New multi-keyframe scripts

`move.keyframes` をopt-inで利用します。

### Future generic motion DSL

rotate / opacity / camera / preset等で `move` の責務を超える必要がEvidenceとして出た場合、generic `motion` DSLを別契約として導入できます。

その際も、既存 `move` はcompatibility inputとして同じMotionPlanへloweringできる状態を維持します。

## 29. Decision record

0.2開始時点では、次を採用します。

1. public APIをいきなり全面刷新しない
2. まず既存 `move` にmulti-keyframeを追加する
3. renderer内部ではproperty trackへ一般化する
4. rotate / opacity / cameraはinternal model上の拡張先として予約し、最初のsliceへ混ぜない
5. presetはMotionPlanのsugarとし、独立render pathにしない
6. Remotion / browser runtimeをMotion Coreの前提にしない

## 30. Re-evaluation triggers

generic `motion` DSLを前倒しで検討するのは、次のいずれかが具体化した場合です。

- character以外の複数targetへ同じtrack authoringが必要
- rotate / opacityの利用が頻出し `move` 名称が明確に不適切
- camera trackをuser-facingに公開する
- preset compositionのためtarget/property指定が不可避
- legacy move拡張のvalidation分岐がgeneric modelより複雑になる

「将来使いそう」だけでは移行理由にしません。
