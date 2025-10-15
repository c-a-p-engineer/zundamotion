# Zundamotion YAML台本チートシート

台本（YAML）でよく使う指定方法をコンパクトにまとめたチートシートです。詳細サンプルは [`docs/script_samples.md`](../docs/script_samples.md) も併せて参照してください。

## 目次

- [基本構造](#基本構造)
- [行とシーン](#行とシーン)
- [シーン遷移 (`transition`)](#シーン遷移-transition)
- [キャラクター表示](#キャラクター表示)
  - [立ち絵アニメーション](#立ち絵アニメーション)
- [字幕エフェクト (`subtitle.effects`)](#字幕エフェクト-subtitleeffects)
- [画面全体エフェクト (`screen_effects`)](#画面全体エフェクト-screen_effects)
- [背景エフェクト (`background_effects`)](#背景エフェクト-background_effects)
- [画像・動画の挿入 (`insert`)](#画像動画の挿入-insert)
- [前景オーバーレイ (`fg_overlays`)](#前景オーバーレイ-fg_overlays)
- [効果音 (`sound_effects`)](#効果音-sound_effects)
- [顔アニメ用差分素材](#顔アニメ用差分素材)
- [便利な小ネタ](#便利な小ネタ)

## 基本構造

```yaml
meta:
  title: "動画タイトル"
  version: 1

video:
  fps: 30
  resolution: {width: 1920, height: 1080}

defaults:
  characters_persist: false        # true にするとVNモード（行間で立ち絵を維持）
  characters:
    copetan:
      speaker_id: 3
      speed: 1.0
      pitch: 0.0
      subtitle:
        font_color: "#90EE90"
        stroke_color: "#000000"

scenes:
  - id: intro
    bg: "assets/bg/room.png"
    lines:
      - text: "はじめまして！"
        speaker_name: "copetan"
      - wait: 1.5                       # 無音待ち（秒）
      - text: "次のシーンへ行くのだ"
        screen_effects:
          - type: "screen:shake_screen"
            amplitude: 18
            freq: 6.0
            easing: ease_out
```

## 行とシーン

- `text`: セリフを指定。`speaker_name` で立ち絵／音声話者を切り替え。
- `wait`: `{duration: 2.0}` または数値で無音の間を挿入。
- `transition`: シーン終端に適用する映像トランジション。サンプル: [`sample_transitions.yaml`](./sample_transitions.yaml)。
- `bg`: 背景画像／動画。動画は自動でループ・尺合わせを行う。
- `defaults.characters_persist: true` で VN 風に立ち絵を保持。サンプル: [`sample_vn_minimal.yaml`](./sample_vn_minimal.yaml)。
- 字幕を任意位置で改行したい場合は `text` / `subtitle_text` に `\\n`（YAML では `"行1\\n行2"`）または `<br>` を挿入すると、字幕PNGと SRT/ASS ファイルで複数行表示されます。サンプル: [`sample.yaml`](./sample.yaml)。

## シーン遷移 (`transition`)

```yaml
transition:
  type: "fade"        # fade / dissolve / wipeleft / wiperight など
  duration: 0.8        # 画面が切り替わる秒数
```

- `type`: トランジション方式。`fade`, `dissolve`, `wipe*` 系などを指定。
- `duration`: 効果の長さ（秒）。
- `easing`: 一部のトランジションは `easing` を追加可能（例: `ease_in_out`）。
- シーン単位の指定で、次のシーンへ進む直前に適用されます。
- クリップ間の音声かぶりを避けるため、トランジション適用時には `config.yaml` の `transitions.wait_padding_seconds`（デフォルト 2.0 秒）ぶんの自動 `wait` が挿入されます。
- サンプル台本: [`sample_transitions.yaml`](./sample_transitions.yaml), [`sample_vn_minimal.yaml`](./sample_vn_minimal.yaml)。

## キャラクター表示

```yaml
lines:
  - text: "登場！"
    characters:
      - name: "copetan"
        visible: true
        enter: true              # 登場アニメを有効化（leaveで退場）
        anchor: bottom_center
        position: {x: -480, y: -32}
        scale: 0.9
        expression: "smile"
        effects:
          - type: "char:shake_char"
            amplitude: {x: 20, y: 12}
            freq: 9.0
            easing:
              type: ease_in_out
              power: 1.2
```

- `characters_persist: true` を `defaults` に設定すると、同シーン内で立ち絵状態が自動的に引き継がれ、差分のみ記述すればよくなります。
- `enter_duration` / `leave_duration` と `enter` / `leave` を組み合わせると立ち絵のスライドイン・アウトが可能。
- `expression` は `assets/characters/<name>/<expression>/` の差分素材に対応。
- サンプル台本: [`sample_character_enter.yaml`](./sample_character_enter.yaml)。

### 立ち絵アニメーション

- `char:shake_char`: ランダム風の揺れ。`amplitude`, `freq`, `easing`, `phase_offset` などで制御。サンプル: [`sample_char_shake.yaml`](./sample_char_shake.yaml)。
- `char:bob_char`: 上下バウンド。`amplitude`, `freq`, `offset.y`, `phase_offset(_deg)`, `easing` を指定。サンプル: [`sample_char_bob.yaml`](./sample_char_bob.yaml)。
- `char:sway_char`: 左右スイング。`amplitude`, `freq`, `offset.x`, `phase_offset(_deg)`, `easing` を調整。サンプル: [`sample_char_sway.yaml`](./sample_char_sway.yaml)。
- 今後追加されたアニメーションはここへ追記してください。

## 字幕エフェクト (`subtitle.effects`)

```yaml
lines:
  - text: "着地時に字幕を強調"
    subtitle:
      effects:
        - type: "text:bounce_text"
          amplitude: 40         # バウンドの高さ（ピクセル）
```

- `text:bounce_text`: `abs(sin)` ベースの常時バウンド。設定は `amplitude`（px）だけで、値が大きいほど跳ね上がりが大きくなります。サンプル: [`sample_text_bounce.yaml`](./sample_text_bounce.yaml)。

## 画面全体エフェクト (`screen_effects`)

```yaml
screen_effects:
  - type: "screen:shake_screen"
    amplitude: {x: 24, y: 18}
    freq: 8.0
    easing: ease_out
    padding: 24
```

- `screen:shake_screen`: 画面全体の揺れ。振幅・周波数・減衰 (`easing`) の調整が可能。必要量を自動で `pad` → `crop` し、`padding` を指定すると余白を追加できます。サンプル: [`sample_screen_shake.yaml`](./sample_screen_shake.yaml)。
- 今後追加された screen エフェクトはここに追記してください。

## 背景エフェクト (`background_effects`)

```yaml
lines:
  - text: "背景だけ揺らすカメラ振動"
    background_effects:
      - type: "bg:shake_bg"
        amplitude: {x: 28, y: 18}
        freq: 7.5
        easing:
          type: ease_out
          power: 1.2
```

- `background_effects` はシーン合成前の背景ストリームに適用され、立ち絵や字幕の座標には影響しません。
- `bg:shake_bg`: `pad`→`crop` チェーンで背景のみを平行移動します。`amplitude`, `freq`, `easing`, `offset`, `padding` が指定でき、サンプルは [`sample_bg_shake.yaml`](./sample_bg_shake.yaml) を参照してください。

## 画像・動画の挿入 (`insert`)

```yaml
lines:
  - text: "参考画像はこちら"
    insert:
      path: "assets/bg/room.png"
      duration: 3.0              # 画像のみ有効。動画は自動で尺合わせ
      scale: 0.3
      anchor: bottom_right
      position: {x: -20, y: -20}
      volume: 0.2                # 動画の音量(省略可)
```

## 前景オーバーレイ (`fg_overlays`)

```yaml
fg_overlays:
  - id: logo
    src: assets/overlay/logo.png
    mode: overlay                 # overlay | blend | chroma
    opacity: 0.9
    position: {x: 16, y: 16}
    scale: {w: 512, h: 256, keep_aspect: true}
    timing: {start: 0.0, duration: 5.0, loop: true}
```

- 行レベルの `fg_overlays` はその行のみ、シーンレベルはベース映像へ適用。
- `mode: blend` のときは `blend_mode: screen|add|multiply|lighten` を指定。
- `mode: chroma` のときは `chroma: {key_color, similarity, blend}` を設定。

## 効果音 (`sound_effects`)

```yaml
lines:
  - text: "効果音を鳴らすのだ"
    sound_effects:
      - path: assets/se/rap_fanfare.mp3
        start_time: 0.5
        volume: 0.8
```

- 複数指定可。セリフ開始からの相対秒で再生。
- セリフ無し行でも `sound_effects` のみで使用可能。
- `text: ""` の行は字幕が生成されず、効果音だけを再生できる。
- サンプル: [`sample.yaml`](./sample.yaml)。

## 顔アニメ用差分素材

- 口: `assets/characters/<name>/mouth/{close,half,open}.png`
- 目: `assets/characters/<name>/eyes/{open,close}.png`
- 差分は立ち絵と同じキャンバス／座標系で作成。存在しない場合は自動無効化。

```yaml
video:
  fps: 30
  face_anim:
    mouth_fps: 15
    mouth_thr_half: 0.2
    mouth_thr_open: 0.5
    blink_min_interval: 2.0
    blink_max_interval: 5.0
    blink_close_frames: 2
```

## 便利な小ネタ

- `insert` と `fg_overlays` は併用可能。優先順位は行→シーン→字幕の順。
- `wait` 行はタイムラインにも反映され、動画全体の尺調整に便利。
- `config.yaml` 側の `system.timeline` / `system.subtitle_file` でタイムライン・字幕の自動出力を制御。
- サンプル台本: [`sample.yaml`](./sample.yaml), [`sample_effects.yaml`](./sample_effects.yaml), [`sample_screen_shake.yaml`](./sample_screen_shake.yaml), [`sample_char_bob.yaml`](./sample_char_bob.yaml), [`sample_char_shake.yaml`](./sample_char_shake.yaml), [`sample_char_sway.yaml`](./sample_char_sway.yaml), [`sample_text_bounce.yaml`](./sample_text_bounce.yaml), [`sample_vn_minimal.yaml`](./sample_vn_minimal.yaml), [`sample_transitions.yaml`](./sample_transitions.yaml)。
- 追加の用途別サンプルまとめ: [`docs/script_samples.md`](../docs/script_samples.md)。

> 新しい演出・アニメーションを追加した際は、サンプル台本を用意し、このチートシートに対応情報を追記してください。
