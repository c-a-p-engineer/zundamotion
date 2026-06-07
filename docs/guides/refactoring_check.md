# リファクタリング確認手順

このガイドは、Python ソースのリファクタリング後に挙動変更や責務分割の不足がないか確認する手順。
チェック用台本は `scripts/refactor_validation_check.yaml` を使う。

## 1. 静的確認

```bash
git diff --check
python3 -m compileall -q zundamotion tests
find zundamotion/components/config -type f -name 'validate*.py' -print0 | xargs -0 wc -l
```

確認事項:

- `validate*.py` が 500 行以下である
- 各ファイルの責務が名前から判断できる
- `validate_config` が全体の呼び出し順序制御だけを担当している
- YAML、CLI、FFmpeg、cache key の仕様変更が含まれていない

## 2. テスト

```bash
python3 -m pytest -q -s \
  tests/test_config_validate.py \
  tests/test_script_loader.py \
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

## 5. モデル 5.4 向け確認依頼

以下を確認対象として渡す。

```text
vendor/zundamotion の設定バリデーション分割をレビューしてください。

確認事項:
- public API、YAML、CLI、エラーメッセージの意図しない変更がないか
- validate.py、validate_script.py、validate_*.py の責務分割が妥当か
- 1ファイル500行以下、1関数80行以下を満たすか
- tests/test_config_validate.py の不足ケースがないか
- scripts/refactor_validation_check.yaml が主要な検証経路を通るか
- git diff とテスト結果から、回帰リスクを重要度順に報告すること

実行手順は docs/guides/refactoring_check.md に従ってください。
```
