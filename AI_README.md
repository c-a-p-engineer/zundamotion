# AI向けプロジェクトREADME: Zundamotion

このREADMEは、AIがこのプロジェクトの目的、構造、機能、開発規約を素早く把握し、正確に貢献できるよう最小限で要点をまとめたものです。

## 0. プロンプト

以下の指示を守るようにしてください。

1. 推論、回答は日本語を基本にしてください。
1. プロジェクトは品質を優先に進めていきます。
1. 当プロジェクトはPythonを使用してPythonのベストプラクティスに沿ってコードを書いてください。
1. コードは以下の原則を守ってください。
  1. DRY (Don't Repeat Yourself)<br>重複を避けることで、保守性・可読性を高め、変更時の修正漏れを防ぐ。
  1. KISS (Keep It Simple, Stupid)<br>設計や実装を過度に複雑にせず、できる限りシンプルに保つ。
  1. YAGNI (You Aren't Gonna Need It)<br>「その機能はどうせ必要にならない」→ 実際に必要になるまで作らない。

## 1. プロジェクト概要

Zundamotionは、YAML台本・アセット（音声/BGM/背景/立ち絵/挿入メディア）を入力として、音声合成（VOICEVOX）、字幕生成、合成、最終出力までを自動化する動画生成パイプラインです。

主要機能:
- YAML台本からの動画自動生成
- VOICEVOXによる非同期音声合成（httpx + tenacity）
- 字幕画像(PNG)の事前生成→overlay合成（高速で安定）
- BGM/効果音の挿入、シーン毎のループ背景、挿入メディア（画像/動画）
- シーン単位のベース映像生成（背景＋静的レイヤを事前合成）→各行では字幕と音声のみ重ねる
- キャッシュ最適化（正規化、メタ情報、クリップ、シーン連結）
- ハードウェアエンコード自動判定（NVENC等）とフォールバック
- タイムライン/字幕ファイル出力（md/csv、srt/ass）

## 2. 技術スタック

- 言語: Python 3.11+（DevContainerは3.13）
- 主要ライブラリ: PyYAML, httpx, tenacity, Pillow, tqdm, pysubs2
- 外部ツール: FFmpeg 7系, VOICEVOX エンジン

## 3. プロジェクト構造

```
.
├── assets/                   # 素材（bg, bgm, characters, se）
├── cache/                    # キャッシュ（正規化/メタ/生成物）
├── logs/                     # 実行ログ
├── output/                   # 最終出力（mp4/srt/md等）
├── scripts/                  # サンプル台本
├── zundamotion/              # ソースコード
│   ├── main.py               # CLIエントリ（async）
│   ├── pipeline.py           # パイプライン制御
│   ├── cache.py              # CacheManager
│   ├── components/
│   │   ├── audio.py          # AudioGenerator
│   │   ├── subtitle.py       # 字幕オーバーレイ準備
│   │   ├── subtitle_png.py   # 字幕PNG生成(Pillow)
│   │   ├── video.py          # VideoRenderer（FFmpeg合成）
│   │   ├── voicevox_client.py# VOICEVOX API（async + retry）
│   │   └── pipeline_phases/  # 各フェーズ
│   │       ├── audio_phase.py
│   │       ├── video_phase.py
│   │       ├── bgm_phase.py
│   │       └── finalize_phase.py
│   ├── reporting/voice_report_generator.py
│   ├── templates/config.yaml # 既定設定
│   └── utils/ffmpeg_utils.py, logger.py
├── .devcontainer/            # DevContainer（FFmpeg/NVENC/依存関係）
└── requirements.txt          # ローカル実行用依存
```

注意:
- pipeline_phases は `zundamotion/components/pipeline_phases/` 配下です。
- DevContainer使用時の依存は `.devcontainer/requirements.txt` にあります。

## 4. セットアップと実行

- DevContainer（推奨）:
  - VSCodeで「Reopen in Container」。VOICEVOXはDocker Composeで`voicevox:50021`に起動。
  - 実行: `python -m zundamotion.main scripts/sample.yaml`
- ローカル実行:
  - FFmpeg 7系、VOICEVOXエンジン起動（既定 `http://127.0.0.1:50021`）
  - 依存: `pip install -r requirements.txt`
  - 実行: `python -m zundamotion.main scripts/sample.yaml`
- 環境変数: `VOICEVOX_URL` を DevContainerでは `http://voicevox:50021` に設定推奨。

CLI主なオプション（main.py実装）:
- `--jobs {auto|N}` 並列度
- `--hw-encoder {auto|gpu|cpu}` / `--quality {speed|balanced|quality}`
- `--timeline [md|csv|both]` / `--no-timeline`
- `--subtitle-file [srt|ass|both]` / `--no-subtitle-file`
- `--no-cache` / `--cache-refresh`

## 5. 主要機能とコード対応

- エントリ: `zundamotion/main.py` → `pipeline.run_generation`
- パイプライン: `zundamotion/pipeline.py`（Audio→Video→BGM→Finalize）
- 音声: `components/audio.py`, `components/voicevox_client.py`, `components/pipeline_phases/audio_phase.py`
- 字幕: `components/subtitle.py`, `components/subtitle_png.py`
- 動画: `components/video.py`, `components/pipeline_phases/video_phase.py`
- BGM: `components/pipeline_phases/bgm_phase.py`
- 最終化: `components/pipeline_phases/finalize_phase.py`
- キャッシュ: `cache.py`
- ユーティリティ: `utils/ffmpeg_utils.py`, `utils/logger.py`

## 6. 開発規約とベストプラクティス

このセクションでは、ZundamotionプロジェクトにおけるPython開発のベストプラクティスと規約を説明します。これにより、コードの一貫性を保ち、可読性、保守性、拡張性を向上させます。

### 6.1. Pythonコーディング規約 (PEP 8)

すべてのPythonコードは、[PEP 8](https://www.python.org/dev/peps/pep-0008/) に準拠する必要があります。主要なポイントは以下の通りです。

- **インデント**: スペース4つを使用します。タブは使用しません。
- **行の長さ**: 1行の最大文字数は79文字とします。
- **命名規約**:
    - モジュール名: 小文字とアンダースコア (`snake_case`)
    - パッケージ名: 小文字 (`snake_case`)
    - クラス名: キャメルケース (`CamelCase`)
    - 関数名、メソッド名、変数名: 小文字とアンダースコア (`snake_case`)
    - 定数: 大文字とアンダースコア (`UPPER_SNAKE_CASE`)
- **空白行**:
    - トップレベルの関数とクラス定義の間には2行の空白行を入れます。
    - クラス内のメソッド定義の間には1行の空白行を入れます。
- **インポート**:
    - 各インポートは別々の行に記述します。
    - 標準ライブラリ、サードパーティライブラリ、ローカルライブラリの順にグループ化し、各グループ間に空白行を入れます。
    - `from module import name` 形式を推奨します。

### 6.2. 設計原則

#### 6.2.1. KISS (Keep It Simple, Stupid) の原則

- **目的**: コードをできるだけシンプルに保ち、不必要な複雑さを避けることで、理解しやすく、保守しやすいシステムを構築します。
- **実践**:
    - 最小限の機能で問題を解決することを常に目指します。
    - 複雑なロジックは小さな関数やクラスに分割します。
    - 不必要な抽象化や汎用化は避けます。将来のニーズを過度に予測してコードを複雑にしないようにします。
    - 明確で簡潔なコードを記述し、トリッキーな実装を避けます。

#### 6.2.2. DRY (Don't Repeat Yourself) の原則

- **目的**: コードの重複を避け、同じロジックが複数の場所に存在しないようにします。これにより、コードの保守性が向上し、バグの発生を減らします。
- **実践**:
    - 繰り返し現れるコードブロックやロジックは、関数、クラス、またはモジュールとして抽象化します。
    - 共通のユーティリティ関数やヘルパークラスを作成し、再利用します。
    - 設定値やマジックナンバーは定数として定義し、一元管理します。
    - パイプラインの各フェーズやコンポーネントで共通する処理は、基底クラスや共通関数として実装することを検討します。

### 6.3. エラーハンドリング

- 予期されるエラーや例外は適切にキャッチし、ユーザーフレンドリーなメッセージで処理します。
- 予期しないエラーはログに記録し、プログラムがクラッシュしないようにします。
- カスタム例外 (`zundamotion/exceptions.py` に定義) を活用し、エラーの種類を明確にします。

### 6.4. ロギング

- `zundamotion/utils/logger.py` に定義されているロギングユーティリティを使用します。
- 適切なログレベル (DEBUG, INFO, WARNING, ERROR, CRITICAL) を使い分けます。
- 開発中はDEBUGレベル、本番環境ではINFOレベル以上を推奨します。
- 重要なイベント、エラー、デバッグ情報は必ずログに記録します。

### 6.5. テスト

- 可能な限りユニットテストと統合テストを記述し、コードの品質と信頼性を保証します。
- 特に、パイプラインの各コンポーネントやフェーズは独立してテストできるように設計します。
- テストコードは、対応するソースコードと同じディレクトリ構造に配置し、`test_` プレフィックスを付けます。

### 6.6. ドキュメンテーション

- すべてのモジュール、クラス、関数、メソッドには、Docstring (PEP 257) を記述します。
- Docstringは、そのコードブロックの目的、引数、戻り値、発生しうる例外などを明確に説明します。
- 複雑なアルゴリズムやビジネスロジックには、インラインコメントを追加して説明します。
- `AI_README.md` は常に最新の状態に保ち、プロジェクトの全体像を正確に反映させます。

### 6.7. 依存関係管理

- プロジェクトの依存関係は `requirements.txt` に明示的に記述します。
- `pip install -r requirements.txt` で再現可能な環境を構築できるようにします（DevContainerは `.devcontainer/requirements.txt`）。
- 開発依存関係 (テストツールなど) は別途 `requirements-dev.txt` などに分離することを検討します。

### 6.8. パフォーマンス考慮事項

- キャッシュ機構 (`zundamotion/cache.py`) を最大限に活用し、再生成時の処理速度を向上させます。
- FFmpegの呼び出しは、不必要な再エンコードを避けるように最適化します。
- 大規模なデータ処理を行う際は、メモリ使用量とCPU負荷を考慮し、効率的なアルゴリズムを選択します。

### 6.9. GPUフィルタポリシー（overlay_cuda/scale_cuda）

- 起動時にCUDAフィルタのスモークテストを実施し、失敗する環境では自動的にCPUフィルタへフォールバックします（NVENCは継続利用）。
- CUDAフィルタを利用しNVENCでエンコードする場合、filter_complex内での`hwdownload`を回避し、GPU内で合成→NVENCへ直接渡します（GPU⇄CPU往復を削減）。
- 実行時にCUDA経路でエラーが発生したクリップは、1回だけCPUフィルタで自動リトライします。
- 初回のCUDAフィルタ失敗（スモーク失敗 or 実行失敗）を検知した場合、プロセス内のグローバルフラグで以降の全クリップをCPUフィルタへバックオフします（NVENCの利用可否は別途維持）。`zundamotion/utils/ffmpeg_utils.py` の `set_hw_filter_mode('cpu'|'cuda'|'auto')` により明示的な制御も可能です。
 - CPUフィルタ経路が有効な場合（グローバルが`cpu`）、NVENCでのエンコード有無に関わらず、`clip_workers` と `-filter_threads`/`-filter_complex_threads` は CPU 向けヒューリスティクス（`max(1, nproc // clip_workers)`）に自動調整します（環境変数での明示指定がある場合はそちらを優先）。

補足（運用トグル／チューニング）:
- 環境変数で挙動を制御できます。
  - `HW_FILTER_MODE={auto|cuda|cpu}`: CUDAフィルタの利用方針をプロセス全体で固定（`auto`が既定）。
  - `FFMPEG_FILTER_THREADS` / `FFMPEG_FILTER_COMPLEX_THREADS`: FFmpegのフィルタスレッド数を明示的に上書き。未指定時は上記ヒューリスティクスを採用。
- CPUフィルタ経路では `clip_workers × filter_threads` の過剰化を避けるため、`filter_threads = max(1, nproc // clip_workers)` を目安に設定してください（既定ロジックが自動調整）。
- ログには各フェーズの所要時間が `--- Finished: <Phase>.run. Duration: X.YZ seconds ---` として出力されます。ボトルネック抽出は `logs/YYYYMMDD_*.log` を参照してください。

### 6.10. シーンベース生成スキップ（static overlays = 0）

- 静的オーバーレイが存在しないシーンでは、ベース映像（背景のみのループ書き出し）を原則スキップします。
- 背景が動画の場合は、シーン開始時に一度だけ正規化（`normalize_media`）し、そのパスを各行の `background_config` に `normalized=True`/`pre_scaled=True` として伝搬します。
  - 行側の `filter_complex` から二重スケールを除去し、正規化時のスケーリングと重複しないようにします。
- 行数が多いシーンでは、ベース生成の方が有利な場合があるため、`video.scene_base_min_lines` 以上の行数であれば（静的オーバーレイが無くても）ベース生成を有効化します。
  - 既定値: `scene_base_min_lines: 6`
  - 静的オーバーレイが1つ以上ある場合は、常にベース生成を行い、静的レイヤを事前合成します。
