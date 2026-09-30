# Character Runtime Materialized SVG Rig Contract

更新日: 2026-09-30
対象: Zundamotion 0.3 Character Runtime first slice
Issue: #123

この文書は、既存 SVG character rig authoring / QA 資産を本体 runtime へ接続する最初の縦切りを定義します。

目的は SVG を毎frame描画する新rendererを導入することではありません。
validated rig から再利用可能な PNG asset を決定論的に materialize し、既存 PNG character / face timeline / FFmpeg 合成経路へ接続します。

関連:

- [SVG Character Rig Authoring](../guides/svg_character_rig.md)
- [Character Assets](../guides/character_assets.md)
- [Current Project Status](../guides/project_status.md)
- [Motion Core Behavior Contract](./motion_core_contract.md)

## 1. Objective

first slice は次を満たします。

1. 既存 PNG character path を既定のまま維持する
2. SVG rig runtime は明示 opt-in にする
3. rig validation を runtime materialization 前に必須化する
4. CairoSVG は materialization 時だけ使う
5. materialized PNG を既存 character / face pipeline へ渡す
6. blink / lip-sync の既存 timeline semantics を変更しない
7. character transform / Motion Core / camera semantics を再実装しない
8. materialization を deterministic / cacheable / headless にする

## 2. Non-goals

first slice では次を実装しません。

- browser / Chromium / DOM runtime
- per-frame SVG rasterization
- CSS animation / JavaScript in SVG
- continuous breathing / body sway
- head / hair physics
- limb / joint gesture runtime
- reaction preset
- phoneme / viseme inference
- vowel-specific lip-sync timeline
- SVG rig を既存 PNG path の自動置換にすること
- arbitrary remote asset fetch
- generic character runtime target DSL

## 3. Public authoring shape

SVG rig runtime は character ごとの `rig` mapping で明示します。

```yaml
characters:
  - name: copetan
    visible: true
    expression: default
    position: {x: 0, y: -32}
    scale: 0.85
    rig:
      path: assets/characters/copetan/character.svg
```

optional:

```yaml
rig:
  enabled: true
  path: assets/characters/copetan/character.svg
  raster_width: 832
```

fields:

- `enabled`: boolean、default true when `rig` mapping exists
- `path`: local SVG path、required when enabled
- `raster_width`: positive integer、optional

unknown field は validation error とします。

`rig.enabled: false` は PNG path と同じ挙動です。

## 4. Explicit opt-in / fallback rule

既存 script に `rig` が無い場合、現在の PNG asset resolution を byte-for-byte互換の基準とします。

enabled rig が指定された場合:

- path missing: validation error
- file missing: validation error
- invalid rig: validation/runtime error
- materialization failure: render error

**明示 opt-in した rig の失敗を黙って PNG fallback しません。**

理由:

壊れた rig を偶然 PNG path が隠すと再現性とdiagnosticが失われるためです。

PNG fallback は `rig` 未指定または `enabled: false` のときだけです。

## 5. Rig validation

runtime は materialization 前に既存 v2-compatible validator semantics を再利用します。

最低条件:

- SVG root
- viewBox
- unique IDs
- required v1 IDs
- v2 declared/detected時のrequired joint/pivot rules
- state group validation
- `fullbody_ref` が character movable hierarchy に入らないこと

validator logicを runtime側に別実装して意味を分岐させません。
必要なら validator core を import可能 module へ移動し、CLI tool はその facade にします。

## 6. Raster size

`raster_width` が明示されている場合、その positive integer を materialization width とします。

省略時:

1. SVG root の numeric `width` が positiveならそれを使用
2. それ以外は viewBox width を positive integer へ丸めて使用

first slice では `1 <= raster_width <= 4096` を要求します。

height は SVG aspect ratio から決定します。

video resolution や machine DPI から暗黙に materialization size を変えません。

## 7. Materialized asset set

enabled rig から最低限次を生成します。

```text
base.png
eyes/open.png
eyes/close.png
mouth/close.png
mouth/half.png
mouth/open.png
```

