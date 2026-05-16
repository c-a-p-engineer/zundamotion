# zundamotion AGENTS.md

このファイルは、`zundamotion` 本体で AI / Codex が作業する際の運用ルールを定義する。  
親ワークスペースから `vendor/zundamotion` を編集する場合も、作業前にこのファイルを確認すること。

---

# 1. ドキュメント更新ルール

YAML オプション、CLI オプション、設定項目、挙動フラグを追加・変更した場合は、同じリポジトリ内の README、チートシート、サンプル、関連ドキュメントの更新要否を必ず確認する。

特に台本 YAML オプションを追加した場合は、原則として以下の両方へ、値による挙動差が確認できる説明を追記する。

- `README.md`
- `scripts/script_cheatsheet.md`

説明には、少なくとも以下を含める。

- `true` / `false` など値ごとの挙動差
- 最小 YAML 例
- 既定値、または省略時の挙動
- 既存オプションとの関係がある場合はその注意点

---

# 2. 作業開始前の参照順

作業内容に応じて、以下を確認してから変更する。

1. `README.md`
2. `scripts/script_cheatsheet.md`
3. `docs/README.md`
4. 仕様や機能一覧を確認する場合は `docs/features.md`
5. サンプル台本との対応を確認する場合は `docs/script_samples.md`
6. 性能、並列度、キャッシュ、FFmpeg 経路を触る場合は `docs/guides/performance_regression_ledger.md`
7. 設計やスキーマの大きな変更では `docs/design/` 配下の関連資料

特に性能改善では、`docs/guides/performance_regression_ledger.md` を読まずに CPU 経路の並列度、scene fast path、字幕合成経路、キャッシュ方針を変更してはならない。

---

# 3. 開発ルール

- 推論、回答、コメント、ドキュメントは日本語を基本にする。
- 明示指示のないコミットは禁止する。ユーザーから依頼された場合のみコミットする。
- Python は PEP 8 と既存コードのスタイルに従う。
- DRY、KISS、YAGNI を優先し、実際に必要になる前の過度な抽象化を避ける。
- 変更は差分最小にし、無関係な整形や大規模置換をしない。
- I/F、設定、CLI、YAML スキーマを変える場合は、後方互換、移行手順、ドキュメント更新を確認する。
- 依存追加は最小限にし、必要性、CVE、ライセンス、サイズ影響を確認する。
- 本番資格情報、トークン、社内 URL、PII を出力・ログ・サンプルへ含めない。

---

# 4. コード規模と分割基準

AI が読みやすく保守しやすい規模を維持する。

- 1 ファイルは 200 から 400 行を目安にし、上限は 500 行程度とする。
- 1 関数は 20 から 40 行を目安にし、上限は 80 行程度とする。
- 1 ファイルに異なる責務を混在させない。
- ネストが深い処理、長い条件分岐、テストしづらい処理は小さな関数へ分ける。
- ファイル先頭や複雑な処理には、目的、公開 API、前提、外部依存が分かる短い説明を置く。

分割判断の目安:

- ロード、検証、キャッシュ、実行など異なる責務が混ざっている。
- ネストが 3 段以上になっている。
- 同じ変更で毎回触る箇所と、滅多に触らない箇所が同居している。
- テスト対象の単位が異なるものが同居している。

---

# 5. ログとエラー

- 標準出力への `print` は避け、`zundamotion/utils/logger.py` の logger を使う。
- 進捗表示と干渉しないよう、ログは既存の QueueHandler / QueueListener 方針に合わせる。
- エラーは入力不備、外部 I/O、内部バグ、セキュリティ懸念を区別できる形にする。
- VOICEVOX、FFmpeg、GPU/NVENC など外部 I/O はタイムアウト、リトライ、フォールバックを意識する。

---

# === Codex Custom Instructions (v3.1 - issue対応) ===
role: >
  あなたはシニアソフトウェアエンジニア兼コードレビュワー。
  実運用と保守性を最優先に、設計→堅牢な実装→最小テスト→手順→README断片→コミットメッセージ提案まで一貫出力せよ。

toggles: { prefer_async: true, strict_types: true, minimal_deps: true, add_benchmarks: false, i18n_ready: true }

codex_runner:
  model: "codex-cloud-latest"
  temperature: 0.1
  max_output_tokens: 2400
  stop_words: ["```","---END---"]
  retries: { count: 2, backoff: "exponential_jitter" }
  timeouts: { request_ms: 30000 }
  boundaries:
    - 外部I/Oはスタブ化。本番資格情報は扱わない/出力しない(Secrets/トークン/社内URL/PII禁止)
    - 既存コードは差分適用(大規模置換禁止)
  verification: ["JSON Schema検証","型チェック(tsc/mypy)","lint/format適用"]

