# リファクタリング確認手順

このガイドは、Python ソースのリファクタリング後に挙動変更や責務分割の不足がないか確認する手順。
チェック用台本は `scripts/refactor_validation_check.yaml` を使う。

## 1. 静的確認

```bash
git diff --check
python3 -m compileall -q zundamotion tests
find zundamotion/components/config -type f -name 'validate*.py' -print0 | xargs -0 wc -l
wc -l zundamotion/components/pipeline_phases/video_phase/scene_*.py
```

確認事項:

- `validate*.py` が 500 行以下である
- 各ファイルの責務が名前から判断できる
- `validate_config` が全体の呼び出し順序制御だけを担当している
- `scene_renderer.py` が公開入口と実行順序制御に限定されている
- scene描画の変更対象が preparation / fast path / cache / standard renderer の
  いずれかへ局所化されている
- YAML、CLI、FFmpeg、cache key の仕様変更が含まれていない

## 2. テスト

```bash
python3 -m pytest -q -s \
  tests/test_config_validate.py \
  tests/test_script_loader.py \
  tests/test_cli_entrypoints.py

python3 -m pytest -q -s \
  tests/test_scene_renderer_module_split.py \
  tests/test_scene_renderer_subtitle_flow.py \
  tests/test_character_movement.py \
  tests/test_cli_entrypoints.py

python3 -m pytest -q -s
```

対象テストは全件成功を必須とする。
全テストで環境依存の失敗が出た場合は、今回の差分との関連を切り分けて記録する。

## 3. 台本ロード確認

```bash
python3 - <<'PY'
from zundamotion.components.script.loader import load_script_and_config

config = load_script_and_config(
    "scripts/refactor_validation_check.yaml",
    "zundamotion/templates/config.yaml",
)
print([scene["id"] for scene in config["script"]["scenes"]])
PY
```

期待値:

```text
['validation_features', 'validation_background']
```

## 4. 動画生成確認

FFmpeg とフォントが入った Dev Container 内で実行する。

```bash
python3 -m zundamotion.main scripts/refactor_validation_check.yaml \
  -o output/refactor_validation_check.mp4 \
  --no-voice \
  --no-cache \
  --hw-encoder cpu \
  --quality speed \
  --debug-log

ffprobe -v error \
  -show_entries format=duration \
  -of default=noprint_wrappers=1 \
  output/refactor_validation_check.mp4
```

目視確認:

- 1 シーン目で右上に `CHECK` バッジが表示される
- warning overlay と右下の画像レイヤーが表示される
- 画像レイヤーがフェードアウトする
- dissolve 後に sunset 背景へ切り替わる
- 映像停止、黒画面、字幕欠落、意図しない例外がない

## 5. SceneRenderer 分割後の確認

次を追加確認する。

- `from zundamotion.components.pipeline_phases.video_phase.scene_renderer import SceneRenderer`
  が従来どおり動作する
- subtitle cache miss後のbase cache再利用が維持される
- `characters_persist` と `background_persist` の状態反映順が変わっていない
- simple scene fast pathの適用条件とfallback理由が変わっていない
- `scene_standard_renderer.py` の次回分割では、一度にFFmpeg処理方式まで変更しない

## 6. AIレビュー向け確認依頼

以下を確認対象として渡す。

```text
vendor/zundamotion の SceneRenderer 責務分割をレビューしてください。

確認事項:
- SceneRenderer のpublic import、YAML、CLI、cache keyに意図しない変更がないか
- preparation、fast path、cache、standard rendererの責務境界が妥当か
- scene_renderer.py が薄い公開入口として保たれているか
- scene_standard_renderer.py の次回分割境界に不足がないか
- tests/test_scene_renderer_subtitle_flow.py の保護範囲に不足がないか
- git diff とテスト結果から、回帰リスクを重要度順に報告すること

実行手順は docs/guides/refactoring_check.md に従ってください。
```
