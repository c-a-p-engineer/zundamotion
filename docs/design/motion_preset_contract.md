# Motion Core Deterministic Preset Contract

更新日: 2026-09-30
対象: Zundamotion 0.2 Motion Core deterministic character preset
Issue: #120
前提: character multi-keyframe / rotate / opacity / camera / background pan-zoom が実装済み

この文書は、既存 MotionTrack を再利用して短い定型モーションを低コストに指定する preset の first slice と、generic public target abstraction を現時点で導入しない判断を定義します。

関連:

- [Motion Core Behavior Contract](./motion_core_contract.md)
- [Camera / Coordinate Space Contract](./motion_camera_contract.md)
- [Background Pan/Zoom Integration Contract](./motion_background_pan_zoom_contract.md)
- [Current Project Status](../guides/project_status.md)
- [Product Roadmap](../guides/product_roadmap.md)
- [YAML Cheatsheet](../../scripts/script_cheatsheet.md)

## 1. Decision

### 1.1 Deterministic motion preset

実装します。

first slice は character の既存 `move` ownerへ preset sugar を追加します。

```yaml
characters:
  - name: copetan
    visible: true
    position: {x: 0, y: -32}
    scale: 0.8
    move:
      preset: pop
      start: 0.10
      duration: 0.45
      intensity: 1.0
```

preset は renderer-specific FFmpeg式ではなく、既存 character `move.from/keyframes` と同じ MotionTrack contractへ決定論的にloweringします。

### 1.2 Generic public target abstraction

現時点では導入しません。

`character` / `camera` / `background` は同じ MotionTrack helperを部分的に共有していても、外部contractが異なります。

- character:
  - position / scale は persistent stateになり得る
  - rotate / opacity は line-local
  - face overlay も同じtransformを追従する必要がある
- camera:
  - bounded W×H world view
  - line-local
  - world/screen-space境界を所有する
- background:
  - background-local effect owner
  - legacy no-keyframe clamp/fallback互換を持つ

この差を隠す `motion.targets[]` のようなpublic DSLは、現在は利用者と実装双方の複雑性を減らしません。

## 2. First-slice presets

公開preset:

- `pop`
- `bounce`
- `emphasis`

first sliceでは1つの `move` にpresetは1つだけです。

preset composition / list構文は導入しません。

## 3. Common authoring fields

preset pathで許可する `move` field:

- `enabled`
- `preset`
- `start`
- `duration`
- `intensity`

### 3.1 Domains

- `preset`: non-empty string、supported presetのみ
- `enabled`: boolean
- `start`: finite number >= 0、default 0
- `duration`: finite number > 0。省略時はpreset固有default
- `intensity`: finite number 0.0〜2.0、default 1.0

boolをnumberとして受理しません。

### 3.2 Conflict rule

`move.preset` がある場合、first sliceでは次を同時指定できません。

- `move.from`
- `move.keyframes`
- `move.easing`
- その他preset pathで未定義のmove field

理由:

presetが生成するstart/keyframe/easingとuser explicit trackのowner競合を避けるためです。

将来 composition を導入する場合も、暗黙mergeではなく別contractで定義します。

## 4. Final-state requirements

presetは「既存のcharacter最終stateへ戻る一時motion」です。

first sliceではvalidation時点で同一character entryに最終値を明示します。

### pop

必須:

- `scale`: finite number > 0

### emphasis

必須:

- `scale`: finite number > 0

### bounce

必須:

- `position.y`: finite number

first sliceでは persistent previous state / global default / scene default からpresetの最終値を暗黙補完しません。

理由:

authoring validationでpreset loweringに必要な値を確定し、state tracker実行順へ依存させないためです。

## 5. Deterministic lowering

preset loweringはpure functionです。

入力:

- preset name
- explicit final character state
- start
- duration
- intensity

出力:

- rendererで既に扱える synthetic `move.from`
- synthetic `move.keyframes`
- synthetic `move.easing`

randomness、wall clock、machine state、network、asset dimensionsへ依存しません。

authoring dict自体はmutationしません。

## 6. pop

目的:

- 小さめのscaleから出現
- 少しovershoot
- 最終scaleへsettle

default duration:

```text
0.45 sec
```

final scaleを `S`、intensityを `I`、durationを `D` とします。

