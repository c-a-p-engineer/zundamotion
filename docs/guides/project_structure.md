# プロジェクト構造

このガイドは、Zundamotion リポジトリの構成と主要コンポーネントの役割をまとめたものです。

関連:

- [docs 入口](../README.md)
- [README](../../README.md)
- [AI 向け低トークン規約](./ai_coding_rules.md)
- [Python コード規約](./python_coding_rules.md)
- [セットアップと実行](./setup_and_runtime.md)
- [台本チートシート](../../scripts/script_cheatsheet.md)

## 技術スタック

- 言語: Python 3.x
- 主要ライブラリ:
  - `PyYAML`
  - `requests`
  - `httpx`
  - `tenacity`
  - `pysubs2`
  - `Pillow`
- 外部ツール:
  - `FFmpeg`
  - `VOICEVOX`

## 主要ディレクトリ

```text
.
├── assets/                 # 背景、立ち絵、BGM、SE
├── docs/                   # ガイド、設計メモ、機能一覧
├── output/                 # 出力動画
├── scripts/                # サンプル台本、確認用 YAML
├── tools/                  # 補助ツール
├── zundamotion/            # 本体コード
└── requirements.txt        # 依存関係
```

## `zundamotion/` 配下

```text
zundamotion/
├── cache.py
├── exceptions.py
├── main.py
├── pipeline.py
├── components/
│   ├── audio/
│   ├── config/
│   ├── pipeline_phases/
│   ├── script/
│   ├── subtitles/
│   └── video/
├── reporting/
├── templates/
└── utils/
```

## 主な責務

- `components/audio/`
  - VOICEVOX 通常発話、音声生成、音声ミックス
- `components/config/`
  - YAML ロード、マージ、検証
- `components/script/`
  - 設定統合の入口 API
- `components/subtitles/`
  - 字幕生成、PNG 字幕レンダリング
- `components/video/`
  - 動画レンダリング、overlay 合成、立ち絵処理
- `components/pipeline_phases/`
  - Audio / Video / Finalize / BGM 各フェーズ
- `utils/`
  - FFmpeg 実行、probe、ハードウェア判定、ログ

## 関連ドキュメント

- YAML の書き方: [`../../scripts/script_cheatsheet.md`](../../scripts/script_cheatsheet.md)
- 機能一覧: [`../features.md`](../features.md)
- docs 入口: [`../README.md`](../README.md)
