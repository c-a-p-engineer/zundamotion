# Zundamotion Product Roadmap

更新日: 2026-09-25

この文書は、Zundamotion の**中長期の製品ゴール、設計原則、フェーズ順序、再判断条件**の正本です。

- 現在の実装状態と次タスクは [project_status.md](./project_status.md) を正とします。
- YAML の現在仕様は [../../scripts/script_cheatsheet.md](../../scripts/script_cheatsheet.md) を正とします。
- 実装済み機能の状態は [../features.md](../features.md) を正とします。
- 性能の採用・却下判断は [performance_regression_ledger.md](./performance_regression_ledger.md) を正とします。

この文書は「将来やりたい機能一覧」ではありません。Zundamotion が何を目指し、何を標準経路へ入れず、どの条件で次の技術へ進むかを固定します。

## 1. Product goal

Zundamotion の長期ゴールを次で固定します。

> **低スペック環境でも動作する、再現可能な Script-to-2D-Video Compiler。**
>
> YAML / Markdown などの台本から、音声、字幕、立ち絵、背景、BGM、SE、カメラ、モーションを組み合わせた動画を、headless / CLI / CI で再現可能に生成する。
> 標準経路は Python + FFmpeg で成立させ、より高コストな表現は必要な scene だけ optional renderer へ委譲できる構成を目指す。

Zundamotion は GUI 動画編集ソフトを目指しません。
Remotion、After Effects、ブラウザアニメーション環境の完全代替も目指しません。

Zundamotion が優先するのは、**最大表現力ではなく、表現力 / 計算コスト / 再現性の比率**です。

## 2. Product principles

### 2.1 Low-spec first

標準の動画生成経路に、GPU、Node.js、Chromium、ブラウザ runtime を必須としません。

標準構成は CPU-only でも成立し、Docker / CI / headless で同じ入力を再実行できることを優先します。

高性能環境向けの acceleration は optional とし、低スペック環境を壊して標準化しません。

### 2.2 Motion over complexity

「何でも自由に描画できる」よりも、低コストで視覚変化を十分な頻度で発生させられることを優先します。

優先する表現:

- position / scale / rotate / opacity
- pan / zoom / Ken Burns
- easing / keyframe
- blink / lip-sync
- breathing / body sway
- head tilt / nod
- simple hair / limb motion
- text emphasis
- slide / pop / bounce / shake 等の preset
- scene / shot 単位の camera change

高度な particle、3D、DOM layout、自由な canvas scripting は標準機能へ急いで入れません。

### 2.3 Progressive enhancement

高度な renderer を追加しても、使わない動画の依存・起動コスト・再現性を悪化させません。

基本形:

```text
native scene
  -> FFmpeg native path

rich scene
  -> optional renderer
  -> deterministic clip
  -> FFmpeg final assembly
```

### 2.4 Compiler / Orchestrator

Zundamotion 全体を個別技術へ直接依存させません。

```text
source script
  ↓
resolve / validate
  ↓
canonical compile
  ↓
render / materialize plan
  ↓
provider / renderer
  ↓
materialized assets / clips
  ↓
FFmpeg final assembly
```

TTS、キャラクターリグ、外部renderer、生成素材は、それぞれ provider / backend / materialized artifact として境界を持たせます。

### 2.5 Reproducibility before convenience

network依存の生成処理を最終renderの途中へ暗黙に混ぜません。

外部TTS、remote model、生成画像、rich renderer などを使う場合は、将来的に次の形を基本とします。

```text
Authoring
  ↓
Compile
  ↓
Materialize
  ↓
Lock
  ↓
Render
```

Materialize 済みの WAV / PNG / MP4 / metadata を provenance とともに固定し、最終 render は可能な限り local artifact だけから再実行できる状態を目指します。

## 3. Current strengths to preserve

現在の Zundamotion には、次の資産があります。

- Python + FFmpeg の headless render pipeline
- scene / clip / final phase の責務分離
- scene / finalize cache
- machine-readable `capabilities / validate / compile`
- Render Lock / input provenance
- VOICEVOX / Chatterbox を扱う TTS Provider 境界
- subtitle / BGM / SE / overlay / transition
- character position / scale movement
- background pan / zoom
- plugin registry
- post-render inspect / contact sheet
- SVG character rig の authoring / validation / preview

今後のフェーズでは、これらを捨てて別runtimeへ全面移行するのではなく、既存境界を利用して表現力を増やします。

## 4. Target content

主対象:

- ゆっくり系動画
- 解説動画
- 技術解説
- 会話形式動画
- キャラクター主体の情報動画
- Shorts / 縦動画
- AI / CI による自動動画生成

標準経路で要求しないもの:

- フル3D
- リアルタイムゲーム描画
- NLE相当のGUI編集
- 任意JavaScript / 任意DOMを常時実行する構成
- 毎frame Python callback が必要な自由描画API
- arbitrary FFmpeg filter文字列の無制限公開

## 5. Architecture direction

中長期の責務境界は次を目標とします。

```text
YAML / Markdown
      ↓
Script Resolver
      ↓
Canonical Compiled Config
      ↓
Timeline / Scene Plan
      ↓
Motion / Character / Audio plans
      ↓
Renderer selection
      ├─ Native FFmpeg
      ├─ Character Rig Runtime
      └─ Optional Rich Renderer
             ↓
       materialized clip
      ↓
FFmpeg Final Assembly
      ↓
MP4 / subtitles / reports / lock
```

重要なのは、Rich Renderer を pipeline の中心へ置かないことです。

## 6. Roadmap

### Phase 0.1.x — Foundation stabilization

目的:
現在の compiler / provider / reproducibility 基盤を、次の表現力拡張を載せられる状態へ固定します。

主要項目:

- J-cut E2E characterization
- audio worker 長尺 benchmark
- 0.1.x compiler contract の実運用確認
- Render Lock / output QA の運用確認
- TTS Provider capability / cache identity / language contract の安定化
- Chatterbox optional runtime の未固定領域整理
- 0.1.0 release baseline

完了条件:

- 現在の標準経路に未characterizedな主要A/V timing挙動を残さない
- compiler / render contract の変更点を version 管理できる
- 次の Motion Core が既存 YAML / cache / reproducibility を無暗に壊さない基準線がある

### Phase 0.2 — Motion Core

**次の表現力フェーズの最優先。**

目的:
「画面が止まっている時間」を減らし、FFmpeg native path のまま視覚変化を増やします。

主要項目:

- multi-keyframe
- easing
- generic motion track
- position / scale / rotate / opacity
- camera track
- character motion と camera motion の責務分離
- motion preset
- preset composition の制約
- machine-readable capability
- motion-aware cache identity
- motion visual QA

初期 preset 候補:

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

設計原則:

- YAMLからFFmpeg式への直結ではなく、一度 motion model へ正規化する
- 既存 `move` / pan / zoom を壊さず段階移行する
- presetは糖衣構文とし、内部では同じmotion contractへ落とす
- frame callback型の自由スクリプトは導入しない

完了条件:

- 単一区間補間だけでなく、複数keyframeを同一propertyへ指定できる
- 代表presetを native FFmpeg path で生成できる
- A/V durationを変えず motion を適用できる
- motion有無で cache / reproducibility の意味が崩れない
- 実動画で中間frameを含むvisual QAが可能

### Phase 0.3 — Character Runtime

目的:
現在の SVG character rig authoring / QA 資産を本体renderへ接続し、低コストなキャラクターアニメーションを標準化します。

主要項目:

- rig runtime contract
- source part / pivot / hierarchy の runtime model
- character rig compile / materialize
- blink
- lip-sync state
- breathing
- body sway
- head motion
- hair motion
- simple arm / limb gesture
- reaction preset
- motion + expression + persist の状態規則
- fallback to existing PNG character path

重要方針:

SVG DOM をブラウザで毎frame描画することを前提にしません。

有力な標準形:

```text
SVG rig / rig config
  ↓
compile
  ↓
part assets + hierarchy + pivot metadata
  ↓
native motion runtime
  ↓
FFmpeg composition
```

完了条件:

- rigを使わない既存動画は従来runtimeで生成できる
- rig character は最低限 idle / blink / lip-sync / head / hair の低コストanimationを持てる
- arm / leg motion は接続点の破綻を visual QA で検出できる
- character animation が camera / subtitle / audio timeline と同一時間軸で扱える

### Phase 0.4 — Materialize / Rich Scene

目的:
FFmpeg native では費用対効果が悪い表現だけを、scene単位で外部rendererへ委譲できるようにします。

主要項目:

- render backend contract
- scene renderer selection
- materialized clip contract
- cache / provenance / lock
- partial rerender
- failure / fallback policy
- optional renderer prototype

候補:

- Remotion adapter
- Web Canvas / WebGL adapter
- Lottie / Rive 等のanimation asset renderer
- 外部 chart / visualization renderer

採用条件:

1. native Motion Core / Character Runtime で不足する具体的 use case がある
2. その use case が複数動画で再利用される
3. optional dependency として隔離できる
4. materialized clip を固定して最終renderの再現性を保てる
5. cold start / memory / render時間が許容範囲
6. native path を使うユーザーへ依存を強制しない

Remotion や Web2D を「高機能だから」という理由だけで標準化しません。