lowering:

```text
start scale = S * (1 - 0.18 * I)

at 0.65D:
  scale = S * (1 + 0.08 * I)
  easing_to_here = ease_out

end D:
  scale = S
  easing_to_here = ease_in_out
```

synthetic move概念:

```yaml
move:
  from: {scale: <start scale>}
  start: <authoring start>
  duration: <resolved D>
  easing: ease_in_out
  keyframes:
    - at: <0.65D>
      scale: <overshoot scale>
      easing: ease_out
```

position / rotate / opacityへkeyframeを追加しません。

## 7. bounce

目的:

- 最終位置から上方向へ1回跳ねる
- 少し下へovershoot
- 最終位置へsettle

default duration:

```text
0.60 sec
```

final yを `Y`、intensityを `I`、durationを `D` とします。

screen座標では負方向が上です。

lowering:

```text
start y = Y

at 0.35D:
  y = Y - 48 * I
  easing_to_here = ease_out

at 0.68D:
  y = Y + 10 * I
  easing_to_here = ease_in_out

end D:
  y = Y
  easing_to_here = ease_out
```

synthetic moveの `from` はyだけを持ちます。

x / scale / rotate / opacityへkeyframeを追加しません。

## 8. emphasis

目的:

- 現在の最終scaleから短く拡大
- 最終scaleへ戻る

default duration:

```text
0.50 sec
```

final scaleを `S`、intensityを `I`、durationを `D` とします。

lowering:

```text
start scale = S

at 0.45D:
  scale = S * (1 + 0.12 * I)
  easing_to_here = ease_out

end D:
  scale = S
  easing_to_here = ease_in_out
```

popとの違い:

- popは小さい状態から開始する
- emphasisは現在の最終scaleからpulseする

## 9. intensity = 0

`intensity: 0` はvalidです。

生成値は最終値と同じになり、visualにはno-opになり得ます。

first sliceではauthoringに `move.preset` が存在する以上、scene planning / cache上はmotion指定として扱って構いません。

zero-intensity専用のfast-path最適化はこのsliceでは行いません。

## 10. enabled = false

`move.enabled: false` は既存semanticsを維持します。

preset fieldがあってもrender motionを発生させません。

ただしpreset名 / field型など authoring shape自体のvalidationは行います。

final-state requirementはdisabled時には要求しません。

## 11. Expansion boundary

preset expansionは character/face graphが同じ synthetic move を参照できる共通clip input境界で1回だけ行います。

要求:

1. authoring character dictを直接mutationしない
2. character base transformとface overlayが同じexpanded moveを見る
3. talk / waitの両pathで同じhelperを使う
4. scene cache keyはauthoring preset configを基準とし、synthetic moveを重複追加しない
5. compiled-configへsynthetic keyframeを露出しない

実装module名は固定しません。

## 12. State / persistence

presetは一時motionであり、最終character stateを変更しません。

### pop / emphasis

- final `scale` はauthoring characterの `scale`
- preset終了後もそのscale
- `characters_persist: true` の通常scale state semanticsは変更しない

### bounce

- final `position.y` はauthoring characterの値
- preset終了後も同じposition
- presetによる中間yをpersistent stateへ書き戻さない

preset設定自体は次lineへpersistしません。

## 13. Face / expression alignment

presetでcharacter baseが動く場合、face overlayも既存 character motionと同様に追従します。

特に:

- pop / emphasis のscale
- bounce のy

でface差分がbaseからずれないことをactual renderで確認します。

## 14. Existing feature ownership

既存機能をpresetへ重複実装しません。

| idea | first-slice owner |
| --- | --- |
| shake | existing `char:shake_char` effect |
| slide_in / slide_out | existing `enter` / `leave` |
| periodic float | existing bob / sway effect |
| pop | new deterministic move preset |
| bounce | new deterministic move preset |
| emphasis | new deterministic move preset |
| breathe | Character Runtime再評価 |
| nod / head_tilt | Character Runtime rig target |
| gentle_zoom | camera/background ownerで将来再評価 |

## 15. Fast path / scene base

`move.preset` は既存 `move` mapping内に存在します。

そのため:

- characterはdynamicとして扱う
- static scene baseへ焼き込まない
- simple scene fast pathは既存move検出によりfallbackする

