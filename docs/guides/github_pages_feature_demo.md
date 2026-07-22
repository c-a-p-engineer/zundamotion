# GitHub Pages 機能デモサイト運用規約

この文書は、AI / Codex が Zundamotion の GitHub Pages 機能デモサイトを追加・更新するときの正本です。
サイトは単なる説明資料ではなく、現在の `master` が実際に生成できる動画を伴う公開デモとして扱います。

## 1. 目的

- `master` の機能状態と公開サイトの説明・動画を一致させる
- 利用者が技術用語を知らなくても、機能、利用場面、YAML、制限事項を理解できるようにする
- Zundamotion 自身で生成した動画を公開し、現在の実装に対する実行証跡とする
- 機能実装だけが進み、デモや説明が更新されない状態を CI で検出する
- `gh-pages` を生成物専用にし、手作業による内容ずれを防ぐ

## 2. 最初に読む資料

GitHub Pages、機能デモ、サイト生成、デモ動画、Pages Workflow を触る場合は、次の順で確認します。

1. `AGENTS.md`
2. `docs/guides/github_pages_feature_demo.md`
3. `docs/features.md`
4. `scripts/script_cheatsheet.md`
5. `docs/guides/runtime_version_policy.md`
6. `docs/guides/reproducibility_contract.md`
7. 実装後は `site/README.md`、`site/features.yml`、`.github/workflows/pages.yml`

まだ存在しない `site/` ファイルを前提に処理を進めず、初回実装時は本書の責務に沿って追加します。

## 3. 正本とブランチ

### `master`

次を置く唯一の正本です。

- Zundamotion 本体
- `docs/features.md`
- 機能紹介 manifest
- デモ用 YAML と素材
- HTML テンプレート、CSS、JavaScript
- サイト生成・検証スクリプト
- Pages Workflow

### `gh-pages`

生成済みの HTML、動画、ポスター、メタデータだけを置く生成物専用ブランチです。

- 人が直接編集しない
- AI / Codex も直接修正しない
- 正本として参照しない
- Workflow が検証成功後にだけ更新する
- `.nojekyll` を配置する

### 作業ブランチ

通常は `master` から作業ブランチを作り、実装と検証を行います。

- PR は自動作成しない
- ユーザーが直接反映を明示した場合だけ、検証成功後に `master` へ fast-forward 可能か確認して merge / push する
- fast-forward できない場合、force push や無条件 merge に切り替えず、分岐状態を報告する
- `gh-pages` は作業ブランチから更新しない

## 4. `master` からの公開フロー

公開処理は `master` への push を起点にします。

```text
master へ push
  -> manifest / YAML / 素材検証
  -> 固定ランタイム準備
  -> Zundamotion でデモ動画生成
  -> ffprobe / DTS / PTS / 容量検証
  -> ポスターと HTML 生成
  -> リンク検証
  -> gh-pages 更新
  -> GitHub Pages deploy
```

`workflow_dispatch` は作業ブランチの build と artifact 確認に使えますが、`master` 以外では `gh-pages` 更新と Pages deploy を行いません。

## 5. 新機能・機能変更時の必須確認

利用者向け機能を追加または変更した場合は、同じ変更で次を確認します。

1. `docs/features.md` の状態と説明
2. `scripts/script_cheatsheet.md` の YAML 仕様
3. 機能紹介 manifest の登録または更新
4. 対応するデモ YAML と必要素材
5. 実際の動画生成
6. 初心者向け説明、利用場面、制限事項
7. manifest / HTML / media のテスト

### 動画を必須とする状態

- `implemented`
- `partial` かつ利用者向け機能

### 動画を作らない状態

- `unverified`
- `planned`
- `rejected`
- 内部機能で `demo_required: false` と理由を明記したもの

未実装または未検証の機能について、動作しているように見せるダミー動画を作りません。

## 6. 機能紹介 manifest

機能紹介データは機械可読な manifest を正本とし、HTMLへ直接重複記載しません。

利用者向けの `implemented` / `partial` には最低限次を持たせます。

- 一意な ID
- 表示タイトル
- カテゴリ
- 状態
- 平易な要約
- 動作説明
- 利用場面
- 制限事項
- デモ YAML
- 動画出力名
- 音声必須かどうか
- 最大 duration
- 最大ファイルサイズ
- `docs/features.md` との対応名
- 関連ドキュメント

同じ動画で複数の近接機能を説明する場合は、対応する機能名をすべて追跡可能にします。

## 7. デモ YAML と素材

デモは機能を理解するための最小構成にします。

