# Video Direction and Render QA

## 目的

YAML台本を単に「要素を配置して動画へ変換する入力」として扱わず、**scene → shot → camera → character/action → text/audio → render verification** の順で、視聴者が何を見るかを設計・確認する。

この文書は演出と実動画QAを担当する。YAML構文の正本は `scripts/script_cheatsheet.md`、実装構造は `project_structure.md`、FFmpeg詳細は `docs/design/ffmpeg_filter_mapping.md` を優先する。

## 演出単位

### Scene

一つの意味・話題・場所・時間帯・説明目的を共有するまとまり。

最低限:

```text
scene purpose
viewer should understand / feel
entry state
exit state
required assets
```

### Shot

scene内でカメラまたは画面構成が一つの役割を担う区間。

```text
subject
framing
camera change
character action
on-screen text
sound cue
beat / duration intention
```

shot数を増やすことを目的にしない。画面変化が理解・感情・テンポへ寄与しない場合はscene内で維持してよい。

## Direction pass

台本または生成前に、必要な箇所だけ次を確認する。

1. **focus** — その瞬間に最初に見てほしい対象は何か
2. **framing** — 全身・半身・寄り・背景主体など、情報量と感情距離が合うか
3. **motion** — キャラ移動、scale、camera pan/zoomが同時に競合していないか
4. **rhythm** — 字幕を読む時間、音声の間、SE、画面変化の密度が合うか
5. **continuity** — 前後shotで位置・向き・scale・表情が理由なく飛んでいないか
6. **hierarchy** — 字幕・立ち絵・挿入画像・装飾が同時に主役になっていないか

## Camera / Motion guardrails

- camera moveは「動いている方が豪華」だから追加しない。注目対象の移動、情報開示、感情距離の変化等の役割を持たせる
- character moveとcamera moveを同時に使う場合、視聴者が追う基準点を一つ決める
- zoom / pan / scale変更後に次sceneへ状態が意図せず持ち越されないか確認する
- 速い移動では終点だけでなく途中frameの画面外逸脱、字幕被り、補間の不自然さを確認する
- 縦動画では横方向の余白が少ないため、16:9の構図を単純cropしただけにしない

## Audio / Subtitle coordination

- 字幕は音声内容の複製ではなく、読める時間と行長を優先する
- SEが台詞の聞き取りを妨げる場合はタイミングまたはvolumeを調整する
- BGM fadeやscene transitionで無音・二重音・急なvolume jumpが生じないか確認する
- 音声なしの挿入区間でも、視聴者が「停止した」と誤認する長さにならないか確認する

## Render QA

実装・台本・演出変更後、metadataやcommand成功だけで完成判定せず、必要な代表状態を**実動画またはframe**で確認する。

### Smoke path

1. 動画が開始する
2. 最初の音声・字幕・立ち絵が期待どおり出る
3. scene transitionを一つ以上通過する
4. move / zoom / overlay等、変更対象の主要verbを通過する
5. 最終frame / audioまで到達する

### Visual checks

- 立ち絵のanchor、scale、表情差分が切替時に飛ばない
- subtitleが安全領域を外れず、キャラの重要部位を不要に隠さない
- overlayや挿入画像のz-orderが意図どおり
- 透明素材の縁、rotate、scaleでartifactが出ていない
- transition前後でblack frameや一瞬の旧frame残留がない
- 9:16 / 16:9等、対象解像度でcrop・余白・文字サイズが成立する

### Temporal / audio checks

- A/V sync driftがない
- scene境界でaudioが切れすぎる／重なる問題がない
- `enable` 区間外へoverlay・字幕・effectが漏れない
- frame rate / setpts / concat変更時にdurationが意図せず変わらない
- cache利用時も非cache時と意味上同じ出力になる

## Representative-state strategy

長尺動画を毎回全frame目視する代わりに、変更のblast radiusに応じて代表状態を選ぶ。

```text
before change boundary
at change start
mid-transition / mid-motion
at change end
next scene / adjacent state
```

ただし、A/V sync、長時間drift、終端処理など時間経過自体が問題になる変更では、短いframe抽出だけで完了判定しない。

## Shorts / Clip extraction

長尺からShortsや短いclipを作る場合、単純な秒数分割ではなく一つの小さな完結単位を取る。

```text
hook / question
  ↓
minimal context
  ↓
payoff / answer / reveal
  ↓
clean ending or intentional continuation
```

- 元動画の字幕がcrop後も読めるか再確認する
- 横動画の左右情報に依存する場面は縦版用にreframeする
- 文脈不足で意味が反転するcutを避ける
- clip専用のテンポ調整を行っても、元台本の事実・発言意味を変えない

## 完了条件

- scene/shotの役割が変更意図と一致する
- 主要verbを含むsmoke pathを実動画で確認した
- 変更境界と隣接状態を視覚的に確認した
- A/V syncやdurationへ影響する変更では時間軸の検証を実施した
- 対象aspect ratioで字幕・キャラ・挿入素材が成立する
- 実行していないrender / visual checkを完了済みと報告していない
