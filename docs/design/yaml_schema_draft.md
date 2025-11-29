# YAMLスキーマ草案（シーン / クリップ / トランジション / テキスト）

時間単位はミリ秒固定。`duration_ms`/`start_ms`/`end_ms`を使用。座標はアンカー基準のピクセル（正規化モードは今後追加可能）。

## 全体構成（トップキー）
- `version`, `meta`, `video`, `audio`, `defaults`, `scenes`
- デフォルト例: トランジション `{type: fade, duration_ms: 800}`、テキストスタイル `{font, size, color, stroke}`、Transform `{anchor, easing}`

## シーン例（抜粋）
```yaml
version: 1
meta:
  title: "Sample Schema"
defaults:
  transition: {type: fade, duration_ms: 800}
  text:
    style: {font: "NotoSans-Bold", size: 48, color: "#FFFFFF", stroke: "#000000"}
  transform:
    anchor: {x: 0.5, y: 0.5}
    easing: ease_in_out

scenes:
  - id: intro
    bg: assets/bg/room.png
    duration_ms: 5000
    clips:
      - id: intro_bg
        src: assets/bg/room.png
        in_ms: 0
        out_ms: 5000
        transform: {position: {x: 0, y: 0}, scale: 1.0, rotate_deg: 0}
        kenburns:
          start_zoom: 1.0
          end_zoom: 1.12
          path: [{x: 0.5, y: 0.55}, {x: 0.45, y: 0.5}]
      - id: char_main
        src: assets/characters/copetan/default.png
        in_ms: 0
        out_ms: 4000
        transform:
          position: {x: -220, y: -80}
          scale: 0.85
          rotate_deg: 0
          anchor: {x: 0.5, y: 1.0}
          easing: ease_out
        motion:
          keyframes:
            - t_ms: 0
              position: {x: -300, y: -120}
              scale: 0.8
            - t_ms: 800
              position: {x: -220, y: -80}
              scale: 0.85
            - t_ms: 3000
              position: {x: -200, y: -60}
              scale: 0.9
    transitions:
      - type: fade
        to_scene: mid
        start_ms: 4500
        duration_ms: 800
    texts:
      - id: intro_telop
        content: "Welcome to Zundamotion"
        start_ms: 500
        end_ms: 2500
        position: {x: 0.5, y: 0.9}
        style:
          font: "NotoSans-Bold"
          size: 64
          color: "#FFFFFF"
          stroke: "#000000"
        shadow: {color: "#00000088", blur: 6, dx: 2, dy: 2}
        animate:
          in: {type: fade, duration_ms: 300}
          out: {type: fade, duration_ms: 300}
```

## キー別フィールド案
- `scenes[]`: `id`(必須), `bg`(必須), `duration_ms`(任意), `clips[]`, `overlays[]`, `transitions[]`, `texts[]`
- `clips[]`: `id`(必須), `src`(必須), `in_ms`/`out_ms`, `transform`(position/scale/rotate_deg/anchor/easing), `kenburns`(start_zoom/end_zoom/path[]), `motion.keyframes[]`で位置・スケール・回転を補間
- `overlays[]`: `src`, `start_ms`/`end_ms`, `blend`(mode/opacity), `transform`, `effects`(プラグインID: blur/eq/hueなど)
- `transitions[]`: `type`(`fade` | `slide_{left,right,up,down}` | `zoom` | `dissolve`), `to_scene`, `start_ms`, `duration_ms`, `params`(direction/scale_from/color)
- `texts[]`: `content`(必須), `start_ms`/`end_ms`, `position`, `style`(font/size/color/stroke/shadow/align), `animate.in/out`(type/duration_ms/delay_ms), `effects`(例: `text:bounce_text`)

## 表現フォーカス
- パン&ズーム（Ken Burns）: `clips[].kenburns`に開始/終了ズームとパス（開始/終了位置）を持ち、長さは`out_ms - in_ms`にフィット
- 位置/スケール/回転アニメ: `clips[].motion.keyframes`で補間し、`easing`で緩急を指定
- シンプルトランジション: `transitions[].type`で`fade`/`slide_*`/`zoom`/`dissolve`を指定。`duration_ms`必須、`start_ms`は省略時シーン終端
- テロップ/テキスト: `texts[]`で時間・位置・スタイル・入退場アニメを保持し、`effects`で追加演出を付与

## バリデーション / デフォルト / 拡張
- 必須: `scene.id`, `clip.id`, `clip.src`, `text.content`, `transition.type`
- デフォルト: `transform.anchor`(0.5,0.5), `easing`(ease_in_out), `transition.duration_ms`(800), `text.style.size`(48), `text.style.font`(NotoSans)
- 整合性: `start_ms < end_ms`を強制し、Ken Burns/motionの長さをクリップ長と一致させる
- 将来拡張: `position_mode`(normalized/pixel), `meta`拡張, `audio`セクション（BGM/SE/J/Lカット）, `render`セクション（出力解像度/ハードウェア設定）
