# メモ

## プロンプト

### タスクの実行

1. [AI_README.md](AI_README.md) を読んでからタスクに取り組んでください。
1. TODO.md を作成してあなたがこれからやる作業をチェックリスト化してください。
	1. 作業に変更があれば都度追記や修正を行ってください。
	1. 作業が完了したら作業が終了したとわかるようにチェックを入れてください。
1. [tasks.md](tasks.md) の中から優先度の高いタスク1件取り掛かってください。
1. タスクが完了したら [tasks.md](tasks.md) から該当タスクを削除してください。
1. 必要があれば [AI_README.md](AI_README.md) [README.md](README.md) の更新をしてください。
1. 該当作業の作業内容をコミットするためのコミット文を TODO.md に記載してください。 

### タスクの整理

1. [AI_README.md](AI_README.md) を読んでからタスクに取り組んでください。
1. /workspace/logs ディレクトリに存在する最新ログを確認して実装の確認。
1. ログを解析してボトルネックをタスクとして既存のタスクと比較して優先度を考えて [tasks.md](tasks.md) に記載。
	1. 優先度順に記載
	2. 優先度は品質向上、高速化（微高速化なら優先度は低い）、動画ツールの新機能 or 新機能拡充
1. 必要があれば [AI_README.md](AI_README.md) [README.md](README.md) の更新をしてください。

## コマンド

### キャラクターの背景透過png作成

```
python remove_bg_ai.py --input /workspace/assets/characters/copetan/temp --output /workspace/assets/characters/copetan/temp --model isnet-anime  --force-gpu --recursive
```