mapping:

| existing PNG runtime state | SVG rig state |
| --- | --- |
| base | neutral rig with `eyes-open` + `mouth-closed` |
| eyes/open | `eyes-open` |
| eyes/close | `eyes-closed` |
| mouth/close | `mouth-closed` |
| mouth/half | `mouth-small` |
| mouth/open | `mouth-a` |

materialized face PNG は既存 PNG face contract と同じ full-canvas registration を持ち、対象state以外は透明にします。

`eyes-half` と `mouth-i/u/e/o` が存在する場合、cache artifactとして追加生成しても構いませんが、first slice の runtime timeline ownerにはしません。

## 8. Existing blink / lip-sync semantics

first slice は現行 face timeline を変更しません。

- blink: current open / close events
- mouth: current close / half / open events
- audio / timing owner: existing face animation pipeline

SVG rig runtime は **asset provider** であり、新しい timeline generatorではありません。

これにより PNG と SVG rig で同じ発話に対する state timing を比較できます。

## 9. Neutral base invariant

`base.png` は neutral character rasterです。

- eyes-open を含む
- mouth-closed を含む
- face state overlayを二重焼きしない
- `fullbody_ref` を描画しない
- authoring preview用continuous motionを適用しない

既存 PNG face overlayと同様、mouth / eyes overlayは base と同一canvas上へ重なります。

## 10. SVG state isolation

materializationでは state group visibility を決定論的に固定します。

base:

- eyes-open = visible
- other eye states = hidden
- mouth-closed = visible
- other mouth states = hidden

eye overlay:

- selected eye stateのみ visible
- characterの非-eye部分は透明

mouth overlay:

- selected mouth stateのみ visible
- characterの非-mouth部分は透明

source SVGの既存 inline style / animation がstate visibilityを上書きしないよう、runtime materialization前に animation/style ownershipを正規化します。

## 11. Hybrid raster asset policy

hybrid SVG の `<image>` は first slice で許容します。

許可:

- embedded `data:` URI
- rig SVG と同一repository内の相対local file

禁止:

- `http://`
- `https://`
- その他network fetch
- repository外へ脱出する relative path
- runtimeで生成AI / external asset serviceから取得すること

relative asset の content hash は materialization cache identity に含めます。

## 12. Cache identity

materialization cache key は最低限次を含みます。

- materializer version
- source SVG content hash
- referenced local raster asset content hashes
- resolved raster width
- rig validation contract version
- state mapping version

同じ入力は同じ materialized PNG bytes / dimensions を生成することを目標とします。

cache key に machine absolute path や wall clock を入れません。

## 13. Runtime boundary

標準経路:

```text
authoring character
  -> rig config validation
  -> materialized asset resolver/cache
  -> existing character input collection
  -> existing face timeline overlays
  -> existing x/y/scale/rotate/opacity/preset
  -> existing camera/world composition
```

materialized rig は character transform ownerになりません。

Motion Coreと競合する新しい transform graphを持ちません。

## 14. Persistence

`rig` は asset/runtime selection metadataです。

`characters_persist: true` では同一characterのresolved rig selectionを通常のasset identityとして維持できます。

ただし:

- blink stateはpersistしない
- mouth stateはpersistしない
- materialized intermediate stateをcharacter stateへ書き戻さない

expression / asset_name / position / scale等の既存state semanticsを変更しません。

## 15. Expression boundary

first slice では rig path 自体を expression ごとに自動推定しません。

`rig.path` が1つの source of truthです。

既存 `expression` は PNG path と同様のcharacter semantic stateとして保持できますが、rig内部のbrow等を expression名から自動切替する機能は deferred とします。

必要なら後続sliceで explicit rig expression mappingを契約化します。

## 16. Color filter / flip

materialized PNG は既存 PNG character asset と同じ後段処理を通します。

したがって:

- `flip_x`
- `flip_y`
- `color_filter`

は materialization後の既存 ownerが担当します。

SVG DOMへ同じeffectを再実装しません。

## 17. Motion Core composition

