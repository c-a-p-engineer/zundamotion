# Git submodule で取り込んで使う

このドキュメントは、Zundamotion を **利用側プロジェクトに git submodule として取り込み**、動画生成機能を呼び出すための手順をまとめたものです。

## 推奨構成

```
your-project/
  vendor/
    zundamotion/        # git submodule
  scripts/              # 利用側の台本置き場（任意）
  assets/               # 利用側の素材置き場（任意）
  output/               # 出力先（任意）
```

## 1) submodule 追加（利用側リポジトリで実行）

```bash
git submodule add <GIT_URL> vendor/zundamotion
git submodule update --init --recursive
```

更新する場合:

```bash
git submodule update --remote --merge
```

## 2) インストール（推奨: editable）

利用側の仮想環境に、サブモジュールを editable install します。

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e vendor/zundamotion
```

フォールバック（editable を使わない場合）:

```bash
pip install -r vendor/zundamotion/requirements.txt
```

さらに最小のフォールバック（環境依存で動く場合）:

```bash
PYTHONPATH=vendor/zundamotion python -m zundamotion.main --help
```

## 3) 実行

### 利用側プロジェクトを基準に実行（推奨）

相対パス（`assets/...` など）は **利用側プロジェクト基準**で解決します。

```bash
zundamotion path/to/script.yaml -o output/out.mp4
```

### サブモジュール同梱サンプルを試す

相対パス基準をサブモジュールに切り替えるには `--project-root` を使います。

```bash
zundamotion scripts/sample.yaml --project-root vendor/zundamotion
```

## 相対パスの基準（`--project-root` / `ZUNDAMOTION_PROJECT_ROOT`）

- 未指定: 実行時のカレントディレクトリ基準
- 指定: `--project-root`（または `ZUNDAMOTION_PROJECT_ROOT`）のディレクトリへ移動してから処理を開始します

用途:
- 利用側プロジェクトに素材を置く（例: `assets/`） → `--project-root` は不要（または `--project-root .`）
- サブモジュール側の `assets/` や `scripts/` をそのまま使う → `--project-root vendor/zundamotion`

## 依存関係について（重要）

- FFmpeg / ffprobe は実行環境に必要です（`ffmpeg` と `ffprobe` が PATH にあること）
- VOICEVOX エンジン連携を使う場合、利用側で VOICEVOX の利用規約・実行環境（Docker 等）を整備してください

