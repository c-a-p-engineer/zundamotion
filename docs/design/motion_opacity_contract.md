# Motion Core Opacity Behavior Contract

更新日: 2026-09-30
対象: Zundamotion 0.2 Motion Core opacity track
Issue: #109
前提: PR #107 の x / y / scale、PR #112 の rotate

この文書は character opacity を Motion Core へ追加する前に、source alpha、enter / leave fade、face overlay、永続状態との合成規則を固定します。

関連:

- [Motion Core Behavior Contract](./motion_core_contract.md)
- [Rotate Behavior Contract](./motion_rotate_contract.md)
- [FFmpeg Filter Mapping](./ffmpeg_filter_mapping.md)
- [Current Project Status](../guides/project_status.md)
- [Compiler Interface](../guides/compiler_interface.md)

## 1. Objective

opacity を既存 x / y / scale / rotate と同じ property-track 時間モデルへ追加します。

優先順位:

1. source PNG alpha を破壊しない
2. 既存 enter / leave fade の見た目を維持する
3. face overlay と base character の濃度を一致させる
4. alpha writer の precedence を暗黙化しない
5. native Python + FFmpeg path を維持する

## 2. Non-goals

最初の opacity slice では次を行いません。

- camera
- blend mode
- foreground overlay opacity の Motion Core 統合
- arbitrary alpha expression
- opacity の永続state化
- CSS / browser compositing model
- mask animation
- per-channel RGB animation
- motion preset

## 3. Public authoring shape

opacity の最終値は line-local character field `opacity` が所有します。

```yaml
characters:
  - name: copetan
    position: {x: 120, y: -32}
    scale: 0.9

    # この line の最終不透明度。0.0〜1.0。
    opacity: 0.8

    move:
      from:
        x: -240
        y: -32
        opacity: 0.0
      start: 0.1
      duration: 1.0
      easing: ease_in_out
      keyframes:
        - at: 0.35
          x: -80
          opacity: 1.0
          easing: ease_out
        - at: 0.75
          opacity: 0.6
          easing: ease_in
```

`move.keyframes[].opacity` は x / y / scale / rotate と同じ intermediate waypoint です。

## 4. Domain

opacity は finite number で、範囲は閉区間 `0.0 <= opacity <= 1.0` です。

- `0.0`: 完全透明
- `1.0`: opacity による追加減衰なし
- 範囲外: validation error
- NaN / ±Inf / bool: validation error

値を暗黙 clamp しません。

理由:

入力ミスを出力差へ変換して隠さないためです。

## 5. Persistence

v1 の `opacity` は line-local render property であり、character persistent state には追加しません。

- `position` / `scale`: persistent state
- `rotate`: line-local
- `opacity`: line-local
- `move.from.opacity`: transient start value
- `move.keyframes[].opacity`: transient intermediate value

`characters_persist: true` でも opacity は次 line へ自動継承しません。

opacity track を使う line は:

- final `opacity` を明示する
- start `move.from.opacity` を明示する

前 line の opacity を暗黙 start value として推測しません。

global `defaults.characters` / scene `character_defaults` に opacity は置けません。

## 6. Property interpolation

opacity は通常の scalar property として数値補間します。

- sparse waypoint rule は x / y / scale / rotate と同じ
- easing semantics も同じ
- interpolation result は入力domainが正しければ [0, 1] 内に留まる
- arbitrary expression は受け付けない

## 7. Source alpha invariant

source PNG / face PNG が持つ alpha は保持します。

Motion opacity は source alpha を置き換えません。

各 pixel の alpha は概念的に:

```text
source_alpha * motion_opacity
```

です。

半透明の縁、アンチエイリアス、透明holeを `opacity` の指定で不透明化してはいけません。

## 8. Lifecycle fade composition

既存 character の:

- `enter: fade`
- `leave: fade`
- bool `enter: true` / `leave: true` が意味する fade

