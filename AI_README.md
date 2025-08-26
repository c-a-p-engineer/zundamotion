# AI向けプロジェクトREADME: Zundamotion

このREADMEは、AIがこのプロジェクトの目的、構造、機能、および開発プロセスを迅速に理解し、効率的に貢献できるように設計されています。

## 1. プロジェクトの目的と概要

Zundamotionは、スクリプトとアセット（音声、BGM、ビデオ）を組み合わせて、自動的に動画コンテンツを生成するためのパイプラインツールです。主に、VOICEVOXを利用した音声合成、字幕生成、背景動画のレンダリング、およびそれらの統合を行います。

**主要な機能:**
- YAML形式のスクリプトからの動画生成
- VOICEVOXによる音声合成
- 自動字幕生成
- 背景動画とBGMの統合
- キャッシュによる高速な再生成
- VOICEVOX使用情報レポートの生成: 生成された動画で使用されたVOICEVOXのキャラクターと設定をまとめたレポート（`動画ファイル名.voice_report.md`）を自動生成。

## 2. 技術スタック

- **言語**: Python 3.x
- **主要ライブラリ**:
    - `PyYAML`: YAML設定ファイルの読み込みと解析
    - `requests`: VOICEVOX APIとのHTTP通信
- **外部ツール**:
    - `FFmpeg`: 動画および音声の処理、結合、レンダリング
    - `VOICEVOX`: 音声合成エンジン (ローカルで実行されている必要があります)

## 3. プロジェクト構造

```
.
├── assets/                 # 動画生成に使用されるアセット（背景動画、キャラクター画像、BGM、効果音）
│   ├── bg/                 # 背景動画/画像
│   ├── bgm/                # 背景音楽
│   ├── characters/         # キャラクター画像
│   └── se/                 # 効果音
├── cache/                  # 生成された中間ファイルやキャッシュデータ
├── output/                 # 最終的な出力動画
├── scripts/                # サンプルスクリプトや設定ファイル
│   └── sample.yaml         # サンプルスクリプト
├── zundamotion/            # メインアプリケーションのソースコード
│   ├── __init__.py
│   ├── cache.py            # キャッシュ管理 (`CacheManager` クラス)
│   ├── exceptions.py       # カスタム例外定義
│   ├── main.py             # エントリーポイント (`main` 関数)
│   ├── pipeline.py         # 動画生成パイプラインの定義 (`GenerationPipeline` クラス, `run_generation` 関数)
│   ├── components/         # パイプラインの各ステップで使用されるコンポーネント
│   │   ├── audio.py        # 音声生成 (`AudioGenerator` クラス)
│   │   ├── script_loader.py# スクリプトと設定の読み込み、マージ、検証
│   │   ├── subtitle.py     # 字幕生成 (`SubtitleGenerator` クラス)
│   │   ├── video.py        # 動画レンダリング (`VideoRenderer` クラス)
│   │   └── voicevox_client.py # VOICEVOX APIクライアント (`generate_voice` 関数)
│   ├── pipeline_phases/    # 動画生成パイプラインの各フェーズ
│   │   ├── audio_phase.py  # 音声生成フェーズ (`AudioPhase` クラス)
│   │   ├── bgm_phase.py    # BGM追加フェーズ (`BGMPhase` クラス)
│   │   ├── finalize_phase.py # 最終化フェーズ (`FinalizePhase` クラス)
│   │   └── video_phase.py  # 動画生成フェーズ (`VideoPhase` クラス)
│   ├── reporting/          # レポート生成関連
│   │   └── voice_report_generator.py # VOICEVOX使用情報レポート生成
│   ├── templates/          # 設定テンプレート
│   │   └── config.yaml     # デフォルト設定テンプレート
│   └── utils/              # ユーティリティ関数
│       ├── ffmpeg_utils.py # FFmpeg関連ユーティリティ
│       └── logger.py       # ロギングユーティリティ
└── requirements.txt        # Pythonの依存関係
```

## 4. セットアップと実行方法

### 4.1. 前提条件

- Python 3.8以上
- FFmpeg (システムパスが通っていること)
- VOICEVOX (ローカルで実行されていること。デフォルトでは`http://127.0.0.1:50021`にアクセスします)

### 4.2. 環境構築

```bash
# 依存関係のインストール
pip install -r requirements.txt
```

### 4.3. プロジェクトの実行

```bash
# サンプルスクリプトを実行
python -m zundamotion.main scripts/sample.yaml
```

## 5. 主要機能とコードマッピング

- **プロジェクトエントリポイント**: `zundamotion/main.py` (`main` 関数)
    - 概要: アプリケーションの起動と設定の読み込みを行います。
- **パイプライン管理**: `zundamotion/pipeline.py` (`GenerationPipeline` クラス, `run_generation` 関数)
    - 概要: 動画生成パイプラインの定義と実行を管理します。
- **スクリプト/設定管理**: `zundamotion/components/script_loader.py`
    - 概要: YAMLスクリプトと設定ファイルの読み込み、マージ、検証を行います。
- **音声生成**: `zundamotion/components/audio.py` (`AudioGenerator` クラス), `zundamotion/components/voicevox_client.py` (`generate_voice` 関数), `zundamotion/pipeline_phases/audio_phase.py` (`AudioPhase` クラス)
    - 概要: VOICEVOX APIを利用した音声合成と音声ファイルの生成を処理します。
- **字幕生成**: `zundamotion/components/subtitle.py` (`SubtitleGenerator` クラス)
    - 概要: 音声データに基づいた字幕の生成を行います。
- **動画レンダリング**: `zundamotion/components/video.py` (`VideoRenderer` クラス), `zundamotion/pipeline_phases/video_phase.py` (`VideoPhase` クラス)
    - 概要: 背景動画と字幕、キャラクター画像を統合した動画のレンダリングを行います。
- **BGM追加**: `zundamotion/pipeline_phases/bgm_phase.py` (`BGMPhase` クラス)
    - 概要: 生成された動画にBGMを追加します。
- **最終化処理**: `zundamotion/pipeline_phases/finalize_phase.py` (`FinalizePhase` クラス)
    - 概要: 最終的な動画ファイルの出力を行います。
- **レポート生成**: `zundamotion/reporting/voice_report_generator.py`
    - 概要: VOICEVOXの使用状況に関するレポートを生成します。
- **キャッシュ管理**: `zundamotion/cache.py` (`CacheManager` クラス)
    - 概要: 生成された中間ファイルやキャッシュデータの管理を行います。
- **ユーティリティ**: `zundamotion/utils/ffmpeg_utils.py`, `zundamotion/utils/logger.py`
    - 概要: FFmpegコマンドの実行補助やロギング機能を提供します。特に、`normalize_media` 関数は、入力ファイルのパス、サイズ、最終更新時刻、およびFFmpegのバージョンに基づいてメディアを正規化し、結果をキャッシュします。これにより、同一素材の再変換がスキップされ、処理速度が向上します。
- **例外処理**: `zundamotion/exceptions.py`
    - 概要: カスタム例外の定義と管理を行います。
