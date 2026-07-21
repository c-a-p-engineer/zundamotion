# Zundamotion 機能一覧

判定は実装コード、テスト、同梱サンプルの順に突合した結果です。状態は「実装済み」
「一部実装」「未実装」「採用見送り」「要再検証」だけを使用します。

## 映像・配置・合成

| 機能 | 状態 | 対応範囲・制約 | 根拠 |
| --- | --- | --- | --- |
| 背景パン・ズーム / Ken Burns | 実装済み | `bg:pan_zoom` / `bg:ken_burns` の単一区間補間 | `clip/effects/resolve.py`, `test_background_pan_zoom_effect.py` |
| キャラクター位置移動 | 実装済み | `move.from` から行の最終位置へ x/y を補間 | `clip/movement.py`, `test_character_movement.py` |
| キャラクタースケール補間 | 実装済み | `move.from.scale` から最終 scale へ補間 | `clip/movement.py`, `test_character_movement.py` |
| キャラクター回転 | 一部実装 | overlay effect の `rotate` は対応。`move` と統合した回転補間は未対応 | `overlay_effects.py`, `test_overlay_effects_registry.py` |
| 複数キーフレーム | 未実装 | pan/zoom と move は開始・終了の単一区間のみ | `clip/movement.py`, `clip/effects/resolve.py` |
| クロマキー | 実装済み | `fg_overlays.mode: chroma`、key color/similarity/blend | `overlays.py`, `validate_overlays.py` |
| blend mode | 実装済み | `screen` / `add` / `multiply` / `lighten` | `overlays.py`, `validate_overlays.py`, `sample_registry_smoke.yaml` |
| image layers | 実装済み | show/hide、複数 layer、fade | `scene_preparation.py`, `test_script_loader.py` |
| 前景 overlay / PiP | 実装済み | 静止画・動画、位置、scale、timing、loop | `overlays.py`, `sample_registry_smoke.yaml` |
| overlay blink | 実装済み | interval/duty/min/max opacity、alpha のみを変調 | `overlays.py`, `test_overlay_alpha_preservation.py` |
| text badge | 実装済み | top-level/scene/line、timing、show/hide | `badge_overlay_cache.py`, `test_badge_overlay_cache.py` |
| キャラクター色替え | 実装済み | hue/saturation/brightness、対象領域・色域 | `image_color_filter_cache.py`, `test_scene_cache_fingerprint.py` |
| キャラクター flip | 実装済み | `flip_x` / `flip_y`、顔差分にも継承 | `clip/characters.py`, `test_scene_renderer_subtitle_flow.py` |
| LUT | 一部実装 | overlay plugin の `lut3d` は対応。全 timeline の管理 UI/preview はない | `plugins/builtin/overlay_basic`, `test_overlay_effects_registry.py` |
| ノイズ effect | 未実装 | blur/unsharp/vignette はあるが noise preset はない | `plugins/builtin/overlay_basic` |
| 動画素材の速度変更 | 実装済み | `insert.speed` 0.25〜4.0、映像 PTS と音声 atempo を同期 | `clip_renderer.py`, `test_clip_renderer_insert_speed.py` |

## 音声・BGM

| 機能 | 状態 | 対応範囲・制約 | 根拠 |
| --- | --- | --- | --- |
| BGM loop | 実装済み | `bgm_layers[].loop`、source position wrap | `bgm_phase.py`, `test_bgm_phase_loop.py` |
| BGM start/stop/resume | 実装済み | timeline event で制御 | `bgm_phase.py`, `sample_bgm.yaml` |
| BGM fade | 実装済み | event ごとの fade in/out | `bgm_phase.py`, `ffmpeg_audio.py` |
| scene 間 audio crossfade | 実装済み | `scene.transition` の `acrossfade` | `ffmpeg_ops.py`, `test_audio_pcm_concat_integration.py` |
| L カット | 実装済み | 前行の音声 tail を次行映像へ overlay | `audio_phase.py`, `test_audio_phase_voice_layers.py` |
| J カット | 要再検証 | `j_cut.duration` の映像 pre-padding は実装。音声先行の render characterization が未整備 | `scene_standard_renderer.py` |
| 音声 filter preset | 実装済み | `phone` / `echo` / `radio` / `muffled` | `filter_presets.py`, `sample_filters.yaml` |
| 任意 EQ | 未実装 | 任意 FFmpeg audio filter 文字列は受け付けない | `validate_script.py` |
| compressor | 一部実装 | `radio` preset 内の固定 `acompressor` のみ | `filter_presets.py` |
| reverb / echo | 一部実装 | `echo` preset の固定 `aecho` のみ。任意 reverb 設定はない | `filter_presets.py` |
| loudnorm | 実装済み | `audio.master_loudnorm` / `mastering.loudnorm` | `bgm_phase.py`, `test_bgm_phase_loop.py` |

