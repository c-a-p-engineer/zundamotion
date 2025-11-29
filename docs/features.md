# Zundamotion 機能一覧（実装状況付き）

## 実装済み機能（コード確認ベース）
| カテゴリ | 機能 | 概要 | 主な実装/ソース |
| --- | --- | --- | --- |
| 台本/検証 | YAMLロード・検証・デフォルト適用 | `defaults/characters_persist`や字幕/解像度をバリデーションし、欠損を補完 | zundamotion/components/config/validate.py, components/script/loader.py |
| 音声合成 | VOICEVOX音声生成＋キャッシュ | speaker設定に従い音声を生成しキャッシュ共有 | components/audio/generator.py, components/audio/voicevox_client.py |
| クリップ生成 | 背景画像/動画の正規化とシーン連結 | contain/cover/fit_width等でリサイズし、行ごとのクリップをconcat | utils/ffmpeg_ops.build_background_fit_steps, components/video/renderer.py, components/pipeline_phases/video_phase/scene_renderer.py |
| キャラ配置 | アンカー＋座標＋スケール配置、揺れ系エフェクト | shake/bob/swayをoverlay式で表現、enter/leave余白計算あり | components/video/clip/effects/resolve.py |
| 背景/画面効果 | 背景揺れ・画面揺れ | pad+crop方式でシェイク | components/video/clip/effects/resolve.py |
| オーバーレイ | 画像/動画挿入・前景オーバーレイ・PiP | insert/fg_overlaysでロゴ・挿入映像を重畳 | components/video/renderer.py, components/pipeline_phases/video_phase/scene_renderer.py |
| 字幕 | PNG字幕焼き込み＋SRT/ASS出力、バウンス効果 | SubtitlePNGRendererでスタイル適用、text:bounce_text効果あり | components/subtitles, plugins/builtin/subtitle_text/plugin.py, main.py CLI `--subtitle-file` |
| トランジション | xfade＋音声acrossfade（scene.transition） | fade/dissolve/wipe/zoom等のxfade typeを指定可能 | utils/ffmpeg_ops.apply_transition, components/pipeline_phases/finalize_phase.py |
| BGM/SE | BGMミックス（音量・フェード・ディレイ）＋複数SE合成 | amixでBGMと映像音声を混合、fade in/out・delay対応 | utils/ffmpeg_audio.add_bgm_to_video, mix_audio_tracks, components/pipeline_phases/bgm_phase.py |
| エフェクト拡張 | プラグイン式オーバーレイ効果 | blur/vignette/eq/hue/curves/unsharp/lut3d/rotate等を登録・適用 | plugins/builtin/overlay_basic/plugin.py, components/video/overlay_effects.py |
| 字幕エフェクト拡張 | バウンス字幕プラグイン | text:bounce_textで上下バウンド | plugins/builtin/subtitle_text/plugin.py |
| 進捗/出力補助 | タイムライン出力・ログ（JSON/KV/ファイル） | timeline.md/csv生成、ログ形式切替 | timeline.py, main.py |
| 性能 | HWエンコーダ自動検出＋スレッド調整 | GPU/CPUを判定し、フィルタ/concatスレッドを自動制御 | utils/ffmpeg_hw.py, components/pipeline_phases/video_phase/scene_renderer.py（auto-tune） |

