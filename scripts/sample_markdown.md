---
# サンプル識別用のメタ情報です。
meta:
  title: sample-markdown-restricted
  version: 3
# 出力動画の基本サイズです。
video:
  width: 1280
  height: 720
  fps: 30
# 字幕全体の既定値です。話者ごとの色は defaults.characters.*.subtitle で上書きできます。
subtitle:
  font_path: /usr/share/fonts/opentype/ipafont-gothic/ipag.ttf
  font_size: 40
  font_color: "#FFFFFF"
  wrap_mode: chars
  max_chars_per_line: auto
  max_pixel_width: 860
  stroke_color: "#101828"
  stroke_width: 3
  background:
    color: "#111827"
    opacity: 0.68
    radius: 28
    padding: {x: 42, y: 22}
# Markdown パネル自体の位置・幅・見た目を制御します。
markdown:
  layer:
    scale: 0.94
    anchor: middle_center
    position: {x: 0, y: 0}
  panel:
    margin: {x: 140, y: 28}
    padding: {x: 56, y: 42}
    background:
      color: "#0F172A"
      opacity: 0.92
      border_color: "#E2E8F0"
      border_width: 3
      border_opacity: 0.8
      radius: 28
  text:
    font_path: /usr/share/fonts/opentype/ipafont-gothic/ipag.ttf
    font_size: 50
    min_font_size: 30
    line_spacing: 12
    color: "#F8FAFC"
# シーン全体の背景です。
bg: assets/bg/room.png
# キャラクターの既定値です。位置や字幕色もここで話者別に管理できます。
defaults:
  speed: 1.05
  pause: 0.2
  characters:
    copetan:
      speaker_id: 3
      style: smile
      position: {x: -200, y: 650}
      scale: 0.82
      anchor: bottom_left
      mouth_sync: true
      subtitle:
        font_color: "#FDE68A"
        stroke_color: "#7C2D12"
    engy:
      speaker_id: 8
      style: default
      position: {x: 200, y: 650}
      scale: 0.82
      anchor: bottom_right
      mouth_sync: true
      subtitle:
        font_color: "#BFDBFE"
        stroke_color: "#1E3A8A"
---
# Markdown台本
ずんだモーション向けの
制限Markdown仕様です

copetan: 今日は台本形式を定義します。
engy: 仕様は「地の文は画像化、話者付き行はセリフ化」です。

## ここは次の画像ブロック
セリフとセリフの間にあるMarkdownが
新しい画像として表示されます。

- 箇条書きも Markdown の見た目で表示したい
- `#` をそのまま出すのではなく見出しとして扱いたい
copetan: この行で画像が切り替わります。
engy: 次の行もセリフなので画像は切り替わりません。

### キャラクターなし説明
キャラクター定義があっても
ナレーション中心で進めたい箇所を書けます。

copetan: このサンプルではキャラクターは常時表示されたままです。
copetan: 背景はfrontmatterのbgで固定し、シーン内では切り替えません。