## 台本・出力・保守

| 機能 | 状態 | 対応範囲・制約 | 根拠 |
| --- | --- | --- | --- |
| scene cache | 実装済み | base と subtitle layer を分離し素材署名を含む | `video_phase/scene_cache.py`, `test_scene_renderer_subtitle_flow.py` |
| FinalizePhase cache | 実装済み | transition と final concat、`system.finalize_cache` で無効化可 | `finalize_phase.py`, `test_finalize_phase.py` |
| SRT/ASS 出力 | 実装済み | `srt` / `ass` / `both` | `timeline.py`, `test_subtitle_text.py` |
| Markdown 入力 | 実装済み | frontmatter と panel image 化 | `components/markdown`, `test_markdown_pipeline.py` |
| include / vars | 実装済み | section/scene include、文字列変数、循環検出 | `components/script/resolver.py`, `test_script_resolver.py` |
| plugin | 実装済み | built-in と drop-in、allow/deny | `plugins`, `test_plugins_integration.py` |
| Shorts 書き出し | 実装済み | `shorts_1080x1920` preset | `export_presets.py`, `test_media_params_resolution.py` |
| 1440p 書き出し | 実装済み | `youtube_1440p` preset | `export_presets.py`, `test_media_params_resolution.py` |
| template 管理 | 一部実装 | package default config と include 再利用は可能。template catalog/version 管理はない | `templates/config.yaml`, `components/script/resolver.py` |
| proxy 生成 | 未実装 | proxy asset pipeline はない | 実装・テストなし |
| 複数 sequence | 未実装 | 1 台本 1 timeline | `pipeline.py` |

## 基盤機能

| 機能 | 状態 | 対応範囲・制約 | 根拠 |
| --- | --- | --- | --- |
| YAML load/validation | 実装済み | default 適用、素材・設定検証 | `components/config`, `components/script/loader.py` |
| VOICEVOX 音声生成/cache | 実装済み | speaker/style/speed/pitch、retry/cache | `components/audio`, `test_audio_generator.py` |
| PNG/ASS 字幕 burn | 実装済み | `png` / `auto` / `ass` と安全な fallback | `components/subtitles`, `test_subtitle_png.py`, `test_subtitle_ass.py` |
| transition | 実装済み | fade/dissolve/wipe/zoom と DTS 安全な concat | `ffmpeg_ops.py`, `test_ffmpeg_ops_transition.py` |
| no-voice | 実装済み | 推定または明示 duration の無音 track | `audio_phase.py`, smoke tests |
| export preset | 実装済み | 解像度/fps/audio を全 phase へ共有 | `export_presets.py`, `test_media_params_resolution.py` |

## 採用見送り

| 機能 | 状態 | 理由 |
| --- | --- | --- |
| 歌唱機能 (`song`) | 採用見送り | 字幕、長尺 YAML、同期、保守責務との不整合。詳細は `guides/song_mode_rejected.md` |

## 関連資料

- YAML: [`../scripts/script_cheatsheet.md`](../scripts/script_cheatsheet.md)
- サンプル: [`script_samples.md`](./script_samples.md)
- filter mapping: [`design/ffmpeg_filter_mapping.md`](./design/ffmpeg_filter_mapping.md)