は opacity track と共存できます。

暗黙 precedence は使いません。

effective alpha を次の積として定義します。

```text
effective_alpha(t)
  = source_alpha
  * motion_opacity(t)
  * lifecycle_fade(t)
```

ここで:

- lifecycle fade が無い区間は `1.0`
- enter fade は 0 -> 1
- leave fade は 1 -> 0
- enter / leave が重ならない通常ケースでは従来と同じ見た目
- 同じ時刻に opacity と lifecycle fade が動いても積で決定する

この積は precedence ではなく明示的な composition rule です。

## 9. Other alpha writers

将来 character effect 等が同じ character alpha を書く場合、次のどちらかが必要です。

1. Behavior Contract で合成式を追加する
2. validation error にする

未定義の複数alpha writerを、filter順や後勝ちで解決してはいけません。

foreground overlay の `opacity` / `blink` は別target ownerであり、この character contract には含めません。

## 10. Enter / leave slide

`slide_left` / `slide_right` / `slide_top` / `slide_bottom` は position writer です。

opacity と独立propertyなので共存できます。

## 11. visible boundary

`visible: false` は「characterをrender targetとして出さない」状態です。

- opacity 0 は visible false と同義ではない
- opacity 0 でも timeline / cache identity / motion semantics は保持する
- renderer が安全に最適化できる場合だけ透明区間を省略してよい
- authoring contractとして `opacity: 0` を `visible: false` に書き換えない

## 12. Face overlay invariant

mouth / eyes 等の face overlay は base character と同じ:

- motion opacity
- lifecycle fade

を適用します。

各face layerは自身のsource alphaを保持した上で:

```text
face_source_alpha
* motion_opacity(t)
* lifecycle_fade(t)
```

となります。

baseだけが薄くなり、mouth / eyes が濃いまま残る出力は禁止します。

## 13. Transform order

observable contract は次です。

```text
source image
  -> color / flip / scale / rotate geometry
  -> preserve transformed source alpha
  -> multiply motion opacity
  -> multiply lifecycle fade envelope
  -> overlay
```

実装上、乗算が可換で既存fade互換が維持される場合は opacity と lifecycle fade の物理filter順を固定しません。

ただし RGB を opacity 値で暗くして「透明に見せる」実装は禁止します。
変更するのは alpha です。

## 14. FFmpeg lowering constraint

v1 の基準 lowering は、RGBA stream の alpha plane を明示的に処理できる経路とします。

候補:

```text
RGBA
  -> split color / alpha
  -> alphaextract
  -> per-frame alpha multiplier
  -> alphamerge
```

per-frame multiplier は MotionTrack expression を使います。

既存 overlay alpha-preservation 実装と同様に、source alpha を保持できる構造を優先します。

renderer backendによって直接dynamic alphaを扱えない場合:

- CPUでalphaを処理してから hwupload してよい
- capabilityを偽って GPU-native と表現しない
- no-opacity pathの既存fast pathを壊さない

## 15. Validation

static opacity:

```yaml
opacity: 0.5
```

は有効です。

animated opacity:

```yaml
opacity: 0.8
move:
  from: {opacity: 0.0}
  duration: 1.0
  keyframes:
    - {at: 0.4, opacity: 1.0}
```

では:

- final `opacity` 必須
- `move.from.opacity` 必須
- duration > 0
- from / final / keyframe opacity は finite number
- すべて [0, 1]
- keyframe `at` / easing / ordering は既存 Motion Core rule

invalid:

```yaml
opacity: 1.2
```

```yaml
# final opacity missing
move:
  from: {opacity: 0}
  duration: 1.0
```

```yaml
# start opacity missing
opacity: 1
move:
  duration: 1.0
  keyframes:
    - {at: 0.5, opacity: 0.5}
```

```yaml
opacity: "0.5"
```

## 16. Static opacity

