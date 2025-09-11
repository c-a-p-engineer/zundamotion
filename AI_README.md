# AI向けプロジェクトREADME: Zundamotion

このREADMEは、AIがこのプロジェクトの目的、構造、機能、開発規約を素早く把握し、正確に貢献できるよう最小限で要点をまとめたものです。

## 0. プロンプト

以下の指示を守るようにしてください。

1. 推論、回答は日本語を基本にしてください。
1. プロジェクトは品質を優先に進めていきます。
1. 当プロジェクトはPythonを使用してPythonのベストプラクティスに沿ってコードを書いてください。
1. 明示指示のないコミットは禁止（ユーザーからの指示がある場合のみコミット）。
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
- キャッシュクリーンアップ処理を関数分割しメンテナンス性を向上
- 動画オーバーレイ処理をMixinへ分割し`VideoRenderer`を整理
- 音声処理ヘルパーを分割し、FFmpeg音声操作を専用モジュールへ集約
- ffprobe呼び出しを並列化し、メディアパラメータ比較を高速化
- ハードウェアエンコード自動判定（NVENC等）とフォールバック
- タイムライン/字幕ファイル出力（md/csv、srt/ass）
- 主要モジュールに日本語Docstringを整備

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
│   │   ├── video_overlays.py # オーバーレイ合成Mixin
│   │   ├── video.py          # VideoRenderer（FFmpeg合成）
│   │   ├── voicevox_client.py# VOICEVOX API（async + retry）
│   │   ├── script_loader.py  # スクリプト読込・統合（公開API: load_script_and_config）
│   │   ├── config_io.py      # YAMLローダ（構文エラー位置つき）
│   │   ├── config_merge.py   # 設定のディープマージ（override優先）
│   │   ├── config_validate.py# 設定検証（スキーマ/パス/数値範囲など）
│   │   └── pipeline_phases/  # 各フェーズ
│   │       ├── audio_phase.py
│   │       ├── video_phase.py
│   │       ├── bgm_phase.py
│   │       └── finalize_phase.py
│   ├── reporting/voice_report_generator.py
│   ├── templates/config.yaml # 既定設定
│   └── utils/ffmpeg_audio.py, ffmpeg_capabilities.py, ffmpeg_ops.py, ffmpeg_params.py, ffmpeg_hw.py, ffmpeg_probe.py, ffmpeg_runner.py, logger.py
├── .devcontainer/            # DevContainer（FFmpeg/NVENC/依存関係）
└── requirements.txt          # ローカル実行用依存

その他:
- `remove_bg_ai.py`           # rembgによる背景除去スクリプト
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
- 動画: `components/video.py`, `components/video_overlays.py`, `components/pipeline_phases/video_phase.py`
- BGM: `components/pipeline_phases/bgm_phase.py`
- 最終化: `components/pipeline_phases/finalize_phase.py`
- キャッシュ: `cache.py`
- ユーティリティ: `utils/ffmpeg_audio.py`, `utils/ffmpeg_capabilities.py`, `utils/ffmpeg_ops.py`, `utils/ffmpeg_params.py`, `utils/ffmpeg_hw.py`, `utils/ffmpeg_probe.py`, `utils/ffmpeg_runner.py`, `utils/logger.py`

## 6. 開発規約とベストプラクティス

このセクションでは、ZundamotionプロジェクトにおけるPython開発のベストプラクティスと規約を説明します。これにより、コードの一貫性を保ち、可読性、保守性、拡張性を向上させます。

### 6.1. Pythonコーディング規約 (PEP 8)