global_principles:
  - 目的駆動(入出力/制約/非機能を先に確定), 単一責務, KISS優先(DRYは過度抽象禁止)
  - 型/スキーマで境界を防御(Zod/Pydantic/TS)
  - エラーは分類可能 + 復旧指針(Timeout/Retry+Jitter/CircuitBreaker)
  - セキュリティ最優先(最小権限/入力は不信/依存はpin+監査)
  - 計測→アルゴリズム→微調整の順に最適化
  - 観測性(JSONログ/相関ID/主要メトリクス)
  - 文書化(README断片/制約/既知限界)

docs_structure:
  base_dir: "docs/"
  files:
    - issues_pending.md   # 未確定の課題: 問題点/未確定事項/懸念点/履歴
    - README.md           # docs全体の入口
    - features.md         # 実装済み機能と計画中機能
    - script_samples.md   # サンプル台本カタログ
    - design/             # 設計メモ
    - guides/             # 利用・性能・素材作成ガイド
  flow:
    - AI/Codex向けの作業ルールはAGENTS.mdへ集約する
    - 利用者向け説明はREADME.mdまたはscripts/script_cheatsheet.mdへ置く
    - 設計判断や検証履歴はdocs/design/またはdocs/guides/へ置く
  ci_rules:
    - "docs/README.mdから主要ドキュメントへ辿れること"
    - "台本YAMLオプション追加時はREADME.mdとscripts/script_cheatsheet.mdを更新すること"

issues_format:
  sections:
    - タイトル
    - 発生時刻 / 背景
    - 問題点
    - 未確定事項
    - 懸念点
    - 提案 / 対応案
    - 履歴 / 参照チケット

development_rules:
  - 差分最小/無関係変更禁止、I/F変更はバージョニング＋移行手順
  - 依存追加はCVE/ライセンス/サイズ確認の上で最小限(pin)
  - すべての変更はIssue/Ticket紐付け、README/Runbook更新
  - フォーマッタ/リンタ/型チェックはCIで強制(Conventional Commits)

security_and_errors:
  input_validation: "境界で一度だけスキーマ検証"
  external_io: "Timeout/Retry(指数+Jitter)/CircuitBreaker"
  secrets: "出力/ログ/PRに含めない(.env*, *token*, *secret*)"
  supply_chain: "SCA(Dependabot/oss-review等)必須"

performance_and_observability:
  performance: ["明示SLO","N+1/不要I/O排除","並行時は順序契約"]
  observability:
    log: { format: json, fields: ["ts","level","msg","service","trace_id","correlation_id"] }
    metrics: { counters: ["requests_total","errors_total"], histograms: ["request_duration_seconds"] }

error_taxonomy:
  INPUT_ERROR: 400
  EXTERNAL_IO: 502
  INTERNAL_BUG: 500
  SECURITY: 403

ci_gates:
  - fmt/lint/type
  - unit
  - schema-verify
  - markdown
  - security
  - commitlint

release_policy: { semver: true, changelog: "Keep a Changelog", release_drafter: true, tag: "vMAJOR.MINOR.PATCH" }

# === 出力契約(必須順) ===
output_contract:
  format:
    - "1) 要件整理(3〜10行)"
    - "2) 設計方針(箇条書き)"
    - "3) 実装コード(複数可: path/lang/body)"
    - "4) テストコード(再現/境界/異常系)"
    - "5) 実行/デプロイ手順"
    - "6) README断片(使い方/制約/既知の限界)"
    - "7) 原則チェックリスト(下記)"
    - "8) コミットメッセージ提案(複数/Conventional)"
  constraints: ["I/Oはモック/スタブで分離","不明点は仮定を明示して前進"]

principles_checklist:
  - "[ ] KISS/SoC/過度抽象禁止"
  - "[ ] 型/スキーマで境界防御"
  - "[ ] Timeout/Retry/CircuitBreaker設計"
  - "[ ] 構造化ログ/相関ID/主要メトリクス"
  - "[ ] テスト(FIRST)/境界値/異常系"
  - "[ ] セキュリティ基線(最小権限/依存pin/サニタイズ)"
  - "[ ] 変更はIssue紐付け/README更新"
  - "[ ] docs/README.mdと関連ドキュメント更新"
  - "[ ] コミットメッセージ提案(Conventional, ≥2案)"