## 機能優先度表（計画 + 実装状況）
| カテゴリ | 機能名 | 優先度 | 実装状況 | 用途説明 |
| --- | --- | --- | --- | --- |
| カット・トリム | カット / トリム / 分割 | MVP | 実装済（台本→行クリップ生成/concat） | シナリオに沿って素材を配置する基本操作 |
| 画面構図 | クロップ / アスペクト比調整 | MVP | 実装済（contain/cover/fit_width/fit_height） | 必要な範囲だけ切り出しレイアウトを整える |
| 画面構図 | パン & ズーム（Ken Burns） | MVP | 未実装 | 静止画や定点動画に動きを付ける |
| 画面構図 | 位置・スケール・回転アニメーション | MVP | 一部実装（shake/bob/sway＋rotate、任意キーフレーム未対応） | スライドイン/アウトや軽いズーム演出 |
| トランジション | フェードイン / フェードアウト | MVP | 実装済（xfade=fade） | シンプルな場面転換や開始/終了の自然な繋ぎ |
| トランジション | クロスディゾルブ / スライド / ズーム | MVP | 実装済（xfade type指定でdissolve/wipeleft/zoom等） | 基本的なシーン間遷移で雰囲気を演出 |
| テキスト | テロップ / タイトル（位置・スタイル・簡易アニメ） | MVP | 実装済（PNG字幕＋bounce effect、SRT/ASS出力） | 字幕・見出しを表示して情報を補足 |
| オーバーレイ | PNG/ロゴ透過オーバーレイ | MVP | 実装済（fg_overlays/insertで重畳） | ロゴや枠などの静的重ね合わせ |
| オーディオ | 音量調整 / ミュート / フェード | MVP | 実装済（BGM volume・fade、amix） | ナレーションやBGMの音量バランスを取る |
| オーディオ | BGM / 効果音トラック（ループ） | MVP | 一部実装（BGM/SEミックス・delay、明示ループ未対応） | シーンを跨いでBGMを敷き詰める |
| コンポジット | ピクチャーインピクチャー（ワイプ） | 優先高 | 実装済（動画insertを正規化して重畳） | 画面隅に別映像を重ねる実況/解説用途 |
| 速度 | 速度変更（スロー / 早送り） | 優先高 | 未実装 | テンポ調整や尺合わせ |
| トランジション | プリセット系（グリッチ / フラッシュ） | 優先高 | 一部実装（xfade内蔵のwipe系のみ、グリッチ未対応） | 目立つ場面転換のプリセット化 |
| 色調整 | 明るさ・コントラスト・彩度・色相 | 優先高 | 実装済（eq/hue/curvesフィルタ） | 基本的な見た目補正 |
| 色調整 | ぼかし / シャープ / ビネット / ノイズ | 優先高 | 一部実装（gblur/unsharp/vignette、ノイズ未対応） | 雰囲気付けや視線誘導 |
| コンポジット | ブレンドモード（加算/乗算/スクリーン） | 優先高 | 未実装 | レイヤー合成で雰囲気や光演出を追加 |
| オーディオ | クロスフェード / Jカット / Lカット | 優先高 | 一部実装（シーン間acrossfade、J/Lカット未対応） | 映像より先/後で音を繋げる |
| オーディオ | EQ / コンプレッサー / リバーブ | 優先高 | 未実装（オーディオEQ/comp/reverbなし） | ざっくりと音質とラウドネスを整える |
| コンポジット | クロマキー（グリーンバック） | 将来候補 | 未実装 | 合成撮影用の背景置換 |
| 画面構図 | 手ブレ補正（スタビライズ） | 将来候補 | 未実装 | 手持ち映像の揺れ抑制 |
| 色調整 | LUT / カラーグレーディング | 将来候補 | 一部実装（lut3dフィルタのみ） | 映画調など高度なトーン調整 |
| オーバーレイ | オーバーレイ動画（フレア/パーティクル） | 将来候補 | 実装済（動画insertで重畳可） | 派手な装飾エフェクト |
| 実務系 | テンプレート / プリセット管理 | 将来候補 | 未実装 | OP/EDやテロップスタイルの再利用 |
| 実務系 | アセット管理 / プロキシ生成 | 将来候補 | 未実装 | 大容量素材を扱うワークフロー最適化 |
| 実務系 | 複数シーケンス管理 | 将来候補 | 未実装 | 章ごとにタイムラインを分けて編集 |
| 実務系 | 書き出しプリセット（解像度/ビットレート） | 将来候補 | 未実装 | 配信プラットフォーム別の最適設定出力 |

## 設計ドキュメントリンク
- YAMLスキーマ草案: `docs/design/yaml_schema_draft.md`
- FFmpegフィルタ対応表: `docs/design/ffmpeg_filter_mapping.md`
- パーサ＆filter_complex骨組み: `docs/design/parser_and_builder.md`
