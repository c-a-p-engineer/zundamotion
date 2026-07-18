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

- 言語: CPython 3.14 系（最新安定版、パッチ版は固定しない）
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

## VideoPhase のシーン描画

`components/pipeline_phases/video_phase/scene_renderer.py` は公開入口です。
既存コードは引き続き `SceneRenderer` をこのモジュールから import します。
実装を調べるときは、変更内容に応じて次のファイルだけを先に読みます。

| 変更内容 | 最初に読むファイル | 責務 |
| --- | --- | --- |
| 初期化、シーン実行順序、公開 API | `scene_renderer.py` | `SceneRenderer` facade、永続状態適用、描画経路の呼び出し |
| 背景、badge、画像レイヤー、顔差分の事前準備 | `scene_preparation.py` | scene / line 単位の素材・状態解決とprecache |
| simple scene fast path | `scene_fast_path.py` | 適用可否、キャラクター式、単一FFmpegグラフ生成 |
| scene cache、字幕entry | `scene_cache.py` | base/subtitle cache payloadと字幕タイミング |
| 通常の行クリップ描画とscene組み立て | `scene_standard_renderer.py` | line並列描画、base/subtitle合成、cache保存 |

`scene_*.py` の Mixin は内部実装です。外部から直接インスタンス化せず、
`scene_renderer.SceneRenderer` 経由で利用します。

`scene_standard_renderer.py` は既存の標準描画処理を挙動変更なしで隔離した段階で、
まだ規約上限を超えています。変更時はファイル全体を先に読まず、
対象ブロックと呼び出す Mixin の契約を確認してください。

## 関連ドキュメント

- YAML の書き方: [`../../scripts/script_cheatsheet.md`](../../scripts/script_cheatsheet.md)
- 機能一覧: [`../features.md`](../features.md)
- docs 入口: [`../README.md`](../README.md)
