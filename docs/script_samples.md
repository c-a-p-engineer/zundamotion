# サンプル台本カタログ

Zundamotion に同梱されている YAML 台本サンプルを用途別に整理しました。各ファイルは `scripts/` ディレクトリに配置されています。

## クイックリスト

| ファイル | 主な用途 | ハイライト |
| --- | --- | --- |
| [`sample.yaml`](../scripts/sample.yaml) | デフォルト設定の総合例 | キャラクターごとのデフォルト、字幕色の上書き、前景オーバーレイ、表情切り替え |
| [`sample_image_layers.yaml`](../scripts/sample_image_layers.yaml) | 画像レイヤーの表示/非表示 | 複数画像の show/hide とフェード演出 |
| [`sample_effects.yaml`](../scripts/sample_effects.yaml) | 前景エフェクト最小構成 | `fg_overlays` のエフェクトチェーンとループ制御 |
| [`sample_effects_registry.yaml`](../scripts/sample_effects_registry.yaml) | エフェクトレジストリ検証用 | `order` 付きの複数エフェクト併用とデモ字幕 |
| [`sample_registry_smoke.yaml`](../scripts/sample_registry_smoke.yaml) | レジストリ動作スモーク | オーバーレイと字幕エフェクトの同時検証、描画順序チェック |
| [`sample_user_overlay_plugin.yaml`](../scripts/sample_user_overlay_plugin.yaml) | ユーザープラグイン overlay の動作確認 | `user_simple` プラグインの `shake` / `soft_shake` / `shake_fanfare` プリセット |
| [`sample_screen_shake.yaml`](../scripts/sample_screen_shake.yaml) | 画面揺れの演出 | `screen:shake_screen` の複数プリセットを比較 |
| [`sample_character_enter.yaml`](../scripts/sample_character_enter.yaml) | 立ち絵の登場・退場アニメ | `enter`/`leave` のパターンとタイミング制御 |
| [`sample_vn_minimal.yaml`](../scripts/sample_vn_minimal.yaml) | ビジュアルノベル風モード | `characters_persist: true` とシーンまたぎ演出 |
| [`sample_transitions.yaml`](../scripts/sample_transitions.yaml) | シーン遷移の比較 | `transition.type` のフェード/ワイプ/ディゾルブ |
| [`sample_include_vars.yaml`](../scripts/sample_include_vars.yaml) | 台本分割と変数置換 | `include` による再利用と `${VAR}` 差し込み |
| [`sample_markdown.md`](../scripts/sample_markdown.md) | Markdown入力フロー | Frontmatter + 本文（地の文=画像化、話者:セリフ=発話）から中間台本を自動生成。`subtitle.max_chars_per_line: auto`、キャラクター別 `subtitle` 色分け、`markdown.layer/panel/text` によるパネル調整を確認可能 |
| [`sample_subtitle_styles.yaml`](../scripts/sample_subtitle_styles.yaml) | 字幕ボックスのスタイル検証 | 軽量な背景色変更から角丸・枠線・背景画像までを 1 本で確認 |
| [`sample_char_bob.yaml`](../scripts/sample_char_bob.yaml) | `char:bob_char` の挙動 | 振幅・周波数・位相・他エフェクトとの併用サンプル |
| [`sample_char_shake.yaml`](../scripts/sample_char_shake.yaml) | `char:shake_char` の挙動 | デフォルト値とカスタム値の比較 |
| [`sample_char_sway.yaml`](../scripts/sample_char_sway.yaml) | `char:sway_char` の挙動 | オフセット調整と `char:bob_char` 併用 |
| [`sample_bg_shake.yaml`](../scripts/sample_bg_shake.yaml) | 背景のみの揺れ | `bg:shake_bg` の `offset`/`padding` チューニング |
| [`sample_text_bounce.yaml`](../scripts/sample_text_bounce.yaml) | 字幕バウンド演出 | `text:bounce_text` の振幅差分 |
| [`sample_vertical.yaml`](../scripts/sample_vertical.yaml) | 縦長キャンバスの背景フィット | `background_fit` と `fill_color` の組み合わせ |
| [`copetan_all_expressions.yaml`](../scripts/copetan_all_expressions.yaml) | Copetan の表情一覧 | `characters_persist` + 表情差分と口パク設定 |
| [`engy_all_expressions.yaml`](../scripts/engy_all_expressions.yaml) | Engy の表情テンプレート | キャラクター固有のデフォルト話速・ピッチを含む |

## チートシートとの対応