すべてのPythonコードは、[PEP 8](https://www.python.org/dev/peps/pep-0008/) に準拠する必要があります。主要なポイントは以下の通りです。

- **インデント**: スペース4つを使用します。タブは使用しません。
- **行の長さ**: 1行の最大文字数は79文字とします。

## 7. AIに読みやすいコード規模と分割基準

AI（LLM）が正確に理解・推論しやすいサイズと構成を明文化します。本プロジェクトでは以下を推奨します。

- 最適行数: 1ファイル 200–400行（上限の目安は500行）
- 関数サイズ: 20–40行（最大80行）。深い分岐はヘルパー化
- 構造: 1ファイルに5–15関数、1–3クラス程度に収める
- 概要コメント: ファイル先頭に目的/公開API/前提/外部依存/簡単な例を5–10行で記述
- 型ヒント: 主要な引数・戻り値に型ヒントを付与

分割の判断基準:
- 責務の分離: ロード/検証/キャッシュ/実行など異なる責務が混在している
- 複雑度: ネストが3段以上、条件分岐が肥大化している
- テスト容易性: テスト対象の単位が異なるものが同居している
- 依存/設定: 外部依存や設定が異なる領域が混ざっている
- 変更頻度: 変更される箇所・ペースが明確に異なる

AIに優しい書き方:
- 明示的な入出力: グローバル状態や暗黙の副作用を避ける
- 小さな関数: 早期return・ガード節で分岐を浅く保つ
- 一貫した命名: ドメイン用語を統一、略語を避ける
- ログ/エラー: 重要分岐に意味のあるメッセージを出す

AIにコードを貼るときのコツ:
- 要約を添える: 目的、現象、対象関数名、想定と実際を1–3行で
- 抜粋する: 問題の前後50–100行だけ抜粋（全量より精度↑）
- 依存関係: 関連ファイル名と役割、呼び出し順を列挙
- 実行条件: 簡単な再現手順や入力例を添える

今回の適用（構成の分割）:
- `components/script_loader.py` を責務別に再構成
  - 読み込み: `components/config_io.py`
  - マージ: `components/config_merge.py`
  - 検証: `components/config_validate.py`
  - 入口: `components/script_loader.py` は公開API `load_script_and_config` のみを保持
- 既存の `pipeline.py` からの import は変更不要（後方互換）
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
- 進捗表示（tqdm）と干渉しないよう、ログ出力は QueueHandler/QueueListener + `tqdm.write` 互換ハンドラで単一路化されています。標準出力への `print` は避け、必ず `logger` を利用してください。
- タイムスタンプは `YYYY-MM-DD HH:MM:SS.mmm`（ミリ秒3桁固定）で出力されます（JSON/KV/プレーン共通）。

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

### 6.9. GPUフィルタポリシー（CUDA/OpenCL・スケール専用フォールバック）

- 起動時にCUDA/OpenCLフィルタのスモークテストを実施し、利用可否を自動判定します。CUDA失敗時はCPUフィルタへフォールバックします（NVENCは継続利用）。
- CUDAフィルタを利用しNVENCでエンコードする場合、filter_complex内での`hwdownload`を回避し、GPU内で合成→NVENCへ直接渡します（GPU⇄CPU往復を削減）。
- 実行時にCUDA経路でエラーが発生したクリップは、1回だけCPUフィルタで自動リトライします。
- 初回のCUDAフィルタ失敗（スモーク失敗 or 実行失敗）を検知した場合、プロセス内のグローバルフラグで以降の全クリップをCPUフィルタへバックオフします（NVENCの利用可否は別途維持）。`zundamotion/utils/ffmpeg_hw.py` の `set_hw_filter_mode('cpu'|'cuda'|'auto')` により明示的な制御も可能です。
 - CPUフィルタ経路が有効な場合（グローバル`cpu`）でも、`scale_opencl` のスモークに通った環境では「GPUスケールのみ + CPU overlay（ハイブリッド）」を限定的に許可します。
- CPUフィルタ経路が有効な場合、NVENCでのエンコード有無に関わらず、`clip_workers` と `-filter_threads`/`-filter_complex_threads` は CPU 向けヒューリスティクス（`max(1, nproc // clip_workers)`）に自動調整します（環境変数での明示指定がある場合はそちらを優先）。
 - 画質プリセット→スケール最適化: CLIの `--quality` に応じてCPUスケーラのフラグを自動設定（speed=fast_bilinear, balanced=bicubic, quality=lanczos）。`video.scale_flags` で明示指定可。
 - FPS適用ポリシー: speed時は背景スケール段での `fps` フィルタを省略して（`video.apply_fps_filter: false`）、出力 `-r` でCFR固定。フィルタ段のCPU負荷を削減。

補足（診断とフォールバックの強化）:
- スモーク失敗時は一度だけ、診断情報をINFOで自動ダンプします。
  - `ffmpeg -hide_banner -buildconf`, `ffmpeg -hide_banner -filters`, `nvidia-smi -L`, `nvcc --version`
- 実行時にCUDAフィルタがエラー（exit 218/234等）となった場合も、同様の診断を一度だけ出力します。
- スモークは複数候補のフィルタグラフ（NV12+NV12／RGBAオーバレイ）を順に試行し、偽陰性を低減します。
- `scale_cuda` が列挙されない環境で `scale_npp` が存在する場合、GPUパスでは `scale_npp` を優先的に使用します（自動選択）。
 - DevContainerでCUDAフィルタを確実に有効化したい場合は、`.devcontainer/Dockerfile.gpu` の `BUILD_FFMPEG_FROM_SOURCE=1` を指定し、`--enable-cuda-nvcc --enable-libnpp --enable-nonfree` でFFmpegをビルドしてください。
- 字幕PNGはRGBAレイヤのため、既定ではCPU overlayを使用します（`video.gpu_overlay_experimental` をtrueにするとGPUを試行）。
- CPUモード時でも `smoke_test_cuda_scale_only` のスモークに通った環境では、背景の「GPUスケールのみ + CPU overlay（ハイブリッド）」を限定的に許可します（背景スケールの高速化が目的）。OpenCL についても `smoke_test_opencl_scale_only` を通過した場合に同様のハイブリッドを許可します。
- RGBAオーバーレイでCPU合成となる場合でも、背景スケーリングのみGPUで先行してからCPUへ戻すハイブリッド最適化が可能です（`video.gpu_scale_with_cpu_overlay: true` 既定有効）。
- 字幕PNGのプリキャッシュ（`video.precache_subtitles: true`）で、行ごとの字幕PNGをシーン開始時に並列生成し、VideoPhase中のばらつきを抑制します。
  - `video.precache_min_lines` により、`precache_subtitles=false` でも行数が閾値以上の場合は自動で有効化されます。
  - 立ち絵PNGは Pillow で目標スケールに事前変換しキャッシュ。CPU overlay 時は `scale` フィルタを省いて `format=rgba` のみで合成（`CHAR_CACHE_DISABLE=1` で無効）。
  - `video.allow_opencl_overlay_in_cpu_mode: true` が指定され、OpenCL のスモークに合格した場合は、グローバル `cpu` モードでも `overlay_opencl` を許可します（安定性優先のオプトイン）。

補足（運用トグル／チューニング）:
- 環境変数で挙動を制御できます。
  - `HW_FILTER_MODE={auto|cuda|cpu}`: CUDAフィルタの利用方針をプロセス全体で固定（`auto`が既定）。
  - `FFMPEG_FILTER_THREADS` / `FFMPEG_FILTER_COMPLEX_THREADS`: FFmpegのフィルタスレッド数を明示的に上書き。未指定時は上記ヒューリスティクスを採用。
- CPUフィルタ経路では `clip_workers × filter_threads` の過剰化を避けるため、`filter_threads = max(1, nproc // clip_workers)` を目安に設定してください（既定ロジックが自動調整）。
- ログには各フェーズの所要時間が `--- Finished: <Phase>.run. Duration: X.YZ seconds ---` として出力されます。ボトルネック抽出は `logs/YYYYMMDD_*.log` を参照してください。
- 追加計測: VideoPhase終了時に「最も遅い行クリップTop5」と「フィルタ経路の使用回数（cuda/opencl/gpu_scale_only/cpu）」をINFOで出力します。加えて、起動時にフィルタ存在とスモーク結果（CUDA/OpenCL/スケール専用）をINFOでサマリ表示します。
 - CPUフィルタモード起動時は初期 `clip_workers<=2` に抑え、AutoTune前の過剰並列を回避します。

### 6.10. シーンベース生成スキップ（static overlays = 0）

- 静的オーバーレイが存在しないシーンでは、ベース映像（背景のみのループ書き出し）を原則スキップします。
- 背景が動画の場合は、シーン開始時に一度だけ正規化（`normalize_media`）し、そのパスを各行の `background_config` に `normalized=True`/`pre_scaled=True` として伝搬します。
  - 行側の `filter_complex` から二重スケールを除去し、正規化時のスケーリングと重複しないようにします。
  - シーン内で全行共通の「挿入メディア（動画）」がある場合も同様に、シーン開始時に一度だけ正規化し、各行の `insert` に `normalized=True`/`pre_scaled=True` で伝搬します（行ごとの再正規化を抑止）。
- 行数が多いシーンでは、ベース生成の方が有利な場合があるため、`video.scene_base_min_lines` 以上の行数であれば（静的オーバーレイが無くても）ベース生成を有効化します。
  - 既定値: `scene_base_min_lines: 6`
  - 静的オーバーレイが1つ以上ある場合は、常にベース生成を行い、静的レイヤを事前合成します。

補足（キャッシュ無効時の重複排除）:
- `--no-cache` 指定時でも、同一キー（入力パス＋変換パラメータ）に対する一時生成物が既に存在する場合は、再生成せずに同一出力を再利用します（プロセス内メモ＋ファイル存在チェック）。

### 6.11. 口パク/目パチ（最小版・音量しきい値）

- 音声WAVを一定FPS（既定15fps）でRMSサンプリングし、最大RMS比の二段閾値で `mouth={close,half,open}` を生成します。
- 目パチは 2–5 秒ランダム間隔で、`blink_close_frames`（既定2フレーム）だけ閉眼します。
- アセット規約（存在しない場合は自動無効化）:
  - `assets/characters/<name>/mouth/{close,half,open}.png`
  - `assets/characters/<name>/eyes/{open,close}.png`
- 実装:
  - `AudioPhase` が各 line の `line_data_map[line_id]['face_anim']` に `{target_name, mouth[], eyes[], meta}` を注入。
  - `VideoPhase` が上記を `VideoRenderer.render_clip(..., face_anim=...)` に渡し、ビデオキャッシュキーに最小限のメタ（しきい値/バージョン）を含めます。
  - `VideoRenderer` は差分PNGを `overlay:x=..:y=..:enable='between(t,...) + between(t,...)'` で合成。`mouth/close` と `eyes/open` をベースで常時、`mouth/half|open` と `eyes/close` は区間のみ上書きします。
- 設定（`video.face_anim`）:
  - `mouth_fps`=15, `mouth_thr_half`=0.2, `mouth_thr_open`=0.5
  - `blink_min_interval`=2.0, `blink_max_interval`=5.0, `blink_close_frames`=2

### 6.12. FFmpegプロファイルとスレッド上限（caps）

- 環境変数で計測とスレッド動作を制御できます。
  - `FFMPEG_PROFILE_MODE=1`: すべてのFFmpeg実行に `-benchmark -stats` を付与（所要時間・fps等の統計をstderrに出力）。
  - `FFMPEG_THREADS`: グローバルの `-threads` を明示上書き（未指定時はFFmpeg既定）。
  - `FFMPEG_FILTER_THREADS_CAP` / `FFMPEG_FILTER_COMPLEX_THREADS_CAP`: フィルタスレッドの上限をキャップ。既定はCPUフィルタ経路で各4、GPU経路では1。
- CPUフィルタ経路では過剰並列を避けるため、`clip_workers` と合わせて保守的に設定されます。

補足（自動チューニング）:
- `video.auto_tune: true` の場合、先頭Nクリップ（`video.profile_first_clips`, 既定4）を計測し、CPU overlay が支配的と判定された場合は `FFMPEG_FILTER_THREADS_CAP`/`FFMPEG_FILTER_COMPLEX_THREADS_CAP` を保守的な値（2）に設定。CPUコア数に応じて `clip_workers` を 2→3/4 まで再探索し、平均/90パーセンタイルの所要をログに出力します。
- 計測後は `FFMPEG_PROFILE_MODE` を無効化してオーバーヘッドを回避します。
- 併せて、CPU overlay が支配的なケースでは `set_hw_filter_mode('cpu')` を適用し、プロセス全体でCPUフィルタ経路に統一します（NVENCによるエンコードは継続）。

### 6.13. テキスト/字幕/音声（表示と読みの分離）

- セリフの `text` は字幕とタイムラインの表示に使用。
- 音声の読みを差し替えたい場合は、行に `reading`（または `read`）を指定（例: `text: "本気"`, `reading: "マジ"`）。
- 字幕だけ個別に差し替えたい場合は `subtitle_text` を指定（無指定時は `text`）。

実装ポイント:
- AudioPhase で `reading` を優先して TTS 入力に使用。`text` は表示（字幕/タイムライン）に使用。
- line_data_map には `text`（表示用）と `tts_text`（音声用）の双方を格納。
- SubtitlePNG は `text`/`subtitle_text` に基づいて生成される（VideoPhase 側の集約で適用）。

### 6.14. 一時ディレクトリ（RAMディスク優先）

- 空き容量が十分な場合、`/dev/shm`（RAMディスク）を `temp_dir` として優先利用します（`USE_RAMDISK=1` 既定）。
- `--no-cache` 時は生成物を `temp_dir`（Ephemeral）に出力し、同一キーの重複生成をプロセス内で抑止します（in-flight集約＋既存ファイル再利用）。

### 6.14. 正規化メタと再正規化抑止

- 正規化出力（`temp_normalized_*.mp4` 等）に隣接して `<name>.meta.json` を書き出し、`target_spec` を保存します。
- 入力が既に正規化済みで、隣接メタの `target_spec` が現在の要求と一致する場合は再正規化をスキップします（ディレクトリに依存しない判定）。

### 6.15. concatのI/O最適化

- `-f concat -c copy` のリストファイルは出力先ディレクトリに配置し、I/O局所性を高めています。`FFMPEG_PROFILE_MODE=1` で結合時の所要も観測可能です。

### 6.16. 字幕PNGのフォントフォールバックとキャッシュ

- フォントは複数の既知パスを探索し、見つからない場合はシステムのデフォルトにフォールバックします。
- 同一フォント/サイズの `ImageFont` をプロセス内でキャッシュし、初期化のばらつき（レイテンシスパイク）を抑制します。
