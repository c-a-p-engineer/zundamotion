# 🧭 Zundamotion 公開整備タスクリスト

Zundamotion を「他の人が使えるOSS」として整備するためのタスクリスト。  
フェーズごとに順序立てて進められるように構成。

---

## 🏗️ Phase 1：リポジトリ基盤整備（開発者が迷わず使える状態）

| タイトル | 詳細 | 具体的な手順 |
|-----------|--------|---------------|
| **README整備** | プロジェクト概要・インストール方法・使い方・サンプル動画を記載し、初見でも理解できるようにする。 | 1. `README.md` に概要・特徴・インストール・コマンド例・出力例GIFを記載<br>2. `Shields.io` バッジ追加（スター数、PyPI、ライセンス）<br>3. 「Support & Links」セクションを末尾に追加 |
| **LICENSE設定** | OSSライセンス（MIT / Apache-2.0）を追加して利用・再配布を明確化。 | 1. `LICENSE` ファイルをプロジェクトルートに配置<br>2. GitHubの「Settings → General → License」で明示選択 |
| **CONTRIBUTING.md** | 貢献ガイドライン（PRルール・ブランチ命名・開発手順）を記載。 | 1. `.github/CONTRIBUTING.md` 作成<br>2. `git flow` or `feature/xxx`戦略を簡潔に説明 |
| **Issue/PRテンプレート** | バグ報告や提案の形式を統一し、やり取りを効率化。 | 1. `.github/ISSUE_TEMPLATE/bug.yml` と `feature.yml` を追加<br>2. `.github/PULL_REQUEST_TEMPLATE.md` 作成 |
| **CHANGELOG.md導入** | バージョン履歴を自動化し、更新内容を追跡可能に。 | 1. `commitizen` または `release-please` 導入<br>2. リリース時に自動更新されるようにCI設定 |

---

## ⚙️ Phase 2：CI/CD・配布自動化（更新・リリースが一瞬で終わる）

| タイトル | 詳細 | 具体的な手順 |
|-----------|--------|---------------|
| **テストCI導入** | `pytest`で最低限の単体テスト・YAML検証を自動実行。 | 1. `.github/workflows/test.yml` 作成<br>2. `pytest`, `flake8`, `black`を実行<br>3. 成功時のみマージ許可 |
| **自動リリースCI** | タグやmainブランチ更新でPyPI公開・GitHub Releaseを自動生成。 | 1. `.github/workflows/release.yml` 作成<br>2. `release-please` or `semantic-release` 使用<br>3. `twine upload`でPyPIアップロード |
| **Docker Build CI** | Dockerfileのビルド検証＋`docker buildx`で自動公開。 | 1. `.github/workflows/docker.yml` 追加<br>2. `docker buildx build --push`を実行<br>3. DockerHubリポジトリ連携 |
| **PyPI公開** | `pip install zundamotion`で使えるようにする。 | 1. `setup.py` or `pyproject.toml` 整備<br>2. `python -m build` でビルド<br>3. `twine upload dist/*` |
| **自動CHANGELOG生成** | コミットメッセージからCHANGELOGを生成。 | 1. Conventional Commits形式に統一<br>2. `release-please`導入<br>3. `CHANGELOG.md`自動反映 |

---

## 📢 Phase 3：公開・拡散（ユーザーが見つけて使ってくれる状態）

| タイトル | 詳細 | 具体的な手順 |
|-----------|--------|---------------|
| **YouTubeチャンネル開設** | Zundamotion公式デモ・チュートリアル投稿用のチャンネルを作成。 | 1. GoogleアカウントでYouTubeチャンネル作成<br>2. ロゴ・バナーを設定<br>3. 「Zundamotion紹介」動画を投稿 |
| **ニコニコ動画シリーズ作成** | ニコ動にチュートリアル動画を連載形式で投稿。 | 1. `#ずんだもーしょん` タグを統一使用<br>2. 「YAMLで自動動画生成してみた」などを投稿<br>3. コンテンツツリー登録（VOICEVOX等） |
| **GitHub Pages公開** | 公式ドキュメント・チュートリアル・動画リンクをまとめたサイトを構築。 | 1. `mkdocs-material` 導入<br>2. `docs/` にMarkdown整備<br>3. GitHub Actionsで自動デプロイ |
| **X(Twitter)開設** | 新機能や動画投稿を発信し、ハッシュタグで拡散。 | 1. `@zundamotion` アカウント作成<br>2. `#Zundamotion #ずんだもーしょん` を固定化<br>3. GitHub Actionsからリリース通知自動投稿 |
| **READMEにデモ埋め込み** | YouTube / ニコ動への導線を作成。 | 1. README末尾にリンク＋サムネイル画像埋め込み<br>2. `![Demo](https://img.youtube.com/vi/xxxx/0.jpg)` 形式で埋め込み |

---

## 💚 Phase 4：支援・コミュニティ拡張（持続的に開発できる体制）

| タイトル | 詳細 | 具体的な手順 |
|-----------|--------|---------------|
| **GitHub Sponsors有効化** | 開発支援を受けられるようにする。 | 1. GitHub設定 → “Sponsors” → 有効化<br>2. `.github/FUNDING.yml` に自分のリンク追加 |
| **Ko-fi / BuyMeACoffee設置** | 海外向け・単発支援を受け付ける。 | 1. Ko-fi / BuyMeACoffee アカウント作成<br>2. READMEにリンク＋アイコンを設置 |
| **支援セクションREADME追記** | 公式支援リンクを明記し導線を一本化。 | 1. README末尾に支援リンク追加<br>2. アイコン＋URL形式で見やすく配置 |
| **Discordコミュニティ開設** | ユーザーと開発者が交流・サポートできる場所を用意。 | 1. Discordサーバー作成<br>2. #general, #support, #updates チャンネルを準備<br>3. README・Docsに招待リンク掲載 |
| **支援者クレジット機能** | スポンサーを動画のエンドロールに自動表示できる仕組み。 | 1. `supporters.json` などを定義<br>2. CLI実行時に動画末尾へテキスト追加する機能実装 |

---

## 🌍 Phase 5：国際化・ブランド強化（海外ユーザー対応）

| タイトル | 詳細 | 具体的な手順 |
|-----------|--------|---------------|
| **英語README作成** | 海外ユーザー向けに `README.en.md` を追加。 | 1. 日本語READMEを翻訳し、英語で再構成<br>2. 「Features / Installation / Example」形式に統一 |
| **PyPI説明英語化** | PyPIページのdescriptionを英語で書く。 | 1. `pyproject.toml` の `long_description_content_type` に英語文を追加 |
| **Hugging Face Spacesデモ** | Webブラウザで簡単に試せるGUI版を作る。 | 1. `gradio` で簡易Web UIを構築<br>2. HuggingFace Spacesにデプロイ |
| **海外YouTuberコラボ** | 「日本発の自動Vocal動画生成ツール」として紹介依頼。 | 1. AI/VTuber系海外クリエイターへ紹介DM<br>2. 英語デモ動画を共有 |

---

## 🗓️ 実施順ロードマップ（おすすめ進行）

| フェーズ | ゴール | 期間目安 |
|-----------|--------|-----------|
| Phase 1 | OSSとしての体裁を整える（README, LICENSE, CI） | 〜2週 |
| Phase 2 | 自動リリース・PyPI公開まで完成 | +1週 |
| Phase 3 | YouTube / ニコ動 / SNS導線を整備 | +1〜2週 |
| Phase 4 | 支援導線・コミュニティ体制構築 | +2週 |
| Phase 5 | 国際化＆ブランド確立 | 継続的改善 |

---