| チートシート項目 | 関連サンプル |
| --- | --- |
| [基本構造](../scripts/script_cheatsheet.md#基本構造) / [行とシーン](../scripts/script_cheatsheet.md#行とシーン) | [`sample.yaml`](../scripts/sample.yaml), [`sample_vn_minimal.yaml`](../scripts/sample_vn_minimal.yaml) |
| [動画キャンバスと背景設定](../scripts/script_cheatsheet.md#動画キャンバスと背景設定) | [`sample_vertical.yaml`](../scripts/sample_vertical.yaml) |
| [字幕設定](../scripts/script_cheatsheet.md#字幕設定) | [`sample.yaml`](../scripts/sample.yaml), [`sample_subtitle_styles.yaml`](../scripts/sample_subtitle_styles.yaml) |
| [キャラクター表示](../scripts/script_cheatsheet.md#キャラクター表示) | [`sample_character_enter.yaml`](../scripts/sample_character_enter.yaml), [`copetan_all_expressions.yaml`](../scripts/copetan_all_expressions.yaml), [`engy_all_expressions.yaml`](../scripts/engy_all_expressions.yaml) |
| [立ち絵アニメーション](../scripts/script_cheatsheet.md#立ち絵アニメーション) | [`sample_char_bob.yaml`](../scripts/sample_char_bob.yaml), [`sample_char_shake.yaml`](../scripts/sample_char_shake.yaml), [`sample_char_sway.yaml`](../scripts/sample_char_sway.yaml) |
| [字幕エフェクト (`subtitle.effects`)](../scripts/script_cheatsheet.md#字幕エフェクト-subtitleeffects) | [`sample_text_bounce.yaml`](../scripts/sample_text_bounce.yaml), [`sample_registry_smoke.yaml`](../scripts/sample_registry_smoke.yaml) |
| [台本の再利用 (`include` / `vars`)](../scripts/script_cheatsheet.md#台本の再利用-include--vars) | [`sample_include_vars.yaml`](../scripts/sample_include_vars.yaml) |
| [画面全体エフェクト (`screen_effects`)](../scripts/script_cheatsheet.md#画面全体エフェクト-screen_effects) | [`sample_screen_shake.yaml`](../scripts/sample_screen_shake.yaml) |
| [背景エフェクト (`background_effects`)](../scripts/script_cheatsheet.md#背景エフェクト-background_effects) | [`sample_bg_shake.yaml`](../scripts/sample_bg_shake.yaml) |
| [画像レイヤー (`image_layers`)](../scripts/script_cheatsheet.md#画像レイヤー-image_layers) | [`sample_image_layers.yaml`](../scripts/sample_image_layers.yaml), [`sample.yaml`](../scripts/sample.yaml) |
| [前景オーバーレイ (`fg_overlays`)](../scripts/script_cheatsheet.md#前景オーバーレイ-fg_overlays) | [`sample.yaml`](../scripts/sample.yaml), [`sample_effects.yaml`](../scripts/sample_effects.yaml), [`sample_registry_smoke.yaml`](../scripts/sample_registry_smoke.yaml), [`sample_user_overlay_plugin.yaml`](../scripts/sample_user_overlay_plugin.yaml) |
| [BGM と音声チューニング](../scripts/script_cheatsheet.md#bgm-と音声チューニング) | [`sample.yaml`](../scripts/sample.yaml) |
| [効果音 (`sound_effects`)](../scripts/script_cheatsheet.md#効果音-sound_effects) | [`sample.yaml`](../scripts/sample.yaml) |
| [顔アニメ用差分素材](../scripts/script_cheatsheet.md#顔アニメ用差分素材) | [`sample.yaml`](../scripts/sample.yaml), [`copetan_all_expressions.yaml`](../scripts/copetan_all_expressions.yaml) |
| [読みと字幕テキストの制御](../scripts/script_cheatsheet.md#読みと字幕テキストの制御) | [`sample.yaml`](../scripts/sample.yaml) |
| [シーン遷移 (`transition`)](../scripts/script_cheatsheet.md#シーン遷移-transition) | [`sample_transitions.yaml`](../scripts/sample_transitions.yaml), [`sample_vn_minimal.yaml`](../scripts/sample_vn_minimal.yaml) |
| [便利な小ネタ](../scripts/script_cheatsheet.md#便利な小ネタ) | [`sample.yaml`](../scripts/sample.yaml), [`sample_vn_minimal.yaml`](../scripts/sample_vn_minimal.yaml) |

> **更新ガイドライン**: 新しい効果やテンプレートを追加した場合は、この表と [`scripts/script_cheatsheet.md`](../scripts/script_cheatsheet.md) の両方にリンクを追記して、利用者が迷わないようにしてください。
