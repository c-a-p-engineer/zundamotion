# Markdown入力パイプライン実行計画

## 目的

- Frontmatter付きMarkdownから動画生成までを一貫処理する。
- 既存YAML入力フローを壊さず、後方互換を維持する。
- 再現性（同一入力=同一中間成果物）、自動化適性（CI/CLI連携）、デバッグ容易性（中間台本・画像の保存）を優先する。

## スコープ

- 対象:
  - Markdownの境界パース（Frontmatter + Body）
  - Markdown Bodyから画像素材の生成
  - 既存スキーマ互換の中間YAML台本生成
  - 既存動画パイプラインへの接続
- 非対象（初期段階）:
  - Markdown独自記法の過度な拡張
  - 外部API依存の画像生成（初期はローカル処理優先）

## パイプライン（4段階）

1. Markdownファイルを解析
   - 入力: `script.md`
   - 処理:
     - FrontmatterをYAMLとして読み込み
     - Bodyをセクション/段落単位に正規化
     - 必須キー（例: `meta.title`）を境界で検証
   - 出力:
     - 正規化済みドキュメントJSON（デバッグ用）

2. Markdownから画像を作成
   - 入力: 正規化済みBody
   - 処理:
     - セクションごとに背景/差し込み画像を生成または組み立て
     - 出力ファイル名を決定論的に生成（再実行で同一パス）
   - 出力:
     - `output/intermediate/images/*.png`

3. 中間台本を作成
   - 入力: Frontmatter + 画像生成結果
   - 処理:
     - 既存YAMLスキーマ互換の `scenes/lines` に変換
     - 生成画像のパスをsceneに埋め込み
     - `defaults/subtitle/video` 等をFrontmatterから反映
   - 出力:
     - `output/intermediate/script.resolved.yaml`

4. 中間台本から動画を作成
   - 入力: `script.resolved.yaml`
   - 処理:
     - 既存 `load_script_and_config` → `validate_config` → `pipeline` を再利用
   - 出力:
     - 最終動画（既存仕様）

## アーキテクチャ方針

- 単一責務で段階分離:
  - `components/markdown/parser.py`
  - `components/markdown/image_builder.py`
  - `components/markdown/script_builder.py`
- 既存ルートの再利用:
  - 最終的に既存YAML入力と同じ検証・実行経路へ合流
- 再現性確保:
  - 中間成果物を必ず保存できるオプション（既定ON）
  - 生成ファイル名はハッシュ/IDベースで決定論化
- エラーモデル:
  - パース/検証不備は `INPUT_ERROR` として即時失敗

## CLI計画

- 入力拡張:
  - `zundamotion script.md` を許可
- 追加オプション案:
  - `--dump-intermediate-dir output/intermediate`
  - `--markdown-images-only`（段階2まで確認）
  - `--from-intermediate script.resolved.yaml`（段階4のみ再実行）

## テスト計画（最小）

- 単体テスト:
  - Frontmatter正常/異常、Body分割、必須キー検証
  - 画像生成ファイル名の決定性
  - 中間台本のスキーマ互換性
- 結合テスト:
  - Markdown入力から `script.resolved.yaml` 生成まで
  - 既存YAML入力が回帰しないこと
- デバッグテスト:
  - `--dump-intermediate-dir` で成果物が保存されること

## ロールアウト手順

1. フェーズ1: Parser実装 + テスト
2. フェーズ2: Script Builder実装 + 既存Validator接続
3. フェーズ3: Image Builder実装（ローカル生成のみ）
4. フェーズ4: CLI統合 + E2Eスモーク
5. フェーズ5: README/サンプル更新

## 既知の制約

- 初期リリースはローカル素材生成のみ（外部I/O依存なし）。
- Markdown独自記法は最小セットから開始し、互換性を優先して段階的に拡張する。