- 一つの主要機能が明確に分かる
- 説明に不要な演出を入れない
- 外部 URL や外部 CDN 素材へ依存しない
- リポジトリ内素材だけで再現できる
- 低解像度・低 fps・短時間を基本とする
- YAML 単体でも利用例として読める
- 同一入力と固定環境で同一のメディア意味を再現できる
- 失敗時に対象機能を特定できる

新しいデモ素材を追加する場合は、ライセンス、容量、再利用可否を確認します。

## 8. 動画生成ルール

原則値:

- 横動画: `640x360`
- 縦動画: `360x640`
- fps: 15 または 20
- duration: 5〜12 秒程度
- video: H.264
- audio: AAC、48 kHz、stereo
- 目標サイズ: 1 本 2 MB 以下
- poster: WebP
- `<video controls preload="metadata">`
- 音声付き動画は自動再生しない

VOICEVOX を使うデモは `.devcontainer/runtime.lock.json` の固定 CPU イメージを使用します。`latest` タグを使用しません。

動画生成失敗時は、代替動画や空動画を公開せず、Workflowを失敗させます。

## 9. メディア検証

生成した全動画について最低限次を検証します。

- ファイル存在と非ゼロサイズ
- 映像ストリーム
- 正の duration
- manifest の duration / size 上限
- 想定解像度と fps
- H.264
- 音声必須デモの音声ストリーム
- AAC、48 kHz、stereo
- 映像と音声の開始・終了差
- `non-monotonic DTS` 等の timestamp 警告がない

検証結果は機能ごとの JSON と公開用 `build-manifest.json` に残します。

## 10. HTMLの要件

各機能ページには次を表示します。

1. 専門用語を避けた一文説明
2. 実際にZundamotionで生成した動画
3. YAML抜粋とコピーボタン
4. 何が起きているか
5. 使用場面
6. 制限事項
7. 完全なYAMLへのリンク
8. 関連ドキュメント
9. 生成元commit
10. Python / FFmpeg / VOICEVOX情報
11. ffprobe結果の折りたたみ表示

静的HTMLを基本とし、React、Vue、Next.js等のフレームワークを導入しません。外部CDNへ依存しません。

375px、768px、デスクトップ幅で動画とコードが横にはみ出さないことを確認します。

## 11. 差分生成と再利用

説明文やCSSだけの変更で全動画を再生成しないよう、内容ハッシュで再利用を判断します。

入力署名には最低限次を含めます。

- デモ YAML
- 参照素材の内容
- Zundamotion の描画コード
- `runtime.lock.json`
- Python依存定義
- 動画生成スクリプト
- 出力設定

再生成ルール:

- `zundamotion/**`、runtime、依存、renderer変更: 全デモ再生成
- 特定デモ YAML / 素材変更: 該当デモ再生成
- 説明、HTML、CSS、JavaScriptのみ: 動画再利用

`mtime`ではなく内容ハッシュを使用し、署名を確認できない動画は再生成します。

## 12. Workflowの安全条件

Pages Workflowは通常CIから分離します。

- build、publish、deployを別jobにする
- build成功まで公開処理を開始しない
- `master`のpush時だけ `gh-pages` 更新とdeployを許可する
- 作業ブランチの `workflow_dispatch` はartifact生成までに限定する
- publish jobだけ `contents: write`
- deploy jobだけ `pages: write` と `id-token: write`
- jobと各renderにtimeoutを設定する
- 失敗時にVOICEVOXログ、renderログ、検証JSONをartifactへ残す
- runtimeの固定値をWorkflowへ重複記載せず、既存lockとスクリプトを使う

次のいずれかが失敗した場合は既存サイトを更新しません。

- manifest検証
- YAML load
- 動画生成
- media検証
- HTML生成
- 内部リンク検証
- 必須デモの存在確認
- `docs/features.md`との対応確認

## 13. ローカル確認

Pages関連変更は、公開前にローカルで次を確認できる構造にします。

```bash
python site/validate.py
python site/render_demos.py --output site-work
python site/build.py --input site-work --output site-dist
python site/inspect_media.py --site-dir site-dist
python -m http.server 8000 --directory site-dist
```

実際のコマンドが異なる場合は `site/README.md` を正として更新します。

`site-dist/`、生成MP4、ポスター、ログをソースブランチへコミットしません。

## 14. 完了時の報告

AI / Codex は次を報告します。

- 読んだ資料と判断根拠
- 追加・更新した機能ID
- 生成したデモ動画と検証値
- HTMLと内部リンクの確認結果
- 既存通常CIへの影響
- Pages Workflowのbuild / publish / deploy条件
- GitHub Settingsで必要な手動設定
- 作業ブランチ、コミット、`master`反映状況
- 未確認事項

`master`へ直接反映する指示がある場合は、PRを作成せず、検証成功後にfast-forward merge / pushした結果を報告します。
