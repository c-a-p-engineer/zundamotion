# サンプル台本カタログ

Zundamotion に同梱されている YAML 台本サンプルを用途別に整理しました。各ファイルは `scripts/` ディレクトリに配置されています。

## クイックリスト

| ファイル | 主な用途 | ハイライト |
| --- | --- | --- |
| [`sample.yaml`](../scripts/sample.yaml) | デフォルト設定の総合例 | キャラクターごとのデフォルト、字幕色の上書き、前景オーバーレイ、表情切り替え |
| [`sample_effects.yaml`](../scripts/sample_effects.yaml) | 前景エフェクト最小構成 | `fg_overlays` のエフェクトチェーンとループ制御 |
| [`sample_screen_shake.yaml`](../scripts/sample_screen_shake.yaml) | 画面揺れの演出 | `screen:shake_screen` の複数プリセットを比較 |
| [`sample_character_enter.yaml`](../scripts/sample_character_enter.yaml) | 立ち絵の登場・退場アニメ | `enter`/`leave` のパターンとタイミング制御 |
| [`sample_vn_minimal.yaml`](../scripts/sample_vn_minimal.yaml) | ビジュアルノベル風モード | `characters_persist: true` とシーンまたぎ演出 |
| [`sample_transitions.yaml`](../scripts/sample_transitions.yaml) | シーン遷移の比較 | `transition.type` のフェード/ワイプ/ディゾルブ |
| [`sample_subtitle_styles.yaml`](../scripts/sample_subtitle_styles.yaml) | 字幕ボックスのスタイル検証 | 背景画像・角丸・余白・枠線バリエーション |
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
| [字幕エフェクト (`subtitle.effects`)](../scripts/script_cheatsheet.md#字幕エフェクト-subtitleeffects) | [`sample_text_bounce.yaml`](../scripts/sample_text_bounce.yaml), [`sample_subtitle_styles.yaml`](../scripts/sample_subtitle_styles.yaml) |
| [画面全体エフェクト (`screen_effects`)](../scripts/script_cheatsheet.md#画面全体エフェクト-screen_effects) | [`sample_screen_shake.yaml`](../scripts/sample_screen_shake.yaml) |
| [背景エフェクト (`background_effects`)](../scripts/script_cheatsheet.md#背景エフェクト-background_effects) | [`sample_bg_shake.yaml`](../scripts/sample_bg_shake.yaml) |
| [画像・動画の挿入 (`insert`)](../scripts/script_cheatsheet.md#画像動画の挿入-insert) | [`sample.yaml`](../scripts/sample.yaml) |
| [前景オーバーレイ (`fg_overlays`)](../scripts/script_cheatsheet.md#前景オーバーレイ-fg_overlays) | [`sample.yaml`](../scripts/sample.yaml), [`sample_effects.yaml`](../scripts/sample_effects.yaml) |
| [BGM と音声チューニング](../scripts/script_cheatsheet.md#bgm-と音声チューニング) | [`sample.yaml`](../scripts/sample.yaml) |
| [効果音 (`sound_effects`)](../scripts/script_cheatsheet.md#効果音-sound_effects) | [`sample.yaml`](../scripts/sample.yaml) |
| [顔アニメ用差分素材](../scripts/script_cheatsheet.md#顔アニメ用差分素材) | [`sample.yaml`](../scripts/sample.yaml), [`copetan_all_expressions.yaml`](../scripts/copetan_all_expressions.yaml) |
| [読みと字幕テキストの制御](../scripts/script_cheatsheet.md#読みと字幕テキストの制御) | [`sample.yaml`](../scripts/sample.yaml) |
| [シーン遷移 (`transition`)](../scripts/script_cheatsheet.md#シーン遷移-transition) | [`sample_transitions.yaml`](../scripts/sample_transitions.yaml), [`sample_vn_minimal.yaml`](../scripts/sample_vn_minimal.yaml) |
| [便利な小ネタ](../scripts/script_cheatsheet.md#便利な小ネタ) | [`sample.yaml`](../scripts/sample.yaml), [`sample_vn_minimal.yaml`](../scripts/sample_vn_minimal.yaml) |

> **更新ガイドライン**: 新しい効果やテンプレートを追加した場合は、この表と [`scripts/script_cheatsheet.md`](../scripts/script_cheatsheet.md) の両方にリンクを追記して、利用者が迷わないようにしてください。