`opacity` があり motion opacity が無い場合も standard renderer が source alpha に定数倍率を適用します。

v1では static opacity character を scene-base baked overlayへ載せません。

理由:

- scene-base側にalpha ownerを増やさず first implementation を単一経路に保つ
- line-local semanticsを明確にする
-後から安全なbake最適化を追加できる

## 17. Fast path boundary

opacity が存在する character は simple scene fast path の対象外とし、standard rendererへ送ります。

これは機能要件であって永続方針ではありません。

将来、同じalpha semanticsをfast pathで証明できれば最適化できます。

## 18. Compatibility

opacity field / opacity keyframe が無い既存 script:

- existing character source alpha を維持
- existing enter / leave fade filter を維持
- additional alpha split / merge を追加しない
- current x / y / scale / rotate lowering を維持
- cache/output semanticsを変更しない

## 19. A/V invariant

opacity は video alpha transform のみです。

- line durationを延長しない
- audio timingを変更しない
- subtitle timingを変更しない
- scene transition offsetを変更しない
- fps / timebaseを変更しない

## 20. Cache / reproducibility

opacity により映像が変わるため、cache identity に次を含めます。

- final opacity
- move.from.opacity
- opacity keyframe order
- at
- value
- easing
- start / duration

`opacity: 0` と field未指定を同一入力へcanonicalizeしません。

前者は「明示的に完全透明」、後者は「opacity ownerなし」です。

## 21. Compiler / capability

compiled-config v1 は additive configuration として:

- character `opacity`
- `move.from.opacity`
- `move.keyframes[].opacity`

を保持できます。

renderer-native alpha expression / split / merge graphは公開しません。

runtime implementation と tests が完了した後だけ capability を:

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
      "multi_keyframe": false
    }
  }
}
```

へ更新します。

contract PR だけでは opacity を capability に追加しません。

## 22. Acceptance mapping

| Acceptance | Verification |
| --- | --- |
| domain is 0..1, no clamping | validation tests |
| sparse opacity waypoints | MotionTrack unit |
| source PNG alpha preserved | actual RGBA / alpha regression |
| lifecycle fade multiplies opacity | representative frames |
| RGB is not darkened as opacity substitute | pixel regression |
| face follows opacity | face overlay filter graph / actual render |
| rotate + opacity compose | standard graph + actual render |
| opacity remains line-local | CharacterTracker test |
| static opacity uses standard path | fast path / scene-base tests |
| cache changes on opacity | cache fingerprint |
| compiled-config stays v1 | authoring CLI test |
| capability truthful | capability test after runtime success |
| A/V duration unchanged | ffprobe integration |
| no-opacity legacy unchanged | existing render regression |

## 23. Minimal implementation slice

Input:

- line-local character `opacity`
- `move.from.opacity`
- optional `move.keyframes[].opacity`
- existing easing vocabulary

Internal:

- existing MotionTrack with property `opacity`
- pure opacity expression helper
- explicit alpha-plane multiplier helper

Output:

- base character source alpha preserved
- face source alpha preserved
- lifecycle fade multiplied with motion opacity
- existing x / y / scale / rotate output preserved

Not included:

- camera
- foreground overlay migration
- blend mode
- arbitrary alpha expression
- persistent opacity
- preset composition

## 24. Decision record

v1 opacity は次を採用します。

1. opacity は x / y / scale / rotate と同じ scalar MotionTrack
2. domainは0.0〜1.0で、clampしない
3. opacityはline-localでpersistしない
4. source alphaを置換せず乗算する
5. enter / leave fade は `source × opacity × fade` の積として共存する
6. 未定義の別alpha writerには暗黙precedenceを作らない
7. baseとface overlayへ同じmotion opacity / lifecycle fadeを適用する
8. static opacityもstandard rendererで処理する
9. opacity無しのlegacy pathへalpha split/mergeを追加しない
10. capabilityはruntime検証後だけ公開する