### Phase 0.5 — AI Director / Voice Ecosystem

目的:
「台本を動画にする」から、「台本から必要な演出を計画して動画にする」へ進めます。

主要項目:

- scene / shot plan
- focus / framing / camera intent
- motion preset selection
- expression / reaction selection
- insert / overlay suggestion
- TTS provider selection
- voice capability negotiation
- narration / dialog style
- scene-level preview / partial render
- automatic QA feedback loop

TTS方針:

- VOICEVOX を既定のローカル日本語経路として維持
- Chatterbox 等の optional provider を capability で扱う
- Google系などの外部TTSも追加する場合は同じ Provider 境界へ入れる
- cloud API を timeline / render core へ直接埋め込まない
- network音声は materialize + cache + provenance を基本とする

AI Director は arbitrary instruction を直接 FFmpeg command へ変換しません。
まず既存の capability / preset / timeline contract へ落とします。

### Phase 1.0 — Lightweight Video Compiler

1.0 の到達条件:

- CPU-only の標準構成で主要機能が成立する
- 動きのある解説 / 会話動画を native path だけで作れる
- TTS / renderer が provider / backend 境界で交換可能
- external generation を materialize して再利用できる
- input provenance と出力QAを機械的に確認できる
- GUI無しで script -> validate -> compile -> materialize -> render -> inspect を完結できる
- rich renderer を使わないユーザーへ追加runtimeを要求しない

## 7. Performance policy

性能改善は機能数より優先度が低いのではなく、**製品ゴールそのもの**です。

新しい表現機能は次を確認します。

- cold render
- warm/cache render
- memory usage
- process count
- intermediate file size
- A/V warnings
- output equivalence
- CPU-only behavior

低スペック基準機の具体的スペックと1分動画の目標時間は、推測で固定せず、代表動画と実測結果から別途 baseline を決めます。

目標は「最速」ではなく、次の両立です。

```text
acceptable visual motion
+
bounded compute cost
+
reproducible output
```

## 8. Decision gates

### Remotion / browser renderer

再検討する条件:

- Motion Core / Character Runtime では実装コストが高い scene が具体化した
- chart / typography / dynamic layout 等で browser renderer の優位が明確
- 1本全体ではなく局所sceneへ限定できる
- benchmarkで費用を測定できる

標準rendererへ昇格する条件はさらに厳しくし、low-spec first を破壊する場合は optional のまま維持します。

### Web Canvas / custom 2D engine

独自実装は最終手段です。

次を満たさない限り作りません。

- 既存FFmpeg / SVG / optional renderer で満たせない
- 長期的に複数機能の共通基盤になる
- browser runtimeを所有する保守コストに見合う
- deterministic frame / timing contractを定義できる

### New TTS provider

追加条件:

- 既存Providerにない具体的価値がある
- capability を機械可読にできる
- provider固有設定をtimeline coreへ漏らさない
- cache identity を定義できる
- remote利用時のprovenance / cost / failureを明示できる

## 9. Success metrics

機能数をKPIにしません。

見る指標:

- **motion coverage**: 動画中で意図した視覚変化を作れる区間の割合
- **native coverage**: external rendererなしで成立するsceneの割合
- **warm rerender cost**: 局所変更時の再生成コスト
- **reproducibility**: 同一locked inputから意味上同じ出力を得られるか
- **authoring complexity**: 単純な演出に大量YAMLを要求していないか
- **fallback integrity**: optional runtimeなしでも標準動画を生成できるか
- **visual defect rate**: move / transition / rig / subtitle等の破綻率

厳密な数値目標は、代表動画 corpus と benchmark 基準線を作った後に固定します。

## 10. Immediate next sequence

次の実装順序は原則として以下です。

1. P0の正しさ未確定項目を閉じる
2. 0.1.x release / compiler / provider 基準線を整理する
3. Motion Core の behavior contract を作る
4. multi-keyframe + easing の最小縦切りを実装する
5. motion preset を少数追加して実動画評価する
6. Motion Core の費用対効果を確認してから Character Runtime へ進む
7. Character Runtime でも不足する具体例が集まってから Rich Renderer を比較する

**Remotion / Web Canvas の全面導入を先に行わない**ことを、現時点の既定方針とします。

## 11. Roadmap update rule

- 現在状態は `project_status.md` へ反映し、この文書を進捗ログにしません。
- phaseの順序を変える場合は、その理由と再判断Evidenceを残します。
- benchmark結果で仮説が崩れた場合は現状維持も有効な結論とします。
- 新しいrenderer / runtime / dependency を標準化する場合は、low-spec / reproducibility / headless / OSS保守への影響を先に評価します。
- 「表現力が上がる」だけでは標準化理由にしません。
