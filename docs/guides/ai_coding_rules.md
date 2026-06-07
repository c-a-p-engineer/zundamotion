# AI Coding Rules

AI / Codex が `zundamotion` で不要なファイル読み込み、過剰な入出力トークン、誤った責務への実装追加を減らすための実装規約。
常時読む入口は `AGENTS.md` とし、このファイルはコード、CLI、補助ツール、設計寄りの変更を行うときだけ参照する。

## 1. 目的

- 変更種別ごとに最初に読むファイルを固定する
- 実装判断を `AGENTS.md` ではなく docs へ分離する
- 1 回の変更で追う責務を絞る
- PR や作業報告で、読んだファイルと読まなかった理由を短く説明できる状態を保つ

## 2. 変更種別ごとの最初の参照先

### YAML 仕様、サンプル台本、利用者向け挙動

1. `README.md`
2. `scripts/script_cheatsheet.md`
3. `docs/README.md`
4. `docs/features.md`
5. 必要に応じて `docs/script_samples.md` と対象コード

### 実行、セットアップ、CLI 運用

1. `README.md`
2. `docs/guides/setup_and_runtime.md`
3. `docs/README.md`
4. 対象 CLI コード

### 性能、並列度、キャッシュ、FFmpeg 経路

1. `docs/guides/performance_regression_ledger.md`
2. `docs/guides/performance_tuning.md`
3. `docs/design/` の関連資料
4. 対象コード

### 設計、構成、責務分割

1. `docs/guides/project_structure.md`
2. `docs/guides/python_coding_rules.md`
3. `docs/README.md`
4. `docs/design/` の関連資料
5. 対象コード

## 3. AI 低トークン運用

- ファイル冒頭には、責務、入口、関連ファイルを最大 10 行で置く
- 長い仕様説明はコードコメントではなく docs に置く
- 同じ仕様を README、docs、コードコメントへ重複記述しない
- 変更に不要な大きいファイルや無関係ディレクトリを広く読まない
- 読む順序は `AGENTS.md`、`README.md`、`docs/README.md` を起点に固定する
- PR や作業報告では、読んだファイルと読まなかった理由を 1 行ずつ書ける粒度で作業する

## 4. Python 規約

- 詳細は `docs/guides/python_coding_rules.md` を正とする
- 1 ファイルは目安 200〜400 行、上限 500 行
- 1 関数は目安 20〜40 行、上限 80 行
- `Dict[str, Any]` は YAML 境界や外部 I/O 境界では許容するが、内部ロジックへ広げない
- 環境変数の読み取りは局所化し、処理の深部で散発的に読まない
- 副作用のある処理と純粋変換処理を分ける
- データ整形、パス解決、設定解決が膨らんだら別関数へ切り出す
- 1 ファイルへ異なる責務を混在させない

## 5. FFmpeg 規約

- `filter_complex` 生成の責務を局所化する
- フィルタ生成関数には、入力ラベル、出力ラベル、同期への影響を明記する
- `fps`、`setpts`、`asetpts`、`concat`、`overlay`、`enable` を触る場合は A/V sync への影響を書く
- DEBUG ログからコマンドを再現できるようにする
- フィルタ列の組み立てとプロセス実行を同じ関数へ混ぜない

## 6. CLI 規約

- `argparse` が増える場合は、オプショングループ単位で関数分割する
- CLI、環境変数、YAML の優先順位をコードか docs のどちらか一方で明記する
- CLI 追加時は `README.md`、`docs/README.md`、`docs/guides/setup_and_runtime.md` の更新要否を確認する
- ヘルプ表示だけで分からない運用前提は docs 側へ寄せる

## 7. Pipeline 規約

- `GenerationPipeline` の主責務はフェーズ順序制御に限定する
- 品質プリセット展開、環境変数解決、一時ディレクトリ選択は肥大化したら別関数へ逃がす
- フェーズ追加時は `timeline`、`stats`、`cache`、docs への影響を確認する
- フェーズ内の詳細実装を pipeline 本体へ直接積み増ししない

## 8. PR 単位のルール

- 1 PR では責務を 1 つに寄せる
- ドキュメント整理と挙動変更を同時に大きく混ぜない
- 変更理由、読んだファイル、読まなかった理由を短く説明できない変更は分割を検討する
- 生成物更新が不要なら含めない

## 9. 分割基準

以下に当てはまる場合は、別ファイル化や別 PR を検討する。

- 1 ファイルが 500 行を超える
- 1 関数が 80 行を超える
- 1 変更で CLI、pipeline、FFmpeg、docs を同時に大きく触る
- 同じ仕様説明を 3 箇所以上へ書きたくなる
- 変更理由の説明に対象外の前提知識が多く必要になる

## 10. 既存ルールの移設先

- ドキュメント更新義務: `AGENTS.md` と `README.md`
- 性能変更前の必読資料: `docs/guides/performance_regression_ledger.md`
- 設計メモや検証履歴の置き場: `docs/design/`, `docs/guides/`, `docs/issues_pending.md`
- ログ方針や外部 I/O の詳細実装は、既存コードと対象モジュールの関連 docs を正とする

## 11. 非対象

- 既存コードの大規模リファクタ
- Formatter 導入
- `mypy` 導入
- CI 追加
- YAML スキーマ変更
- FFmpeg 処理変更
- CLI 仕様変更
