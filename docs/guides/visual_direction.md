# Visual Direction Guide

Zundamotionの台本を、単なる「字幕付き立ち絵」ではなく、**scene → shot → camera / motion / sound / text** の役割を分けて設計するためのProject固有ガイド。

この文書は新しいYAML機能を定義しない。実際に使用できる機能・構文・制限は `scripts/script_cheatsheet.md`、`docs/features.md`、`docs/guides/compiler_interface.md` を正とする。

## 目的

- 台本上の意図を、現在のZundamotionで実装可能な視覚・音響演出へ落とす
- camera、character motion、subtitle、SE、BGMを同時に盛りすぎず、視線誘導を作る
- unsupportedな演出を「実装済み」と仮定しない
- render後に、意図した見せ場が実際の映像へ出ているか確認する

## Direction layers

```text
story / explanation beat
  ↓
scene purpose
  ↓
shot composition
  ↓
camera + character motion + text + sound
  ↓
Zundamotion capability mapping
  ↓
render verification
```

### 1. Beat

まず「この数秒で視聴者に何が変わって見えるか」を一つ決める。

例:

- 新しい事実を知る
- キャラクターが反応する
- 比較対象が切り替わる
- 重要語を覚える
- 緊張から安心へ変わる

一つの短いbeatへ複数の主目的を詰め込みすぎない。

### 2. Scene purpose

sceneには主役を決める。

- character
- dialogue / narration
- inserted media
- diagram / text
- environment / transition

主役以外は補助へ回す。

### 3. Shot composition

shot planningでは必要なものだけ次を決める。

```text
purpose:
focal subject:
shot size / framing:
character position:
character action:
camera action:
subtitle role:
SE / BGM role:
approximate rhythm:
transition:
required Zundamotion capability:
fallback if unsupported:
```

すべてを毎shotで埋める必要はない。変更しない項目は既定状態を継承する。

## Camera and motion

camera motionは「動かせるから動かす」のではなく、視線誘導か状態変化を表す場合に使う。

### Push / zoom

向いている用途:

- 重要語・表情・対象へ注意を集める
- 山場へ密度を上げる

避ける:

- 全台詞で同じzoomを繰り返す
- 字幕の読みやすさを損なうほど動かす

### Pan / lateral movement

向いている用途:

- 比較対象を順に見せる
- 画面外から新しい対象を導入する

移動方向とキャラクター入退場が衝突しないようにする。

### Character move

`move`等を使う場合、座標変化そのものより次を先に決める。

- 近づく / 離れる
- 相手側へ寄る
- 画面を譲る
- inserted mediaのために空間を作る

連続sceneで位置・scaleが意図せずリセットされる場合は、現在のpersist / expression / motion仕様を確認する。

## Visual hierarchy

一つの瞬間に強い変化を重ねすぎない。

```text
primary change: 1
secondary support: 0-2
background continuity: keep stable
```

例えば、重要な字幕を読ませる瞬間に、大きなcamera move、character move、SE、transitionを同時発火させない。

見せ場では密度を上げ、説明やつなぎでは静止・余白・既存状態の継承を使ってよい。

## Subtitle / text safe area

- 字幕が主情報なら、顔・重要insert・主要動作と競合しない配置を優先する
- 長い文章を一画面で読ませず、speech / narrationの意味単位で分ける
- visualだけで分かる情報を字幕で完全に重複説明しない
- 画面端へ寄るmotionではsafe areaからのはみ出しを確認する

## Sound direction

### SE

- 画面上の変化、操作、登場、決定等へ同期させる
- 台詞の全phraseへSEを付けない
- 同種SEの連打で重要度を均一化しない

### BGM

- sceneの感情を説明するだけでなく、区切り・転調・継続性を支える
- BGM変更が頻繁すぎてsceneのまとまりを壊さない
- fade / volumeを使う場合は音声可聴性を優先する

## Continuity checks

連続scene / shotでは次を確認する。

- characterの左右位置
- scale / framing
- expression change
- cameraの開始・終了状態
- inserted mediaの位置と残存
- BGM継続 / fade
- subtitle safe area
- scene境界のA/V sync

意図したjump cutは問題ではない。意図しないresetだけを修正する。

## Capability mapping

演出案をYAMLへ落とす前に、必要に応じて次で実装可否を確認する。

1. `docs/features.md`
2. `scripts/script_cheatsheet.md`
3. `zundamotion capabilities` / machine-readable contract
4. 対象featureの制限事項

未対応なら次のどれかを選ぶ。

- 現在機能で近い演出へ置換
- asset側で事前生成
- feature request / planningへ分離
- その演出を削る

未実装機能をYAMLへ書いてrender成功を期待しない。

## Render verification

演出追加後は「YAMLがvalidateした」だけで完了にしない。変更範囲に応じて実renderまたは既存の検証経路で次を見る。

- scene開始・終了のframe
- camera / moveの開始位置と終了位置
- characterが意図しない瞬間移動をしていない
- subtitleが読める
- SE/BGMと画面イベントがずれていない
- A/V warningが増えていない
- transition前後でblack frameや残像が出ていない

大きな演出変更では、代表sceneを短くrenderしてから長尺へ広げる。

## Short-form adaptation

長尺から短い動画へ再構成する場合、単純な時間切り抜きではなくbeat単位で扱う。

```text
self-contained question / situation
  ↓
minimum context
  ↓
main change / answer
  ↓
clean ending or next-action
```

元動画の文脈がないと意味不明になる箇所は、短尺側で必要最小限のcontextを追加する。短尺化のために事実や結論を強く言い換えない。

## 完了条件

- 各主要sceneの主役とbeatを説明できる
- camera / motion / sound / subtitleが同じ役割を奪い合っていない
- 使用する演出が現在のZundamotion capabilityへ対応している
- 連続性または意図したjumpのどちらかを説明できる
- render結果で主要な視覚・音響イベントを確認している
