# Zundamotion YAML台本チートシート

台本（YAML）でよく使う指定方法をコンパクトにまとめたチートシートです。詳細サンプルは `scripts/` 配下の台本も参照してください。

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
    zundamon:
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
        speaker_name: "zundamon"
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
- `transition`: シーン終端に適用する映像トランジション。
- `bg`: 背景画像／動画。動画は自動でループ・尺合わせを行う。

## キャラクター表示

```yaml
lines:
  - text: "登場！"
    characters:
      - name: "zundamon"
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

### 立ち絵アニメーション

- `char:shake_char`: `amplitude`, `freq`, `easing`, `phase_offset` などで揺れを制御。
- `char:bob_char`: `y` 軸のみを低周波サインでバウンス。`amplitude`, `freq`, `offset.y`, `phase_offset(_deg)`, `easing` で揺れ幅や開始位相、収束カーブを調整できる。サンプル: `scripts/test_char_bob.yaml`。
- `char:sway_char`: `x` 軸のみをゆっくり揺らす。`amplitude`, `freq`, `offset.x`, `phase_offset(_deg)`, `easing` で横揺れの幅や方向、時間経過による収束を制御できる。サンプル: `scripts/test_char_sway.yaml`。
- 今後追加されたアニメーションはここへ追記してください。

## 字幕エフェクト（`subtitle.effects`）

```yaml
lines:
  - text: "着地時に字幕を強調"
    subtitle:
      effects:
        - type: "text:bounce_text"
          amplitude: 40         # バウンドの高さ（ピクセル）
```

- `text:bounce_text`: `abs(sin)` ベースの常時バウンド。設定は `amplitude`（px）だけで、値が大きいほど跳ね上がりが大きくなります。サンプル: `scripts/test_text_bounce.yaml`。

## 画面全体エフェクト（screen_effects）

シーン最終合成後に適用されるフィルタ。複数指定で後段適用。

```yaml
screen_effects:
  - type: "screen:shake_screen"
    amplitude: {x: 32, y: 20}      # ピクセル揺れ幅
    freq: 9.0                      # 周波数(Hz)
    easing:
      type: ease_in_out
      power: 1.1
    offset:
      y: -6                        # 静的オフセット
    padding: 24                    # 上下左右に確保する余白
```

- 画面からはみ出さないよう必要量を自動で `pad` → `crop` します。
- `padding` を追加すると揺れ幅より広い余白を確保できます。

## 画像・動画の挿入（`insert`）

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

## 前景オーバーレイ（`fg_overlays`）

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

## 効果音（`sound_effects`）

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
- サンプル台本: `scripts/sample.yaml`, `scripts/sample_effects.yaml`, `scripts/sample_screen_shake.yaml`, `scripts/test_char_bob.yaml`, `scripts/test_char_sway.yaml`, `scripts/test_text_bounce.yaml`。

> 新しい演出・アニメーションを追加した際は、サンプル台本を用意し、このチートシートに対応情報を追記してください。
