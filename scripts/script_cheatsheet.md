# Zundamotion YAML台本チートシート

台本（YAML）でよく使う指定方法をコンパクトにまとめたチートシートです。詳細サンプルは [`docs/script_samples.md`](../docs/script_samples.md) も併せて参照してください。

> Markdown入力を使う場合は [`sample_markdown.md`](./sample_markdown.md) を参照してください。frontmatter の `markdown.layer` / `markdown.panel` / `markdown.text` で、画像化パネルの位置・枠色・余白・フォントサイズを調整できます。

## 目次

- [基本構造](#基本構造)
- [動画キャンバスと背景設定](#動画キャンバスと背景設定)
- [字幕設定](#字幕設定)
- [行とシーン](#行とシーン)
- [プラグイン設定](#プラグイン設定)
- [台本の再利用 (`include` / `vars`)](#台本の再利用-include--vars)
- [音声なしで生成する](#音声なしで生成する)
- [シーン遷移 (`transition`)](#シーン遷移-transition)
- [キャラクター表示](#キャラクター表示)
  - [立ち絵アニメーション](#立ち絵アニメーション)
- [字幕エフェクト (`subtitle.effects`)](#字幕エフェクト-subtitleeffects)
- [テキストバッジ (`badge`)](#テキストバッジ-badge)
- [画面全体エフェクト (`screen_effects`)](#画面全体エフェクト-screen_effects)
- [背景エフェクト (`background_effects`)](#背景エフェクト-background_effects)
- [画像・動画の挿入 (`insert`)](#画像動画の挿入-insert)
- [前景オーバーレイ (`fg_overlays`)](#前景オーバーレイ-fg_overlays)
- [BGM と音声チューニング](#bgm-と音声チューニング)
- [Topic（チャプター）](#topicチャプター)
- [音声・映像フィルタ](#音声映像フィルタ)
- [効果音 (`sound_effects`)](#効果音-sound_effects)
- [顔アニメ用差分素材](#顔アニメ用差分素材)
- [読みと字幕テキストの制御](#読みと字幕テキストの制御)
- [便利な小ネタ](#便利な小ネタ)

## プラグイン設定

組み込みエフェクトはレジストリにキャッシュ済みで即座に利用できます。外部プラグインを試す場合は `plugins` ブロックを設定します。

```yaml
plugins:
  enabled: true            # false でドロップインを全て無効化
  paths: ["./plugins"]      # スキャン対象の追加ディレクトリ
  allow: []               # 許可IDを列挙（空なら全許可）
  deny: []                # 拒否IDを列挙（allow より優先）
```

- CLI から追加する場合: `python -m zundamotion.main --plugin-path ./my_plugins --plugin-allow my-blur`
- レジストリ動作をまとめて確認したい場合は [`scripts/sample_registry_smoke.yaml`](./sample_registry_smoke.yaml) を実行すると、字幕とオーバーレイの両方でプラグイン読み込み・順序維持を検証できます。

## 台本の再利用 (`include` / `vars`)

台本を分割して `include` で再利用したり、`vars` で文字列を差し込めます。`${VAR}` 形式の文字列置換のみ対応しています。

```yaml
vars:
  EP: 12
  TITLE: "S3 consistency"

defaults:
  include:
    - presets/defaults_base.yaml
    - presets/subtitle_shorts.yaml
  subtitle:
    max_lines: 2

scenes:
  - include: parts/intro.yaml
  - include: parts/outro.yaml
    transition:
      video: fade
      duration: 0.25
```

- `include` はシーン配列にも、`defaults`/`assets`/`overlays` などの非シーンセクションにも使えます。
- 非シーンの `include` は深いマージで合成し、配列は後勝ち（置換）です。
- `transition` は `include` 呼び出し側で指定し、直前のシーン終端に適用されます。
- サンプル台本: [`sample_include_vars.yaml`](./sample_include_vars.yaml)。

## 音声なしで生成する

VOICEVOX を使わず、無音の音声トラックを自動生成して動画を作る場合は `--no-voice` を指定します。
セリフの長さから推定した秒数で無音を作成します。明示的に長さを指定したい場合は `duration` か
`estimated_duration` を行に指定してください。

```bash
DISABLE_HWENC=1 python -m zundamotion.main scripts/sample_include_vars.yaml \\
  --no-voice --no-cache -o output/sample_include_vars_no_voice.mp4
```

```yaml
scenes:
  - id: intro
    lines:
      - text: "音声なしで生成"
        duration: 2.5
```

## 基本構造

```yaml
meta:
  title: "動画タイトル"
  version: 1

video:
  width: 1920
  height: 1080
  fps: 30
  resolution: {width: 1920, height: 1080}

defaults:
  characters_persist: false        # true にするとVNモード（行間で立ち絵を維持）
  background_persist: false        # true にすると行間で直前の背景を維持
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

- `meta.version` はツール側のフォーマット互換性を示します。最新の値は [`sample.yaml`](./sample.yaml) を参照してください。
- `video.width` / `video.height` は出力キャンバスの解像度。旧 `resolution` キーもサポートされていますが、新規は幅・高さの個別指定を推奨します。縦長レイアウト例: [`sample_vertical.yaml`](./sample_vertical.yaml)。
- `video.face_anim` を設定すると口パク／瞬き制御が行えます。閾値やフレーム数は [`sample.yaml`](./sample.yaml) を参照。
- `defaults.characters` で VOICEVOX `speaker_id` や字幕色などキャラクターごとの初期値をまとめて定義できます。

## 動画キャンバスと背景設定

```yaml
video:
  background_fit: contain      # contain / cover / fit_width / fit_height

background:
  default: assets/bg/room.png
  fill_color: "#0F172A"
  anchor: middle_center
```

- `video.background_fit` で背景のフィットモードを指定。余白の扱いは `background.fill_color` に従います。縦長キャンバスの比較: [`sample_vertical.yaml`](./sample_vertical.yaml)。
- ルート `background` はシーンで `bg` が未指定の場合のデフォルト。`anchor` / `position` / `fit` はシーンや行ごとにも上書き可能です。
- 行レベルの `background` でズームやパンを切り替えることで、同じ素材でも構図を変えられます。
- `defaults.background_persist: true` またはシーンの `background_persist: true` を指定すると、`background.path` を指定した行以降は、省略行でも直前の背景を使い続けます。`false` の場合、省略行はシーンの `bg` またはルート `background.default` に戻ります。

```yaml
defaults:
  background_persist: true

scenes:
  - id: lesson
    bg: assets/slides/01-cover.png
    lines:
      - text: "表紙です。"
      - text: "2枚目へ切り替えます。"
        background: {path: assets/slides/02-topic.png}
      - text: "この行も 02-topic.png のままです。"
```

## 字幕設定

```yaml
subtitle:
  render_mode: png          # png / auto / ass
  font_path: /path/to/font.ttf
  size: 48
  color: "white"
  outline: "black"
  wrap_mode: chars
  max_chars_per_line: auto  # max_pixel_width から自動推定も可
  max_pixel_width: 960
  background:
    show: true
    color: "#000000"
    opacity: 0.65
  reading_display: paren      # none / paren
```

- ルート `subtitle` でフォントパスや文字数制御など全体の既定値をまとめます。例: [`sample.yaml`](./sample.yaml)。
- `subtitle.max_chars_per_line` は字幕折り返しの最大表示幅として扱います。全角は `1.0`、ASCII 英数字や半角記号や半角スペースは `0.5` 相当で数えます。
- `max_chars_per_line: auto` を使うと、実際のフォント幅と `max_pixel_width` から字幕ごとに折り返し文字数を推定します。空白のない日本語字幕向けです。
- `subtitle.background.show: false` で字幕ボックスを非表示にできます。`color` と `opacity` で色と透過率を調整します。
- `subtitle.render_mode` で動画への字幕焼き込み方式を指定できます。既定は `png` です。
- `render_mode: png` は全字幕をPNGで焼き込みます。角丸・枠線・背景画像・字幕エフェクトなどの見た目を優先する通常モードです。
- `render_mode: auto` は、背景色・透過率だけの軽いボックスを `ASS/libass`、背景画像・字幕エフェクトなどPNG必須の字幕を `PNG` で描画します。
- `render_mode: ass` は可能な限り `ASS/libass` を使います。ただし背景画像や字幕エフェクトなどASSで表現できない装飾がある場合は、安全側で `PNG` にフォールバックします。
- `ASS` の背景ボックスは仕様上、独立した枠線色や角丸をPNGと同じ見た目で再現できません。見た目を優先する場合は `png`、速度検証や軽量字幕では `auto` / `ass` を使います。サンプル: [`sample_subtitle_styles.yaml`](./sample_subtitle_styles.yaml), [`sample_subtitle_render_modes.yaml`](./sample_subtitle_render_modes.yaml)。
- 行ごとの `subtitle` ブロックで色や余白などを一時的に上書き可能です。
- `defaults.characters.<name>.subtitle` で話者ごとの字幕色や縁色を既定化できます。例: [`sample_markdown.md`](./sample_markdown.md)。
- 字幕PNGだけ改行したい場合は `subtitle_text` に `"行1\n行2"` を設定します。読み仮名は `reading` で別途管理できます。
- SRT/ASSファイルだけ動画より少し早い、または遅い場合は `system.subtitle_file.offset_seconds` で出力字幕ファイル全体を秒単位でずらせます。正の値は字幕ファイルを遅らせ、負の値は早めます。動画に焼き込むPNG字幕のタイミングは変わりません。

```yaml
system:
  cache_dir: ".cache/zundamotion" # キャッシュ保存先
  subtitle_file:
    enabled: true
    format: srt          # srt / ass / both
    offset_seconds: 0.5  # SRT/ASSファイルだけ0.5秒遅らせる
```

## 行とシーン

- `text`: セリフを指定。`speaker_name` で立ち絵／音声話者を切り替え。
- `wait`: `{duration: 2.0}` または数値で無音の間を挿入。
- `transition`: シーン終端に適用する映像トランジション。サンプル: [`sample_transitions.yaml`](./sample_transitions.yaml)。
- `bg`: 背景画像／動画。動画は自動でループ・尺合わせを行う。
- `defaults.characters_persist: true` で VN 風に立ち絵を保持。サンプル: [`sample_vn_minimal.yaml`](./sample_vn_minimal.yaml)。
- 字幕を任意位置で改行したい場合は `text` / `subtitle_text` に `\\n`（YAML では `"行1\\n行2"`）または `<br>` を挿入すると、字幕PNGと SRT/ASS ファイルで複数行表示されます。サンプル: [`sample.yaml`](./sample.yaml)。

### キャッシュを効かせやすいシーン分割

長い台本は 1 つの `main` シーンにまとめすぎず、トピックや章ごとにシーンを分けると再生成が扱いやすくなります。
Zundamotion はシーン単位の動画キャッシュを持つため、一部の章だけを修正した場合、変更していないシーンのキャッシュを再利用しやすくなります。

```yaml
scenes:
  - id: main_intro
    bg: assets/slides/01-cover.png
    items:
      - topic: "導入"
      - say:
          text: "今日は設計の話です。"

  - id: main_topic_a
    bg: assets/slides/02-topic-a.png
    items:
      - topic: "考え方"
      - say:
          text: "ここから本題です。"
```

注意:

- 1 スライド 1 シーンまで細かくする必要はありません。章、トピック、数枚のスライド単位を目安にします。
- `characters_persist` と `background_persist` は同一シーン内の継続です。シーンを分けた場合は、各シーン冒頭で必要な `characters` や `bg` を明示してください。
- `characters_persist: true` のとき、`wait` 行でも直前の立ち絵状態を自動継承します。待機中だけ別の立ち絵にしたい場合に限って `wait` 行へ `characters` を明示します。
- シーン境界で `transition` を指定すると、その境界ごとに遷移処理が入ります。単にキャッシュ粒度を分けたいだけなら、遷移を指定しない通常のシーン分割で十分です。

### 複数キャラクターの同時発話

`voice_layers` にキャラクターごとのボイス設定を列挙すると、同じ行で複数の音声をミックスできます。
レイヤーには `speaker_name` を必須指定し、必要に応じて `text` / `reading` / `speed` などを個別に上書きします。

サンプル台本: [`sample_voice_layers.yaml`](./sample_voice_layers.yaml)

```yaml
lines:
  - text: "二人揃ってご挨拶！"
    voice_layers:
      - speaker_name: "copetan"
        text: "二人揃ってご挨拶！"
      - speaker_name: "engy"
        text: "二人揃ってご挨拶！"
        start_time: 0.0   # ずらしたい場合は秒数指定（省略時は0）
        volume: 0.9       # 個別音量（0.0〜1.0、省略時は1.0）
```

`voice_layers` の各エントリには `defaults.characters.<name>` の `speaker_id` や `speed` が自動適用されるため、既存のキャラクターデフォルトをそのまま活用できます。

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
        flip_x: true             # true でキャラクター画像を左右反転
        flip_y: false            # true でキャラクター画像を上下反転
        expression: "smile"
        asset_name: "copetan"     # 別名キャラが共有する素材ディレクトリ名
        color_filter:             # 元PNGのRGBだけをHSV変換し、透明度は維持
          hue: 210                # 色相シフト: 0〜360
          saturation: 1.2         # 彩度倍率: 0以上
          brightness: 1.0         # 明度倍率: 0以上
          targets:                # 指定時は対象領域・対象色ごとの部分色替えも追加適用
            - name: hair
              region:
                type: top
                ratio: 0.45
              select:
                color:
                  mode: luma
                  min: 0
                  max: 90
              adjust:
                hue: 340
                saturation: 1.6
                brightness: 1.35
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
- `asset_name` を指定すると、`name` は別名のまま `assets/characters/<asset_name>/` の素材を共有できます。色違いキャラクターを独立して同時表示するときに使います。
- `flip_x: true` で立ち絵、口パク、目パチ差分をまとめて左右反転できます。右向き素材を左向きにしたい時に使います。
- `flip_y: true` で同じ対象を上下反転できます。上下反転の確認や特殊演出に使えます。
- `color_filter` は Pillow でベース立ち絵と口パク・目パチ差分PNGを事前変換し、同じ元画像と設定ではキャッシュを再利用します。未指定時は元画像をそのまま使います。
- 既存形式の `hue` / `saturation` / `brightness` は従来通り画像全体へ適用します。
- `color_filter.targets` を使うと、画像上部 / 下部 / 矩形領域のうち、指定した色域だけを部分色替えできます。
- `region.type` は `top`, `bottom`, `rect` をサポートします。`top` / `bottom` の `ratio`、`rect` の `x`, `y`, `width`, `height` はすべて 0.0〜1.0 の比率指定です。
- `select.color.mode` は `luma` と `rgb_distance` をサポートします。`luma` は明るさ帯で選択、`rgb_distance` は指定 hex 色との近さで選択します。
- `targets` と全体指定を併用した場合は、全体色替えを先に適用し、そのあと `targets` を順番に追加適用します。
- 黒髪や黒服は `hue` だけでは変化が弱いため、`brightness` と `saturation` も上げます。ただし線画まで壊れやすいので、`luma.max` を上げすぎないでください。
- サンプル台本: [`sample_character_enter.yaml`](./sample_character_enter.yaml), [`sample_character_flip.yaml`](./sample_character_flip.yaml), [`sample_character_color_filter.yaml`](./sample_character_color_filter.yaml)。

### `color_filter` 例

#### 値の考え方

- `hue` は「何色に寄せるか」です。目安として `0` は赤、`30` はオレンジ、`60` は黄、`120` は緑、`180` はシアン、`210` は青、`270` は紫、`330` は赤紫です。
- `saturation` は「色の濃さ」です。`1.0` は元のまま、`1.2` から `1.4` は少し鮮やか、`1.5` 以上はかなり強め、`0.3` 付近まで下げると色が抜けて灰色寄りになります。
- `brightness` は「明るさ」です。`1.0` は元のまま、`1.1` から `1.25` は少し明るい、`1.3` 以上は黒髪や黒服を別色に起こしたい時向け、`0.8` 前後は暗く沈めたい時向けです。
- 黒に近い部分は、`hue` だけ変えてもあまり色が出ません。黒髪を赤や青にしたい時は `saturation: 1.4` 以上、`brightness: 1.2` 以上から試す方が変化を確認しやすいです。
- 逆に白や肌まで巻き込むと不自然になるので、部分色替えでは `luma.max` を低めに保ちます。黒髪ならまず `70` から `90`、黒服なら `60` から `80` が出発点です。

#### よくある狙いと値の目安

| 狙い | まず試す値 | 補足 |
| --- | --- | --- |
| 少し青くする | `hue: 210`, `saturation: 1.15`, `brightness: 1.0` | 全体色替えの軽い色違い向け |
| はっきり青髪にする | `hue: 220`, `saturation: 1.45`, `brightness: 1.25` | 黒髪なら `targets` + `luma` 併用推奨 |
| 赤髪にする | `hue: 350`, `saturation: 1.55`, `brightness: 1.3` | 朱色っぽければ `hue: 10` 付近も試す |
| ピンク寄りにする | `hue: 330`, `saturation: 1.45`, `brightness: 1.28` | 黒髪を柔らかく変えたい時向け |
| 緑髪にする | `hue: 120`, `saturation: 1.35`, `brightness: 1.18` | 暗すぎると緑が濁るので少し明るめが無難 |
| 黒っぽく戻す / 落ち着かせる | `saturation: 0.6`, `brightness: 0.82` | `hue` は省略可。彩度を落として暗くする |
| 銀髪・色を抜く | `saturation: 0.2`, `brightness: 1.3` | 完全な白にはならないので元絵依存 |

#### 調整のコツ

1. まず `region` で髪や服の大まかな場所だけに絞る。
2. 次に `luma` か `rgb_distance` で対象色を狭める。
3. そのあと `hue` だけ決める。
4. まだ黒くて色が出ないなら `saturation` と `brightness` を上げる。
5. 肌や線画まで変わるなら `luma.max` を下げるか、`rect` / `rgb_distance` に切り替える。

全体色替え:

```yaml
color_filter:
  hue: 210
  saturation: 1.2
  brightness: 1.0
```

髪色だけ変える:

```yaml
color_filter:
  targets:
    - name: hair
      region:
        type: top
        ratio: 0.45
      select:
        color:
          mode: luma
          min: 0
          max: 90
      adjust:
        hue: 340
        saturation: 1.6
        brightness: 1.35
```

- `hue: 340` は赤紫寄りです。赤を強めたければ `350` 前後、ピンク寄りなら `320` から `330` も試せます。
- 黒髪で色が出ない時は、まず `brightness` を `1.2` から `1.35` の範囲で上げます。
- 前髪以外の顔影まで巻き込むなら、`ratio` を `0.40` へ下げるか `max` を `75` 前後に下げます。

服色だけ変える:

```yaml
color_filter:
  targets:
    - name: clothes
      region:
        type: bottom
        ratio: 0.65
      select:
        color:
          mode: luma
          min: 0
          max: 80
      adjust:
        hue: 220
        saturation: 1.3
        brightness: 1.0
```

- `hue: 220` は青系です。制服や上着を寒色へ寄せたい時の出発点です。
- 黒服を青くしたいのに変化が弱いなら、`brightness: 1.12` から `1.2` を足します。
- 白シャツや肌まで混ざるなら `ratio` を少し下げるか、`luma.max` を `70` 付近まで絞ります。

矩形範囲の近似色だけ変える:

```yaml
color_filter:
  targets:
    - name: ribbon
      region:
        type: rect
        x: 0.18
        y: 0.00
        width: 0.64
        height: 0.42
      select:
        color:
          mode: rgb_distance
          color: "#1a1a1a"
          tolerance: 40
      adjust:
        hue: 220
        saturation: 1.3
        brightness: 1.0
```

- `rgb_distance` は「この色に近い部分だけ変えたい」時向けです。リボン、ネクタイ、ワンポイント装飾のような狭いパーツで使います。
- `tolerance` は小さいほど厳密です。まず `25` から `40`、広げたければ `50` 前後を試します。
- 指定色がよく分からない時は、画像編集ソフトのスポイトで元色を拾って `#rrggbb` で入れます。

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
- オーバーレイと字幕エフェクトのレジストリ挙動を同時に確認するスモーク: [`sample_registry_smoke.yaml`](./sample_registry_smoke.yaml)。

## テキストバッジ (`badge`)

「頻出」「重要」「暗記」「注意」のような短いラベルを、動画上部の固定サイズバッジとして表示します。再利用したい定義は `scenes` の外に top-level `badges` として置けます。

```yaml
badges:
  - id: important-top
    text: "重要"
    position: "top-right"
    visible: false

scenes:
  - id: topic
    bg: assets/bg/room.png
    lines:
      - id: intro
        text: "シーン全体にバッジを出します。"
        badges:
          - id: important-top
            visible: true
      - text: "この行だけ複数バッジも出せます。"
        badges:
          - text: "長い文でも自動で幅が伸びる注意バッジ"
            position: "top-left"
            timing: {start: 0.3, end: 1.2}
          - text: "補足"
            position: "top-right"
            timing: {start: 0.1, end: 1.0}
      - id: summary
        text: "ここで scene バッジを閉じます。"
        badges:
          - id: important-top
            visible: false
```

- top-level `badges` は共有定義です。全 scene で再利用でき、scene ごとに同じ定義を書き直す必要がありません。
- `badges` はシーンレベルと行レベルでも使えます。複数バッジを並べたい場合の基本形です。
- `badges` を scene に置くと、その scene 専用の持続バッジ定義、または共有定義と同じ `id` の scene 上書きを並べられます。各要素は `id` 必須、`visible` 既定 `false` です。
- `line.badges` で `{id: "...", visible: true/false}` を指定すると、character に近い感覚でその発話以降の表示状態を切り替えられます。必要なら text/style の上書きも可能です。
- `line.badges` には `id` なしの完全なバッジ定義も書けます。その場合はその行だけに複数バッジを直接表示します。
- `text` は必須の短い文字列です。
- `position` は必須で、`top-left` / `top-center` / `top-right` / `bottom-left` / `bottom-center` / `bottom-right` を指定します。
- `font_size` / `font_color` / `stroke_color` / `stroke_width` / `background` を指定できます。`background` は字幕と同じく `show`, `color`, `opacity`, `radius`, `border_color`, `border_width`, `border_opacity`, `padding` を使えます。
- バッジ幅は文字数と padding に応じて自動で伸びます。`min_width` / `max_width` で下限と上限も指定できます。
- `timing.start` / `timing.end` は秒指定です。`end` を省略すると、そのシーンまたは行の終わりまで表示します。
- scene-level の持続バッジは `timing.show_on_line` / `timing.hide_on_line` でも制御できます。値は 1-based 行番号または `line.id` です。`hide_on_line` はその行の開始時刻で非表示になります。
- 既存互換として単体の `badge` も使えますが、新規では `badges` を推奨します。
- バッジは内部で角丸 PNG を生成して `fg_overlays` と同じ経路で合成します。既存動画に `badge` が無ければ挙動は変わりません。
- サンプル: [`sample_badge.yaml`](./sample_badge.yaml)。

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
- `offset` で揺れの中心をずらして、画面全体が常に上下に動かないよう微調整できます。
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

## 画像レイヤー (`image_layers`)

```yaml
lines:
  - text: "参考画像を表示"
    image_layers:
      - show:
          id: "room_thumb"
          path: "assets/bg/room.png"
          scale: 0.3
          anchor: bottom_right
          position: {x: -20, y: -20}
          transition:
            in: {type: "fade", duration: 0.6}
            out: {type: "fade", duration: 0.4}
  - image_layers:
      - hide:
          id: "room_thumb"
          transition:
            out: {type: "fade", duration: 0.4}
```

- `image_layers` は行境界で show/hide を明示し、シーン内の任意タイミングで画像を表示/終了できます。
- `transition` は `fade` / `none` を選択可能。`fade` 時は `duration` を必須指定。
- 画像は立ち絵より背面に合成されます（`insert` と同じレイヤー位置）。

## 前景オーバーレイ (`fg_overlays`)

```yaml
fg_overlays:
  - id: logo
    src: assets/overlay/logo.png
    mode: overlay                 # overlay | blend | chroma
    opacity: 0.9
    blink: {interval: 0.2, duty: 0.5, min_opacity: 0.0, max_opacity: 1.0}
    position: {x: 16, y: 16}
    scale: {w: 512, h: 256, keep_aspect: true}
    timing: {start: 0.0, duration: 5.0, loop: true}
```

主なキー:

| キー | 必須 | 意味 | 例 |
|---|---:|---|---|
| `id` | 任意 | オーバーレイを識別する名前。ログや台本上の見通し用。未指定でも合成は可能。 | `warning_blink` |
| `src` | 必須 | 重ねる素材のパス。PNG/JPG/WebPなどの静止画、またはMP4などの動画を指定。 | `assets/overlay/warning.png` |
| `mode` | 任意 | 合成方式。通常は `overlay`。光素材は `blend`、単色背景を抜く場合は `chroma`。 | `overlay` |
| `opacity` | 任意 | 全体の透明度。`1.0` が不透明、`0.0` が完全透明。`blink` と併用すると、この透明度をかけた後に点滅する。 | `0.8` |
| `position.x` | 任意 | 左上基準の横位置(px)。0なら画面左端。 | `420` |
| `position.y` | 任意 | 左上基準の縦位置(px)。0なら画面上端。 | `250` |
| `scale.w` | 任意 | リサイズ後の幅(px)。 | `1080` |
| `scale.h` | 任意 | リサイズ後の高さ(px)。 | `360` |
| `scale.keep_aspect` | 任意 | `true` の場合、縦横比を維持して `w` x `h` の枠内に収める。余白は透過で埋める。 | `true` |
| `fps` | 任意 | 静止画を動画入力化するときのFPS。点滅や揺れなどフレーム単位の効果を安定させたい場合に指定。 | `30` |
| `timing.start` | 任意 | overlay を表示し始める時刻。シーンまたは行クリップの先頭からの秒数。 | `0.0` |
| `timing.duration` | 任意 | overlay を表示する秒数。省略すると `start` 以降、対象クリップの終わりまで表示。 | `2.0` |
| `timing.loop` | 任意 | 動画素材をループ入力する。静止画像は自動的に必要尺まで伸ばされるため通常不要。 | `true` |
| `blink.interval` | 任意 | 点滅1周期の秒数。小さいほど速く点滅する。`0.2` なら0.2秒で1周期。 | `0.2` |
| `blink.duty` | 任意 | 1周期のうち `max_opacity` で表示する割合。`0.5` なら半分点灯、半分消灯。 | `0.5` |
| `blink.min_opacity` | 任意 | 消灯側の透明度倍率。`0.0` なら完全に消える。`0.3` なら薄く残る。 | `0.0` |
| `blink.max_opacity` | 任意 | 点灯側の透明度倍率。通常は `1.0`。 | `1.0` |
| `effects` | 任意 | overlay 素材だけにかける見た目の効果。`shake` などを指定できる。背景や字幕は揺れない。 | `[{type: shake}]` |

- 行レベルの `fg_overlays` はその行のみ、シーンレベルはベース映像へ適用。
- `mode: blend` のときは `blend_mode: screen|add|multiply|lighten` を指定。
- `mode: chroma` のときは `chroma: {key_color, similarity, blend}` を設定。
- 静止画オーバーレイでも `fps` を指定するとフレーム補間され、アニメ的な動きを加えられます。
- `blink` は静止画/動画オーバーレイの alpha だけを周期的に変化させます。省略時は点滅しません。`interval <= 0` は無視され、`duty` は `0.0 < duty <= 1.0`、`min_opacity` / `max_opacity` は `0.0–1.0` に丸められます。`opacity` と `effects` は併用できます。
- `effects` チェーンで `blur` / `eq` / `rotate` などのポストエフェクトを順番に適用可能。`timing` の `loop` や `start` で再生タイミングを制御できます。詳しくは [`sample_effects.yaml`](./sample_effects.yaml), [`sample.yaml`](./sample.yaml)。
- オーバーレイのレジストリ化と字幕効果の同時スモークテスト: [`sample_registry_smoke.yaml`](./sample_registry_smoke.yaml)。

点滅例:

```yaml
fg_overlays:
  - id: warning
    src: assets/overlay/warning.png
    mode: overlay
    opacity: 1.0
    position: {x: 300, y: 200}
    scale: {w: 900, h: 300, keep_aspect: true}
    blink:
      interval: 0.2     # 1周期の秒数
      duty: 0.5         # 周期内で max_opacity になる割合
      min_opacity: 0.0  # 0.0なら完全に消える
      max_opacity: 1.0
    timing: {start: 0.0, duration: 3.0}
```

サンプル: [`sample_overlay_static_image_effect.yaml`](./sample_overlay_static_image_effect.yaml), [`sample_overlay_blink.yaml`](./sample_overlay_blink.yaml)。

## BGM と音声チューニング

```yaml
bgm:
  path: assets/bgm/intro.wav
  volume: 0.2
  fade_in_duration: 2.0
  fade_out_duration: 1.5
  start_time: 1.0

lines:
  - text: "台詞ごとに速度を調整"
    speed: 0.9            # 0.5〜2.0 の範囲
    pitch: -0.1           # -1.0〜1.0
    voice_style: whisper  # キャラクターに登録済みのスタイル名
```

- シーンレベル `bgm` でループBGMを設定。フェードや開始位置を細かく制御できます。サンプル: [`sample.yaml`](./sample.yaml)。
- BGMの start/stop 切り替え例は [`sample_bgm.yaml`](./sample_bgm.yaml) を参照してください。
- 行ごとの `speed` / `pitch` / `voice_style` は VOICEVOX の音声チューニングに利用します。
- `defaults.characters.<name>.speaker_id` や行の `speaker_id` で話者を指定してください。

## Topic（チャプター）

`topic` を挿入するとタイムライン上でチャプター情報を生成できます。

```yaml
items:
  - topic: "導入"
  - say:
      text: "導入パートです。"
      speaker_name: "copetan"
  - topic: "本題"
```

- YouTube などのチャプター用メタデータに利用されます。
- まとまった例は [`sample_topics.yaml`](./sample_topics.yaml) を参照してください。

## 音声・映像フィルタ

音声には `audio_filter`、映像には `video_filter` を行単位で指定します。
オーバーレイの色味変更は `fg_overlays[*].filter` で行えます。

```yaml
items:
  - say:
      text: "電話越しの音"
      audio_filter: phone
  - say:
      text: "セピア調の映像"
      video_filter: sepia
  - say:
      text: "オーバーレイのグレースケール"
      fg_overlays:
        - id: speedlines
          src: assets/overlay/speedlines.png
          mode: overlay
          filter: grayscale
```

- audio_filter presets: `phone` / `echo` / `radio` / `muffled`
- video_filter presets: `invert` / `sepia` / `grayscale` / `high_contrast` / `night`
- まとめた例は [`sample_filters.yaml`](./sample_filters.yaml) を参照してください。

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

## 読みと字幕テキストの制御

- ルート `subtitle.reading_display: paren` を設定すると、インライン読み `[表示|読み]` や `表示{読み}` を字幕PNGにも括弧付きで出力します。
- 行全体の読み仮名を差し替える場合は `reading: "ふりがな"` を指定。サンプル: [`sample.yaml`](./sample.yaml)。
- 字幕と音声のテキストを分けたいときは `subtitle_text` を活用し、表示のみ別テキストにできます。

## 便利な小ネタ

- `insert` と `fg_overlays` は併用可能。優先順位は行→シーン→字幕の順。
- `wait` 行はタイムラインにも反映され、動画全体の尺調整に便利。
- `config.yaml` 側の `system.timeline` / `system.subtitle_file` でタイムライン・字幕の自動出力を制御。SRT/ASSファイルの一括タイミング補正は `system.subtitle_file.offset_seconds` を使います。
- `system.cache_scene_base_video: true` で、字幕焼き込み前のシーン動画を内部キャッシュします。字幕だけを直した再生成では `[SceneCache] layer=base HIT` が出れば、発話クリップ生成とシーンconcatをスキップして字幕焼き込みから再開できます。`system.generate_no_sub_video` は `*_no_sub.mp4` を成果物として出す別機能です。
- サンプル台本: [`sample.yaml`](./sample.yaml), [`sample_effects.yaml`](./sample_effects.yaml), [`sample_screen_shake.yaml`](./sample_screen_shake.yaml), [`sample_char_bob.yaml`](./sample_char_bob.yaml), [`sample_char_shake.yaml`](./sample_char_shake.yaml), [`sample_char_sway.yaml`](./sample_char_sway.yaml), [`sample_text_bounce.yaml`](./sample_text_bounce.yaml), [`sample_vn_minimal.yaml`](./sample_vn_minimal.yaml), [`sample_transitions.yaml`](./sample_transitions.yaml)。
- 追加の用途別サンプルまとめ: [`docs/script_samples.md`](../docs/script_samples.md)。

> 新しい演出・アニメーションを追加した際は、サンプル台本を用意し、このチートシートに対応情報を追記してください。