preset専用の第二のdynamic flagを作りません。

## 16. Cache / reproducibility

cache identityはauthoring preset configを含みます。

最低限:

- preset
- start
- duration
- intensity

の変更でcache missになります。

synthetic `from/keyframes` はcache keyへ二重追加しません。

同じauthoring inputから同じsynthetic moveを生成します。

## 17. Compiled-config

compiled-config v1はauthoring fieldsを保持します。

例:

```json
{
  "move": {
    "preset": "pop",
    "start": 0.1,
    "duration": 0.45,
    "intensity": 1.0
  }
}
```

公開しない:

- synthetic `from`
- synthetic `keyframes`
- synthetic easing
- FFmpeg expression
- resolved track frames

format versionは1のままです。

## 18. Capability

runtime + tests完了後だけ `motion.character` capabilityへpreset情報をadditiveに追加します。

候補:

```json
{
  "motion": {
    "character": {
      "multi_keyframe": true,
      "properties": ["position.x", "position.y", "scale", "rotate", "opacity"],
      "easings": ["linear", "ease_in", "ease_out", "ease_in_out"],
      "presets": ["bounce", "emphasis", "pop"],
      "preset_parameters": {
        "start_min": 0.0,
        "intensity_range": [0.0, 2.0],
        "max_presets_per_move": 1
      }
    }
  }
}
```

contract PRではまだ公開しません。

generic target capabilityは追加しません。

## 19. Validation placement

presetは `move` の新しいstrict subpathです。

`move.preset` が存在する場合:

- common preset fieldsをstrict validation
- conflict fieldをreject
- preset-specific final stateをvalidation
- unknown presetをreject

presetがない既存 `move` validation / legacy compatibilityを変更しません。

## 20. A/V invariant

presetはcharacter video transformだけです。

- clip durationを延長しない
- audio timingを変更しない
- subtitle timingを変更しない
- camera timingを変更しない
- background timingを変更しない

motion endがclip endを超えてもclipを延長せず、既存Motion Core semanticsと同じです。

## 21. Generic target abstraction reconsideration gate

generic public target abstractionは「将来の可能性」だけでは導入しません。

再検討条件:

1. character / camera / background のうち2 owner以上が同一public target/property/lifecycle schemaを必要とする
2. owner adapter間でvalidation/loweringの実質重複が増える
3. Character Runtimeがstable rig subtarget IDを導入し、target referenceが利用者価値を持つ
4. AI authoringがowner-specific capabilityだけでは安全にtarget選択できない実例が蓄積する

条件を満たすまではowner-specific authoringを維持します。

## 22. Acceptance mapping

| Acceptance | Verification |
| --- | --- |
| deterministic pop expansion | pure unit test |
| deterministic bounce expansion | pure unit test |
| deterministic emphasis expansion | pure unit test |
| preset conflict rejection | validation test |
| parameter domains | validation test |
| explicit final state requirement | validation test |
| existing no-preset move unchanged | legacy regression |
| character dynamic / no scene-base bake | scene state test |
| fast-path fallback | eligibility test |
| face alignment | actual FFmpeg representative frames |
| duration unchanged | ffprobe integration |
| cache identity changes | cache hash test |
| compiled-config stays v1 | authoring CLI |
| capability truthful | capability test after runtime green |
| generic target absent | capability/document contract |

## 23. Minimal implementation slice

Change:

- pure preset expansion helper
- preset validation branch inside character move validation
- common clip input expansion for talk/wait + face alignment
- tests
- capability/docs/sample after runtime green

Do not change:

- explicit move semantics
- camera/background owner
- character persistence model
- existing char effects
- enter/leave
- generic target abstraction
- Character Runtime rig model

## 24. Decision record

1. Deterministic preset is worth implementing as MotionTrack sugar.
2. first slice is character-only.
3. syntax reuses `character.move`; no new top-level motion DSL.
4. pop / bounce / emphasis are the first presets.
5. explicit `from/keyframes/easing` cannot be combined with preset in first slice.
6. preset final state is explicit in the same character entry.
7. synthetic keyframes are renderer-internal and not exposed by compiled-config.
8. generic public target abstraction is not implemented now.
9. generic target is reconsidered only when concrete cross-owner duplication/use cases appear.