materialized characterは既存 characterと同じ対象です。

対応済み:

- position x/y
- scale
- rotate
- opacity
- deterministic motion preset
- enter / leave
- camera world transform

rig materializationのためにこれらの意味を変えません。

## 18. Fast path / scene base

first implementationでは enabled rig character を simple scene fast path / static scene-base bakeへ直接載せることを必須にしません。

安全な初期方針:

- materialization/cacheは許可
- line renderはstandard renderer
- semantic equivalenceを証明した後に fast-path / scene-base最適化を追加可能

`rig.enabled: false` は既存PNG eligibilityを維持します。

## 19. Compiled-config / capability

compiled-config v1 は authoring fieldsだけを保持します。

```yaml
rig:
  enabled: true
  path: assets/characters/copetan/character.svg
  raster_width: 832
```

次は compiled-config に露出しません。

- cache path
- generated PNG path
- CairoSVG command/internal object
- expanded state asset table

runtime + tests完了後だけ capability へ additive に公開します。

例:

```json
{
  "character_runtime": {
    "svg_rig": {
      "materialized": true,
      "per_frame_svg": false,
      "face_states": {
        "eyes": ["open", "close"],
        "mouth": ["close", "half", "open"]
      },
      "max_raster_width": 4096
    }
  }
}
```

contract PRだけでは capability を true にしません。

## 20. Dependency policy

CairoSVG は materialization capability に必要です。

first slice implementationでは packaging方針を明示します。

優先:

- optional dependency groupとして分離
- PNG-only installを重くしない
- enabled rig使用時に未installなら actionable error

通常PNG renderのimport pathでCairoSVGを eager importしません。

## 21. Reproducibility / security

- network access不要
- local path resolutionはrepository/script root基準で決定論的
- XML external entity / remote resource fetchを許可しない
- SVG scriptを実行しない
- source / referenced asset hashをlock/cache identityへ含める
- materialized outputは中間成果物として観測可能にする

## 22. Acceptance mapping

| Acceptance | Verification |
| --- | --- |
| PNG-only script unchanged | existing render regression |
| enabled rig requires explicit valid path | validation tests |
| invalid rig fails loudly | validator/runtime tests |
| no network asset fetch | path/resource validation |
| deterministic materialization | same-input byte/dimension/cache regression |
| source changes cache identity | cache test |
| referenced raster changes cache identity | hybrid asset cache test |
| base neutral state correct | pixel/contact-sheet regression |
| eye open/close aligned | materialized PNG regression + actual render |
| mouth close/half/open aligned | materialized PNG regression + actual render |
| existing face timing reused | graph/timeline regression |
| Motion Core transforms unchanged | combined render regression |
| duration unchanged | ffprobe |
| compiled-config remains v1 | authoring CLI test |
| capability truthful | capability test after runtime green |
| PNG install does not eager-import CairoSVG | import/package test |
| reproducibility maintained | existing no-voice reproducibility + rig fixture |

## 23. Implementation order

1. extract/importable rig validation core from tool without behavior change
2. add strict `rig` authoring validation
3. add resource/path resolver with network/repository escape rejection
4. add deterministic materialization helper + cache
5. connect materialized asset set before existing character input collection
6. route current face timeline to materialized eye/mouth PNG
7. add cache/compile/fast-path boundaries
8. add actual FFmpeg + reproducibility tests
9. only after green, publish capability/docs/sample
10. then evaluate next Character Runtime slice: continuous body/head/hair motion

## 24. Decision record

first Character Runtime slice adopts:

1. explicit opt-in rig runtime
2. PNG materialization, not per-frame SVG rendering
3. existing face timeline as the only blink/lip-sync timing owner
4. close/half/open compatibility mapping instead of new vowel inference
5. deterministic local-only resources and cache identity
6. existing PNG renderer/Motion Core as the only transform owner
7. loud failure for explicitly enabled invalid rig
8. PNG path remains default and unchanged
9. CairoSVG remains optional and lazily required
10. continuous joint motion is deferred to a separate contract
