# 🎬 Zundamotion: YAML台本から動画を自動生成する開発環境

Zundamotionは、VOICEVOXによる高品質な音声合成とFFmpegを用いた映像合成を組み合わせ、YAML形式の台本から`.mp4`動画を自動生成する強力な開発環境です。動画制作のワークフローを効率化し、コンテンツ作成を加速します。

---

## 🚀 機能概要

- **VOICEVOX連携**: Dockerを利用したVOICEVOXエンジンとの連携により、高品質な音声合成を実現します。
- **FFmpegによる動画合成**: 背景、キャラクター、字幕、音声をFFmpegでシームレスに統合し、プロフェッショナルな動画を生成します。
- **BGM逐次制御（start/stop/resume）**: 台本の流れに沿ってBGMを順次開始・停止・再開でき、フェード指定にも対応します。
- **Topic（YouTubeチャプター）生成**: 台本内のtopic指定からチャプター用テキストを自動生成します。
- **音声/色フィルタのプリセット**: 音声合成後の音声フィルタと、レイヤー単位の色フィルタをプリセットから適用できます。
- **YAMLベースの台本**: 直感的で記述しやすいYAML形式の台本から、音声と字幕を自動生成します。
- **Markdown入力（Frontmatter対応）**: Frontmatter付きMarkdown（`.md`）を解析し、画像生成→中間YAML台本生成を経由して既存パイプラインで動画化できます。`output/intermediate/<script名>/` に中間生成物を保存するためデバッグしやすい設計です。
- **台本の再利用 (`include` / `vars`)**: シーンやプリセットを分割して読み込み、`${VAR}` による簡易置換で台本を再利用できます。
- **VOICEVOX不要の無音生成**: `--no-voice` で無音トラックを自動生成し、音声合成なしで動画を作成できます。
- **多様な字幕出力**: SRT形式とFFmpeg `drawtext`用のJSON形式字幕ファイルの両方を出力し、柔軟な動画編集に対応します。
- **堅牢なバリデーション**: 実行前にYAML構文、参照される素材ファイル（背景、BGM、キャラクター画像など）の存在、および音声パラメータ（速度、ピッチ、音量など）の有効範囲を自動でチェックします。エラー発生時には、具体的なエラーメッセージと該当する行番号・列番号が表示され、問題の特定と修正を支援します。
- **進捗バー＋ETA表示**: CLI上で動画生成の全体進捗率と残り時間をリアルタイムで表示し、ユーザー体験を向上させます。
- **ファイルログ出力**: すべてのログは `./logs/YYYYMMDD_HHMMS_MS.log` の形式でファイルに出力されます。
- **JSONログ出力**: `--log-json`オプションを使用することで、機械可読なJSON形式でログをコンソールに出力し、GUIや外部ツールとの連携を容易にします。
- **KVログ出力**: `--log-kv`オプションを使用することで、人間が読みやすいKey-Value形式でログをコンソールに出力し、ログの解析とボトルネックの特定を容易にします。
- **日本語Docstring**: 主要な関数・クラスに日本語コメントを付与し、コードの理解を助けます。
- **キャッシュクリーンアップのモジュール化**: キャッシュ削除処理を関数に分割し、保守性を向上させました。
- **オーバーレイ処理のモジュール化**: 前景動画や字幕の合成をMixinに切り出し、`VideoRenderer`を簡潔にしました。
- **音声処理ヘルパーの分離**: FFmpeg音声操作を`ffmpeg_audio.py`に集約し、責務を明確化しました。
- **メディアパラメータ比較の並列化**: 複数ファイルのffprobeを同時実行し、前処理を高速化しました。
- **設定ローダの責務分離**: YAML読み込み（`config/io.py`）/ディープマージ（`config/merge.py`）/検証（`config/validate.py`）に分割し、`script/loader.py`はエントリAPIに集約しました。
- **ドロップインプラグイン**: `plugins.enabled/allow/deny/paths` でエフェクトや字幕エフェクトをドロップイン追加・無効化でき、組み込みプラグインはキャッシュされたレジストリ経由で即時利用できます。
- **AIに読みやすい規模の徹底**: 1ファイル200–400行（最大500）、1関数20–40行（最大80）の目安で分割・整理。AI / Codex 作業ルールは [AGENTS.md](AGENTS.md) に集約しています。
- **並列レンダリングとハードウェアエンコードの自動検出**: CPUコア数やGPU（NVENC/VAAPI/VideoToolbox）を検出し、最適なジョブ数を自動設定します。ハードウェアエンコードが利用可能な場合は自動的に活用し、失敗時はソフトウェアにフォールバックします。
- **音声生成の先行並列化**: `voice.parallel_workers` に応じて音声合成タスクを先行起動し、タイムライン順を維持したまま AudioPhase の待ち時間を短縮します。
- **字幕焼き込みの自動切替**: 軽量な字幕ボックスは内部で `ASS/libass`、角丸や枠線や背景画像を含む装飾付き字幕は `PNG` を自動選択します。
- **字幕 PNG プロセスプールの共有**: シーンごとに字幕用プロセスプールを作り直さず、ラン全体で共有してウォームアップコストを削減します。
- **`cache_refresh` の実効性改善**: 同一キーは 1 実行につき 1 回だけ無効化し、シーンキャッシュも含めて再生成されるようにしました。並列生成も同一キーは 1 本に集約します。
- **完成版合成の単発スレッド最適化**: 前景/字幕の最終焼き込みは単発ジョブ向けの FFmpeg スレッド設定を使い、行クリップ用 `clip_workers` の影響を受けにくくしています。
- **シーン並列レンダリング（任意）**: `video.scene_workers` を有効化すると、独立シーンを並列で描画できます。GPU エンコード時は `1`、CPU中心時に `auto` または `2` が目安です。
- **単純シーンの fast path**: 背景画像差し替え + 単一キャラ + 通常発話だけのシーンは、GPU 利用時に 1 シーン 1 FFmpeg へ寄せる fast path を使えます。CPU では逆効果になりやすいため既定では無効です。
- **キャラクター配置の柔軟性**: キャラクターの表示位置をX/Y座標で指定できるだけでなく、スケーリング（拡大縮小）やアンカーポイント（画像の基準点）を設定することで、より細かくキャラクターの配置を制御できます。
  - `scale`: キャラクター画像の拡大縮小率を指定します（例: `0.8` で80%のサイズ）。
  - `anchor`: キャラクター画像を配置する際の基準点（アンカーポイント）を指定します。以下のいずれかの値を設定できます。
    - `top_left`: 画像の左上を基準点とします。
    - `top_center`: 画像の上辺中央を基準点とします。
    - `top_right`: 画像の右上を基準点とします。
    - `middle_left`: 画像の左辺中央を基準点とします。
    - `middle_center`: 画像の中心を基準点とします。
    - `middle_right`: 画像の右辺中央を基準点とします。
    - `bottom_left`: 画像の左下を基準点とします。
    - `bottom_center`: 画像の底辺中央を基準点とします（デフォルト）。
    - `bottom_right`: 画像の右下を基準点とします。
  - `position`: `x`, `y` 座標は、指定された `anchor` からのオフセットとして機能します。例えば、`anchor: bottom_center` で `position: {x: 0, y: 0}` の場合、キャラクターの底辺中央が背景の底辺中央に配置されます。`position: {x: 100, y: -50}` の場合、底辺中央から右に100ピクセル、上に50ピクセル移動します。
  - `flip_x`: `true` にするとキャラクター画像を左右反転します。右向きの立ち絵を左向きにしたい場合などに使えます。口パク・目パチ差分も同じ向きで反転されます。
  - `flip_y`: `true` にするとキャラクター画像を上下反転します。上下反転の確認や特殊演出に使えます。口パク・目パチ差分も同じ向きで反転されます。

- **ゆっくり的 口パク/目パチ（最小版）**: 音声の音量（RMS）に基づき、`mouth={close,half,open}` を切替。目パチは2–5秒間隔でランダムに閉じるスケジュール。差分PNGを `overlay:enable=between(t,...)` で重畳します（アセットが無い場合は自動で無効化）。

以下は、台本ファイルでのキャラクター設定の記述例です。

```yaml
lines:
  - text: "これから自己紹介の動画をはじめるのだ。"
    speaker_name: "copetan"
    characters: # キャラクター設定リスト
      - name: "copetan"
        expression: "whisper"
        position: {"x": "0", "y": "0"}
        scale: 0.8
        anchor: "bottom_center"
        flip_x: true
        flip_y: false
        visible: true
```

### キャラクター登場/退場アニメーション

- **DevContainer対応**: VSCode DevContainerをサポートしており、どこでも一貫した開発環境を簡単に構築できます。
- **外部設定ファイル**: `config.yaml`を通じて、キャッシュディレクトリや動画拡張子などのシステム設定を柔軟に変更できます。
- **タイムライン出力**: 動画の各シーンやセリフの開始時刻を記録し、YouTubeのチャプターなどに利用できるタイムラインファイルを自動生成します。出力形式はMarkdown (`.md`)、CSV (`.csv`)、またはその両方を選択できます。
- **字幕ファイル出力**: 焼き込み字幕とは別に、`.srt`または`.ass`形式の独立した字幕ファイルを動画と同時に出力します。これにより、YouTubeへのアップロードや、他言語への翻訳作業が容易になります。
- **キャラクターごとのデフォルト設定**: 台本ファイル内でキャラクターごとのデフォルト設定（話者ID、ピッチ、速度など）を定義できます。これにより、セリフごとの記述を簡潔にし、台本の可読性を向上させます。設定は「セリフごとの指定 > キャラクターごとのデフォルト > グローバルなデフォルト」の順に優先されます。

> 台本（YAML）の具体的な記述例は `scripts/script_cheatsheet.md` に集約しています。

---

## 🛠️ 技術スタック

- **言語**: Python 3.x
- **主要ライブラリ**:
    - `PyYAML`: YAML設定ファイルの読み込みと解析
    - `requests`: VOICEVOX APIとのHTTP通信
    - `httpx` / `tenacity`: VOICEVOX API呼び出しの非同期通信とリトライ制御
    - `pysubs2`: 字幕ファイルの生成
    - `Pillow`: 画像処理・背景透過
- **外部ツール**:
    - `FFmpeg`: 動画および音声の処理、結合、レンダリング
    - `VOICEVOX`: 音声合成エンジン (ローカルで実行されている必要があります)

---

## 🧱 プロジェクト構造

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
├── tools/                  # 補助ツール（rembg背景除去など）
├── zundamotion/            # メインアプリケーションのソースコード
│   ├── __init__.py
│   ├── cache.py            # キャッシュ管理 (`CacheManager` クラス)
│   ├── exceptions.py       # カスタム例外定義
│   ├── main.py             # エントリーポイント (`main` 関数)
│   ├── pipeline.py         # 動画生成パイプラインの定義 (`GenerationPipeline` クラス, `run_generation` 関数)
│   ├── components/         # パイプラインの各ステップで使用されるコンポーネント
│   │   ├── audio/          # 音声生成 (`AudioGenerator`) と VOICEVOX クライアント
│   │   ├── script/         # 設定統合の入口API（`load_script_and_config`）
│   │   ├── config/         # YAMLローダ/マージ/検証ユーティリティ
│   │   ├── subtitles/      # 字幕生成 (`SubtitleGenerator`, `SubtitlePNGRenderer`)
│   │   ├── video/          # 動画レンダリング (`VideoRenderer`, `OverlayMixin`)
│   │   │   ├── clip_renderer.py  # クリップ単位のレンダリングエントリ
│   │   │   └── clip/            # クリップ処理ヘルパー（立ち絵/顔アニメ）
│   │   │       ├── characters.py
│   │   │       └── face.py
│   │   └── pipeline_phases/    # 各フェーズ（components配下）
│   │       ├── audio_phase.py      # 音声生成フェーズ (`AudioPhase` クラス)
│   │       ├── bgm_phase.py        # BGM追加フェーズ (`BGMPhase` クラス)
│   │       ├── finalize_phase.py   # 最終化フェーズ (`FinalizePhase` クラス)
│   │       └── video_phase/        # 動画生成フェーズ (`VideoPhase` パッケージ)
│   │           ├── __init__.py
│   │           ├── character_tracker.py
│   │           ├── main.py          # `VideoPhase` クラス本体
│   │           └── scene_renderer.py
│   ├── reporting/          # レポート生成関連
│   │   └── voice_report_generator.py # VOICEVOX使用情報レポート生成
│   ├── templates/          # 設定テンプレート
│   │   └── config.yaml     # デフォルト設定テンプレート
│   └── utils/              # ユーティリティ関数
│       ├── ffmpeg_audio.py       # 音声処理ヘルパー
│       ├── ffmpeg_capabilities.py  # FFmpeg機能検出
│       ├── ffmpeg_ops.py         # 映像処理ヘルパー
│       ├── ffmpeg_params.py  # エンコード設定データクラス
│       ├── ffmpeg_hw.py      # ハードウェアフィルタ制御
│       ├── ffmpeg_probe.py   # ffprobeラッパー
│       ├── ffmpeg_runner.py  # FFmpeg実行ヘルパー
│       └── logger.py         # ロギングユーティリティ
└── requirements.txt        # Pythonの依存関係
```

### プラグイン設定の最小例

- CLI: `python -m zundamotion.main --plugin-path ./my_plugins --plugin-allow my-blur`
- config.yaml:
  ```yaml
  plugins:
    enabled: true
    paths: ["./plugins"]
    allow: []   # 空なら全許可、ID指定で絞り込み
    deny: []    # 危険/不要なIDを明示的に遮断
  ```
組み込みプラグインはキャッシュ済みレジストリから即時読み込まれ、追加パスを指定しない場合はスキャンも最小限になります。

### ユーザー作成プラグインのサンプル

- [ユーザーサンプルプラグイン実装ガイド（overlay shake 編）](./docs/user_simple_plugin.md) 参照

---

## 📦 セットアップ手順

### 1. 必要ツールのインストール
- [Docker](https://www.docker.com/get-started/)
- [FFmpeg](https://ffmpeg.org/download.html) (システムにインストールされている必要があります)
  - CLI起動時に`ffmpeg`/`ffprobe`のバージョンを自動検証し、FFmpeg 7.x未満や未インストールの場合は実行前にエラーで停止します。
- [VS Code](https://code.visualstudio.com/)
- [Remote - Containers 拡張機能](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers) (VS Code)

### 2. リポジトリのクローン
```bash
git clone https://github.com/c-a-p-engineer/zundamotion.git
cd zundamotion
```

### 3. DevContainerの起動
VS Codeでプロジェクトを開き、プロンプトが表示されたら「Reopen in Container」を選択します。これにより、必要な依存関係が自動的にインストールされ、開発環境が構築されます。

#### GPUを使う場合（DevContainer）
- `ZUNDA_DOCKER=Dockerfile.gpu` を指定して DevContainer を起動してください（例: `.env` に `ZUNDA_DOCKER=Dockerfile.gpu` を追加）。
- ホスト側で NVIDIA Container Toolkit と GPU ドライバが有効である必要があります。
- コンテナ内で `nvidia-smi` と `ffmpeg -filters` に `overlay_cuda`/`scale_cuda` が出ることを確認してください。

#### Docker ログで実行ログを追う場合（DevContainer）
- `docker compose exec app ...` で起動したプロセスは `docker logs` / `docker compose logs` には流れません。
- Docker ログで追いたい場合は、前面実行用の `render` サービスを使ってください。

```bash
ZUNDAMOTION_COMMAND='python -m zundamotion.main scripts/sample.yaml -o output/sample.mp4 --no-cache --hw-encoder cpu --log-kv' \
docker compose --env-file .devcontainer/.env -f .devcontainer/docker-compose.yml --profile runner up --build render
```

別ターミナルで追う場合:

```bash
docker compose --env-file .devcontainer/.env -f .devcontainer/docker-compose.yml logs -f render
```

### 4. Codex Cloud 環境向けセットアップ（CPUエンコード前提）

Codex Cloud 上での実行を想定した最小セットアップ例です。Dockerfileに合わせた基本ツール、IPAゴシック、FFmpeg（CPU版）を導入します。

```bash
set -euo pipefail

# =========================================================
# 基本ツール（Dockerfile準拠）
# =========================================================
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  curl git xz-utils ca-certificates \
  gnupg2 software-properties-common

# =========================================================
# 日本語フォント（IPAゴシック）
# =========================================================
sudo apt-get install -y --no-install-recommends \
  fonts-ipafont-gothic

# =========================================================
# Python pip 周り
# ※ Python 3.13 は Codex Environment 側で指定済み前提
# =========================================================
python -m ensurepip --upgrade || true
python -m pip install --no-cache-dir --upgrade pip setuptools wheel

# =========================================================
# Python パッケージ
# =========================================================
python -m pip install --no-cache-dir -r requirements.txt

# =========================================================
# FFmpeg（CPU版 prebuilt / BtbN）
# =========================================================
FFMPEG_URL="https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-linux64-gpl-shared.tar.xz"

curl -L -o /tmp/ffmpeg.tar.xz "$FFMPEG_URL"

sudo mkdir -p /opt/ffmpeg
sudo tar -xJf /tmp/ffmpeg.tar.xz -C /opt/ffmpeg --strip-components=1

sudo ln -sf /opt/ffmpeg/bin/ffmpeg  /usr/local/bin/ffmpeg
sudo ln -sf /opt/ffmpeg/bin/ffprobe /usr/local/bin/ffprobe

rm -f /tmp/ffmpeg.tar.xz

# =========================================================
# ライブラリパス設定（agent実行時にも有効化）
# =========================================================
echo "/opt/ffmpeg/lib" | sudo tee /etc/ld.so.conf.d/ffmpeg.conf >/dev/null
sudo ldconfig
echo 'export LD_LIBRARY_PATH="/opt/ffmpeg/lib:${LD_LIBRARY_PATH:-}"' >> ~/.bashrc

# =========================================================
# 動作確認（Dockerfileと同等）
# =========================================================
python --version
pip --version

ffmpeg -hide_banner -encoders | grep -E 'libx264|libx265'
ffmpeg -hide_banner -filters | grep -E 'overlay_opencl|scale_opencl' || true
```

Codex Cloud 上でのテスト用コマンド（CPUエンコード + 音声なし）:

```bash
DISABLE_HWENC=1 python -m zundamotion.main scripts/sample.yaml \
  -o output/sample.mp4 --no-cache --no-voice
```

---

## 速度優先で回すとき

- `--quality speed`
- `--jobs auto`
- `--hw-encoder gpu`

この 3 つを併用すると、字幕 PNG の事前生成と GPU エンコードを活かしやすくなります。

長尺動画で字幕が多い場合は、最終字幕合成だけ自動で CPU フィルタにフォールバックします。既定では `video.max_cuda_subtitle_overlays: 8` 相当のしきい値で切り替わり、NVENC 自体はそのまま使います。

長時間の FFmpeg 実行中は、15 秒ごとに進捗ログが出ます。ログには `elapsed` に加えて、出力ファイルサイズから見積もった `eta` の目安も含まれます。厳密値ではありませんが、少なくとも「止まっているのか、まだ進んでいるのか」は判断しやすくなります。

字幕付き完成版は、指定した出力パスそのものに保存されます。字幕前の最終動画を保存できる場合は、同じ場所に `*_no_sub.mp4` を追加で出力します。

---

## 🧩 Git submoduleとして使う（利用側プロジェクトから）

このリポジトリを **動画生成エンジン** として利用側プロジェクトに取り込みたい場合は、`git submodule` + `pip install -e` を推奨します。
詳細版は `docs/guides/submodule.md` を参照してください。

`zundamotion-video-workspace` のように、親リポジトリ直下に `assets/` `scripts/` `output/` を置き、`vendor/zundamotion` をサブモジュール化した Dev Container 運用もできます。`.devcontainer` の構成例を含めた手順は [docs/guides/submodule.md](./docs/guides/submodule.md) の「zundamotion-video-workspace のような開発環境を作る」を参照してください。

### 1) submodule 追加（利用側リポジトリで実行）

```bash
git submodule add <GIT_URL> vendor/zundamotion
git submodule update --init --recursive
```

### 2) インストール（推奨: editable）

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e vendor/zundamotion
```

フォールバック（editableを使わない場合）:

```bash
pip install -r vendor/zundamotion/requirements.txt
```

### 3) 実行例

利用側プロジェクトを基準に実行（相対パスは利用側リポジトリ基準）:

```bash
zundamotion path/to/script.yaml -o output/out.mp4
```

サブモジュール同梱のサンプル台本を試す（相対パス基準をサブモジュールに切り替え）:

```bash
zundamotion scripts/sample.yaml --project-root vendor/zundamotion
```

キャラクター画像の左右・上下反転を確認するサンプル:

```bash
zundamotion scripts/sample_character_flip.yaml --project-root vendor/zundamotion
```

### 相対パスの基準（`--project-root` / `ZUNDAMOTION_PROJECT_ROOT`）

- 未指定: 実行時のカレントディレクトリ基準
- 指定: `--project-root`（または `ZUNDAMOTION_PROJECT_ROOT`）を基準に `assets/`・`plugins/`・`output/` 等の相対パスを解決します

---

## 🧩 開発者向け: コード分割とAI向けガイド（要点）

- ファイル規模の目安: 1ファイル200–400行（最大500行）
- 関数規模の目安: 20–40行（最大80行）、深い分岐はヘルパー化
- 責務分離: ロード/マージ/検証/実行を分け、テスト容易性と保守性を向上
- 本プロジェクトの適用例:
  - `components/script/loader.py`: エントリAPI（`load_script_and_config`）
  - `components/config/io.py`: YAML読み込みとエラーハンドリング
  - `components/config/merge.py`: ディープマージ（override優先）
  - `components/config/validate.py`: スキーマ/パス/数値範囲などの検証

AI / Codex 向けの作業ルールは [AGENTS.md](AGENTS.md)、ドキュメント全体の入口は [docs/README.md](docs/README.md) を参照してください。

---

## 🎵 BGM設定

BGMは、グローバル設定またはシーンごとに設定できます。シーンごとの設定はグローバル設定を上書きします。

### グローバルBGM設定 (config.yaml)

`zundamotion/templates/config.yaml` またはカスタム設定ファイルで、動画全体に適用されるデフォルトのBGMを設定できます。

```yaml
# BGM settings
bgm:
  path: "assets/bgm/default_bgm.wav" # デフォルトのBGMファイルパス
  volume: 0.3                       # デフォルトのBGM音量 (0.0-1.0)
  start_time: 0.0                   # デフォルトのBGM開始時間 (秒)
  fade_in_duration: 1.0             # デフォルトのフェードイン時間 (秒)
  fade_out_duration: 1.0            # デフォルトのフェードアウト時間 (秒)
```

### シーンごとのBGM設定 (scripts/your_script.yaml)

各シーンで個別のBGMを設定できます。これにより、シーンごとに異なる雰囲気を作り出すことが可能です。

```yaml
scenes:
  - id: intro
    bg: "assets/bg/sample_video.mp4"    # シーン背景 (動画ファイル)
    bgm:                                # BGM設定
      path: "assets/bgm/intro.wav"      # BGMファイルパス
      volume: 0.1                       # BGM音量 (0.0-1.0, オプション)
      fade_in_duration: 2.0             # フェードインの長さ (秒, オプション)
      fade_out_duration: 1.5            # フェードアウトの長さ (秒, オプション)
    lines:
      - text: "こんにちは！こぴぺたんです。"

### 🔤 読み分け（音声と字幕の分離）

音声で読む内容と字幕に表示する内容を分けられます。例えば「本気（ほんき）」と書いて音声では「マジ」と読ませたい場合:

```yaml
scenes:
  - id: example
    bg: "assets/bg/room.png"
    lines:
      - speaker_name: copetan
        text: "本気"            # 字幕に表示する文字列（タイムラインもこちらを使用）
        reading: "マジ"         # 音声合成で読む文字列（省略時は text を使用）
        # 必要に応じて字幕だけ個別に差し替えたい場合:
        # subtitle_text: "本気"    # 指定が無ければ text が使われます
```

- `reading`: VOICEVOX 合成用テキスト。キャッシュキーにも含まれます。
- `text` / `subtitle_text`: 字幕PNG生成・タイムライン表記に使用。`subtitle_text` があればそれを、無ければ `text` を使用します。
- 字幕内で任意に改行したい場合は `\n`（YAML では `"行1\\n行2"`）や `<br>` を差し込むと、PNG描画・SRT/ASS ファイルの両方で複数行に分割されます。

### 🗣️ 同時発話（複数キャラを1行で）

1つの行で複数キャラクターに同時に喋らせたい場合は、`voice_layers` にキャラクターごとのボイス設定を並べます。
`defaults.characters.<name>` に定義した `speaker_id` や `speed` が各レイヤーへ自動で適用され、必要な項目だけを上書きすればOKです。

```yaml
lines:
  - text: "二人揃って○○です！"
    voice_layers:
      - speaker_name: copetan
        text: "二人揃って○○です！"
      - speaker_name: engy
        text: "二人揃って○○です！"
        volume: 0.9       # 省略時は1.0
        start_time: 0.0   # 秒単位、ずらしたいときだけ指定
```

各レイヤーは `reading` / `speed` / `pitch` などの調整も個別に指定可能です。生成された音声は自動的にミックスされ、字幕表示は行の `text`（または `subtitle_text`）が使用されます。

> 📄 フルサンプル: [`scripts/sample_voice_layers.yaml`](scripts/sample_voice_layers.yaml)

### 📝 字幕スタイル調整

`subtitle` セクション（既定は `zundamotion/templates/config.yaml`）で、行間や整列方法を細かく調整できます。

- `line_spacing_multiplier`: 行送りをフォントの自然な高さに対して乗算で調整します（既定 `1.15`）。
- `line_spacing_offset_per_line`: 行ごとの固定ピクセル加算（既定 `0`、互換用）。
- `text_align`: 字幕テキストの揃え位置。`left` / `center` / `right` を指定できます。
- `max_chars_per_line: auto`: `max_pixel_width` と実フォント幅から、字幕ごとに折り返し文字数を自動推定します。日本語の空白なし字幕向けです。
- `subtitle.background.show`: 字幕ボックスの表示/非表示を切り替えます。`color` と `opacity` で色と透過率を調整できます。
- 字幕の描画方式は内部で自動選択されます。背景色・透過率・表示/非表示だけの軽量な字幕ボックスは `ASS/libass`、角丸・枠線・背景画像・字幕エフェクトを使う装飾付き字幕は `PNG` になります。
- `ASS` の背景ボックスは `BorderStyle=3` 仕様により独立した枠線色を持てません。枠線や角丸を指定した場合は、自動的に `PNG` 描画へ切り替わります。
- 確認用サンプル: [`scripts/sample_subtitle_styles.yaml`](scripts/sample_subtitle_styles.yaml)

#### インライン読みマークアップ（1行内で複数箇所）
1行の中で箇所ごとに読みを変えるには、以下のマークアップが使えます。

- 角括弧: `[表示|読み]`
- 波括弧: `表示{読み}`

例: `それ[本気|ホンキ]？[本気|マジ]？`

- 音声は「それホンキ？マジ？」と読みます。
- 字幕の表示は `subtitle.reading_display` で制御します。
  - `none`（既定）: 「それ本気？本気？」
  - `paren`: 「それ本気（ホンキ）？本気（マジ）？」
```

- `path`: BGMファイルのパス。
- `volume`: BGMの音量（0.0から1.0の範囲）。
- `start_time`: BGMが動画のどの時点から開始するか（秒）。
- `fade_in_duration`: BGMのフェードインの長さ（秒）。
- `fade_out_duration`: BGMのフェードアウトの長さ（秒）。

### 🎨 前景オーバーレイ設定

`fg_overlays` に透過動画やクロマキー素材を指定すると、シーン全体や各セリフにエフェクトを重ねられます。字幕は最終段階で合成されるため、常に前景オーバーレイより手前に表示されます。

```yaml
scenes:
  - id: intro
    bg: "assets/bg/room.png"
    fg_overlays:
      - id: rain
        src: "assets/overlay/sakura_bg_black.mp4"
        mode: chroma
        chroma:
          key_color: "#000000"
          similarity: 0.1
          blend: 0.0
        position: {x: 0, y: 0}
        scale: {w: 1920, h: 1080, keep_aspect: true}
        timing:
          start: 0.0
          loop: true
    lines:
      - text: "背景に桜を合成"
      - text: "このセリフだけ桜を重ねる"
        fg_overlays:
          - id: petals
            src: "assets/overlay/sakura_bg_black.mp4"
            mode: chroma
            chroma:
              key_color: "#000000"
              similarity: 0.1
              blend: 0.0
            timing:
              start: 0.0
              duration: 2.0
```

#### fg_overlays オプション一覧

前景オーバーレイは、シーンレベル（`scene.fg_overlays`）と行レベル（`line.fg_overlays`）の両方に記述できます。行レベルはその行クリップのみに適用、シーンレベルはシーン内の全クリップを連結した後に適用されます。複数指定した場合はリストの上から順に重ねられ、後に書かれたものほど前面になります。字幕はすべての前景オーバーレイ適用後に最前面で合成されます。

- src: オーバーレイ素材のパス（必須, 画像/動画）。実在ファイルのみ可。
- id: 任意の識別子（省略可, 既定は `fg_{index}`）。
- mode: 合成方法（`overlay` | `blend` | `chroma`）。既定は `overlay`。
- fps: オーバーレイのフレームレートを整数で変換（省略可）。
- opacity: 不透明度（0.0–1.0, 省略可, 既定 1.0）。
- position: 配置座標。`{x: number, y: number}`（省略可, 既定 `{x:0,y:0}`）。座標はフレーム左上基準のピクセル値。
- scale: スケール設定。`{w: number, h: number, keep_aspect: bool}`（すべて省略可）。
  - w/h: 目標解像度（ピクセル, 正の数）。
  - keep_aspect: アスペクト保持（既定 false）。true の場合は `force_original_aspect_ratio=decrease` + 余白パディングでレターボックス化。
- timing: 表示タイミング。`{start: number>=0, duration: number>0?, loop: bool?}`
  - start: シーン/行の先頭からの開始時刻（秒, 既定 0.0）。
  - duration: 表示長（秒, 省略時は `start` 以降ずっと有効）。
  - loop: ループ再生（既定 false）。素材が短い場合でもループして期間を満たします。

モード別の追加オプション

- mode=blend: ブレンド合成（素材にアルファが無い場合などに便利）
  - blend_mode: `screen` | `add` | `multiply` | `lighten`（必須）。

- mode=chroma: クロマキー合成（単色背景の除去）
  - chroma.key_color: キーカラー（例 `"#00FF00"`）。
  - chroma.similarity: 許容差（0.0–1.0, 既定 0.1）。
  - chroma.blend: エッジの馴染ませ（0.0–1.0, 既定 0.0）。

注意事項

- オーバーレイ素材の音声はミックスされません（映像のみ使用）。
- 大きな解像度/多数レイヤーはCPU負荷が高くなります。RGBA（透過）を含むオーバーレイは基本的にCPUフィルタで合成します。
- `scale.keep_aspect: true` は縦横いずれかを目標に合わせ、余白を透過でパディングします。
- `loop: true` を指定しても、出力の長さはベース動画の長さに揃います。

最小構成の例（全シーン）

```yaml
scenes:
  - id: s1
    bg: assets/bg/room.png
    fg_overlays:
      - id: logo
        src: assets/overlay/logo.png
        mode: overlay
        position: {x: 20, y: 20}
        opacity: 0.9
        timing: {start: 0.0}
```

行ごとの例（特定セリフの2秒間だけ適用）

```yaml
lines:
  - text: "このセリフだけ桜を重ねる"
    fg_overlays:
      - id: petals
        src: assets/overlay/sakura_bg_black.mp4
        mode: chroma
        chroma: {key_color: "#000000", similarity: 0.1, blend: 0.0}
        scale: {w: 1920, h: 1080, keep_aspect: true}
        timing: {start: 0.0, duration: 2.0}
```

#### fg_overlays チートシート

最小テンプレート（そのままコピペして値を調整）

```yaml
fg_overlays:
  - id: name            # 任意
    src: path/to/asset  # 必須（画像/動画）
    mode: overlay       # overlay | blend | chroma（既定 overlay）
    opacity: 1.0        # 0.0–1.0（省略可）
    fps: 30             # 整数（省略可）
    position: {x: 0, y: 0}
    scale: {w: 1920, h: 1080, keep_aspect: false}
    timing: {start: 0.0, duration: 2.0, loop: false}
```

よく使うレシピ

```yaml
# 1) ロゴ画像を左上に常時表示
fg_overlays:
  - src: assets/overlay/logo.png
    position: {x: 16, y: 16}

# 2) クロマキー（黒背景を抜いて全画面）
  - src: assets/overlay/sakura_bg_black.mp4
    mode: chroma
    chroma: {key_color: "#000000", similarity: 0.1, blend: 0.0}
    scale: {w: 1920, h: 1080, keep_aspect: true}
    timing: {start: 0.0, loop: true}

# 3) ブレンド（スクリーン合成）で2秒だけ
  - src: assets/overlay/glow.mp4
    mode: blend
    blend_mode: screen   # screen | add | multiply | lighten
    timing: {start: 1.0, duration: 2.0}

# 4) 行だけに2秒適用（line配下に置く）
lines:
  - text: "このセリフにだけ重ねる"
    fg_overlays:
      - src: assets/overlay/effect.mp4
        timing: {start: 0.0, duration: 2.0}
```

デフォルトと制約（検証ルール）

- mode: 既定 `overlay`（許可: `overlay|blend|chroma`）
- blend_mode: `screen|add|multiply|lighten`（mode=blend時 必須）
- chroma: `key_color("#RRGGBB")`, `similarity 0.0–1.0(既定0.1)`, `blend 0.0–1.0(既定0.0)`
- opacity: `0.0–1.0`、省略時 1.0
- position.x/y: 数値（px）、省略時 0
- scale.w/h: 正の数、`keep_aspect` は bool（省略可）
- timing.start: 0 以上（既定 0.0）
- timing.duration: 正の数（省略可＝以後ずっと）
- timing.loop: bool（既定 false）
- fps: 正の整数（省略可）

ヒント

- 複数のオーバーレイは記載順に合成され、後のものほど前面になります。
- 行レベルの `fg_overlays` はその行クリップだけに適用。シーンレベルはシーン連結後にまとめて適用されます。
- 字幕は全オーバーレイ適用後に最前面で合成されます。
- `loop: true` を指定しても出力尺はベース動画長に自動で揃います。

---

## 🔊 効果音設定

効果音は、各セリフ（`line`）に紐付けて設定できます。これにより、セリフの再生と同時に、またはセリフの開始からの相対的な時間で効果音を挿入することが可能です。

```yaml
lines:
  - text: "こんにちは！こぴぺたんです。"
    speaker_id: 3
    sound_effects: # セリフと同時に再生する効果音
      - path: "assets/se/rap_fanfare.mp3"
        start_time: 3.0 # セリフ開始から3.0秒後に再生
        volume: 0.5

  - text: "" # セリフなしで効果音のみを再生する場合
    sound_effects:
      - path: "assets/se/rap_fanfare.mp3"
        start_time: 0.0 # このlineが開始されると同時に再生
        volume: 0.7
```

- `path`: 効果音ファイルのパス。
- `start_time`: 効果音がセリフの開始から何秒後に再生を開始するかを指定します。デフォルトは `0.0` で、セリフと同時に再生されます。
- `volume`: 効果音の音量（0.0から1.0の範囲）。デフォルトは `1.0` です。

---

### AIベースでの背景除去（rembg）

写真や複雑な背景では、AIベースの除去が高精度です。

- ファイル: `tools/remove_bg_ai.py`
- 依存関係: `pip install rembg`（GPU利用時は `onnxruntime-gpu` を別途インストール）

使い方:

```bash
# 一括処理（デフォルトモデル: isnet-general-use）
python tools/remove_bg_ai.py --input ./path/to/input_images --output ./path/to/output_png

# サブフォルダも含めて処理
python tools/remove_bg_ai.py --input ./in --output ./out --recursive

# モデル切替（アニメ調に強い）
python tools/remove_bg_ai.py --input ./in --output ./out --model isnet-anime

# CPU/GPUを強制（GPUが不可ならCPUにフォールバック）
python tools/remove_bg_ai.py --input ./in --output ./out --force-cpu
python tools/remove_bg_ai.py --input ./in --output ./out --force-gpu
```

モジュールとしても利用でき、`remove_background_in_directory` 関数を使ってプログラムから直接ディレクトリを処理できます。

備考:
- 起動時に利用可能なONNX Runtimeプロバイダ情報を表示します。
- 出力は常に透過PNGです。
- GPU環境では `pip install onnxruntime-gpu` で高速化できます。


## 🎬 画像・動画の挿入

セリフ中に、指定した画像や動画を画面に挿入することができます。これにより、参考資料を提示したり、視覚的なエフェクトを追加したりすることが可能です。

```yaml
lines:
  - text: "（画像を右下に小さく表示するのだ）"
    speaker_id: 3
    insert:
      path: "assets/bg/room.png"      # 挿入する画像・動画のパス
      duration: 3.0                   # 表示時間 (秒, 画像の場合のみ有効)
      scale: 0.3                      # 拡大縮小率 (オプション)
      anchor: "bottom_right"          # アンカーポイント (オプション)
      position: {"x": "-20", "y": "-20"} # 位置オフセット (オプション)

  - text: "（動画を再生するのだ！）"
    speaker_id: 3
    insert:
      path: "assets/bg/countdown.mp4" # 挿入する動画
      scale: 0.8
      anchor: "middle_center"
      position: {"x": "20", "y": "20"}
      volume: 0.2                     # 挿入動画の音量 (オプション)
```

- `path`: 挿入する画像または動画ファイルのパス。
- `duration`: 画像を表示する時間（秒）。動画の場合は無視されます。
- `scale`: 画像・動画の拡大縮小率。
- `anchor`: 配置の基準点。キャラクター配置と同様のアンカーポイントが利用可能です。
- `position`: アンカーポイントからの相対的な位置オフセット（x, y座標）。
- `volume`: 挿入する動画の音量（0.0から1.0の範囲）。画像の場合は無視されます。

---

## 🖼️ キャラクター画像の設定

キャラクター画像は、`assets/characters/` ディレクトリ以下に、キャラクター名と表情ごとのフォルダを用意して配置します。
各表情フォルダには少なくとも `base.png` を置き、必要に応じて `eyes/` や `mouth/` の差分を追加します（後述）。

**例:**
- こぴぺたんの通常の表情: `assets/characters/copetan/default/base.png`
- こぴぺたんの笑顔の表情: `assets/characters/copetan/smile/base.png`

もし指定された表情の画像ファイルが存在しない場合、システムは自動的に `assets/characters/{キャラクター名}/default/base.png` を探してフォールバックします。

### Copetan 表情セット

Copetan は 8 種類の表情を `assets/characters/copetan/<expression>/` に配置しています（`base.png`, `eyes/`, `mouth/` をセットで管理）。どの表情がどのフォルダか分かるよう、手元のサンプルを一覧化しました。

| 表情ID | ディレクトリ | ニュアンス | 備考 |
| --- | --- | --- | --- |
| `default` | `assets/characters/copetan/default/` | きょとんとした通常ポーズ | 迷った時のフォールバック表情 |
| `smile` | `assets/characters/copetan/smile/` | 口角を上げた素直な笑顔 | 喜び・挨拶シーン向け |
| `angry` | `assets/characters/copetan/angry/` | 眉を吊り上げたぷんすか顔 | グーの手で抗議中 |
| `exasperated` | `assets/characters/copetan/exasperated/` | 両手を広げた呆れ顔 | 旧ディレクトリ名 `deadpan` から改名 |
| `embarrassed_blush` | `assets/characters/copetan/embarrassed_blush/` | 顔を真っ赤にしてしどろもどろ | 照れ・動揺の場面 |
| `flustered_coldsweat` | `assets/characters/copetan/flustered_coldsweat/` | 冷や汗をかいた焦り顔 | 緊張・想定外の状況向け |
| `sad` | `assets/characters/copetan/sad/` | しょんぼり落ち込む表情 | 涙目で頼りない印象 |
| `smug` | `assets/characters/copetan/smug/` | 得意げなニヤリ顔 | 口元に余裕の笑み |

> `exasperated` 以外の表情名はフォルダ命名と YAML の表情 ID が一致しています。台本内で `expression:` に上記 ID を指定することで、該当フォルダの差分素材が読み込まれます。
そのため、各キャラクターには少なくとも `default/base.png` を用意しておくことを推奨します。

### 口パク/目パチ用の差分PNG（任意）

「ゆっくり」的な最小アニメーションに対応するため、以下の差分PNGを用意すると、口パク・目パチが自動で適用されます（存在しない場合は無効化）。

- 口パク: `assets/characters/<name>/mouth/{close,half,open}.png`
- 目パチ: `assets/characters/<name>/eyes/{open,close}.png`

差分PNGは、元の立ち絵と同一キャンバスサイズ・座標系で作成してください（透明背景の「差分」レイヤ）。キャラクターの拡大率・配置に追従し、音声に同期して `half/open` を切替、`close` はベースとして常時合成、`half`/`open` が上から被さる構成です。目は `open` を常時合成し、`close` を点滅区間のみ上書きします。

`characters[].flip_x: true` または `characters[].flip_y: true` を指定した場合、ベース立ち絵に加えて口パク・目パチ差分も同じ向きに反転されます。反転用の別素材を追加する必要はありません。

設定（`config.yaml` またはスクリプトの `video:` セクション）

```yaml
video:
  fps: 30
  face_anim:
    mouth_fps: 15           # 口パク判定のサンプリングFPS
    mouth_thr_half: 0.2     # 半開き閾値（RMSのmax比）
    mouth_thr_open: 0.5     # 全開閾値（RMSのmax比）
    blink_min_interval: 2.0 # 目パチの最小間隔（秒）
    blink_max_interval: 5.0 # 目パチの最大間隔（秒）
    blink_close_frames: 2   # 瞬きの閉眼フレーム数（動画FPS基準）
```

対象キャラクターは、各セリフの `speaker_name`（未指定時は最初の `visible: true` のキャラ）です。

### 背景フィットモードと余白制御

`video.background_fit` では背景のリサイズ方法を指定できます。`stretch`（従来の全画面伸長）のほかに、縦横比を維持したまま余白を残す
`contain`、逆に余白が出ないよう中央でクロップする `cover`、単軸優先の `fit_width` / `fit_height` を選べます。`contain` と単軸フィッ
トでは `background.fill_color` が余白色として使われ、`background.anchor` と `background.position` で余白やクロップ位置を調整でき
ます。値はシーンや行ごとに `background:` ブロックで上書き可能です。

```yaml
video:
  width: 1080
  height: 1920
  background_fit: contain

background:
  default: assets/bg/street.png
  fill_color: "#0F172A"
  anchor: middle_center

scenes:
  - id: skyline
    lines:
      - text: "縦長でも背景を余白付きで表示"
      - text: "一部シーンだけトリミング"
        background:
          fit: cover
          anchor: bottom_center
          position: {y: -160}
```

上記の例では、デフォルトでレターボックス付きの `contain` を使い、特定の行だけ `cover` でクロップ位置を下寄せに切り替えています。
`scripts/sample_vertical.yaml` に縦長キャンバス向けの詳細なサンプルを用意しました。

### 背景の継続指定

`defaults.background_persist` またはシーン単位の `background_persist` で、行ごとの背景指定を省略したときの扱いを切り替えられます。

- `false`: 背景を継続しません。`background.path` を省略した行は、シーンの `bg`、またはルート `background.default` を使います。
- `true`: 背景を継続します。`background.path` を指定した行で背景を切り替え、以降の省略行はその背景を使い続けます。

長いスライド解説では `true` にすると、背景が切り替わる行だけを書けばよくなります。行ごとに同じ `background.path` を繰り返す必要はありません。

```yaml
defaults:
  background_persist: true

scenes:
  - id: lesson
    bg: assets/slides/01-cover.png
    lines:
      - text: "最初は表紙です。"
      - text: "次のスライドへ切り替えます。"
        background:
          path: assets/slides/02-topic.png
      - text: "この行も 02-topic.png を使います。"
      - text: "ここでまとめスライドへ切り替えます。"
        background:
          path: assets/slides/03-summary.png
```

`background_persist: false` の場合、3 行目は `02-topic.png` ではなくシーンの `bg` に戻ります。

#### 差分PNG配置ガイド（具体例）

- 準備するファイル（こぴぺたんの例）:
  - `assets/characters/copetan/default/base.png`（既存の立ち絵）
  - `assets/characters/copetan/default/mouth/close.png`
  - `assets/characters/copetan/default/mouth/half.png`
  - `assets/characters/copetan/default/mouth/open.png`
  - `assets/characters/copetan/default/eyes/open.png`
  - `assets/characters/copetan/default/eyes/close.png`
- ファイル仕様:
  - キャンバス: 立ち絵 `default/base.png` と同じ幅・高さ。
  - 背景: 透明（PNGのアルファ）。
  - 描画範囲: 口/目の差分部分のみ描画し、それ以外は完全に透明にします。
  - 位置合わせ: `default/base.png` に対してピクセル単位で一致させてください（同一座標系）。
  - ネーミング: 上記の固定ファイル名のみを参照します。大文字/拡張子違いは不可。
- 動作メモ:
  - 口は `close` が常時、`half`/`open` は音量しきい値を満たす時間だけ重なります。
  - 目は `open` が常時、`close` はランダムな点滅時間だけ重なります。
  - 差分PNGが存在しない場合は、その要素（口 or 目）は自動的に無効化されます（既存の静止立ち絵のみ）。

---

## 🗣 VOICEVOX エンジン

DevContainer起動時にDocker ComposeによってVOICEVOXエンジンが自動的に起動し、コンテナ内からは `voicevox:50021` で利用可能です。
ローカル環境（コンテナ外）からアクセスする場合は、通常 `http://127.0.0.1:50021` を使用してください。
必要に応じて環境変数 `VOICEVOX_URL` で接続先を上書きできます（例: DevContainer内では `http://voicevox:50021`）。

---

## 🧪 動作確認

Zundamotionは、YAML台本から最終的な動画ファイルを生成することを目的としています。ここでは、その基本的なワークフローを説明します。

#### 1. 動画の生成
台本に指定された情報（音声、字幕、背景、キャラクター素材など）を元に、`.mp4`動画を生成します。このプロセスでは、VOICEVOXによる音声合成、字幕生成、FFmpegによる動画合成がすべて一括で行われます。実行中、CLIに進捗バーと残り時間が表示されます。
```bash
python -m zundamotion.main scripts/sample.yaml
```
機械可読なJSON形式でログを出力したい場合は、`--log-json`オプションを使用します。
```bash
python -m zundamotion.main scripts/sample.yaml --log-json
```
人間が読みやすいKey-Value形式でログを出力したい場合は、`--log-kv`オプションを使用します。
```bash
python -m zundamotion.main scripts/sample.yaml --log-kv
```
出力ファイルのパスを指定する場合は、`-o`または`--output`オプションを使用します。未指定の場合は `output/final_YYYYMMDD_HHMMSS.mp4` の形式で自動命名されます（例: `output/final_20250911_143015.mp4`）。
```bash
python -m zundamotion.main scripts/sample.yaml -o output/my_video.mp4
```
キャッシュを無効にしてすべての中間ファイルを再生成したい場合は、`--no-cache`オプションを使用します。
```bash
python -m zundamotion.main scripts/sample.yaml --no-cache
```
すべての中間ファイルを再生成し、キャッシュを更新したい場合は、`--cache-refresh`オプションを使用します。
```bash
python -m zundamotion.main scripts/sample.yaml --cache-refresh
```

並列レンダリングジョブ数を指定したい場合は、`--jobs`オプションを使用します。`auto`を指定するとCPUコア数を自動検出し、最適なジョブ数を設定します。
```bash
python -m zundamotion.main scripts/sample.yaml --jobs auto
```
特定のジョブ数を指定することも可能です（例: 4コアを使用する場合）。
```bash
python -m zundamotion.main scripts/sample.yaml --jobs 4
```

ハードウェアエンコーダーを指定したい場合は、`--hw-encoder`オプションを使用します。`auto`を指定すると利用可能な場合にGPUを使用し、`gpu`はGPUを強制（CPUフォールバックあり）、`cpu`はCPUを強制します。
```bash
python -m zundamotion.main scripts/sample.yaml --hw-encoder gpu
```

### Docker GPU/NVENC チェック

GPUを使う場合、コンテナ内で以下を確認してください。

```bash
nvidia-smi
ldconfig -p | rg libnvidia-encode
ffmpeg -hide_banner -encoders | rg nvenc
```

`libnvidia-encode.so.1` が見つからない場合は、Docker起動時に `--gpus all` と `NVIDIA_DRIVER_CAPABILITIES=compute,utility,video`（または `all`）を指定して、ホスト側のNVENCライブラリをコンテナへマウントしてください。

エンコード品質を指定したい場合は、`--quality`オプションを使用します。`speed`, `balanced`, `quality`から選択できます。
```bash
python -m zundamotion.main scripts/sample.yaml --quality quality
```

最終的な連結を`-c copy`のみに強制し、再エンコードが必要な場合は失敗させたい場合は、`--final-copy-only`オプションを使用します。
```bash
python -m zundamotion.main scripts/sample.yaml --final-copy-only
```

タイムライン出力を有効にするには、`--timeline`オプションを使用します。フォーマットを指定しない場合、デフォルトでMarkdown形式で出力されます。
```bash
python -m zundamotion.main scripts/sample.yaml --timeline
```
出力フォーマットをCSVに指定する場合：
```bash
python -m zundamotion.main scripts/sample.yaml --timeline csv
```
両方のフォーマットで出力する場合：
```bash
python -m zundamotion.main scripts/sample.yaml --timeline both
```
タイムライン出力を無効にするには、`--no-timeline`オプションを使用します。
```bash
python -m zundamotion.main scripts/sample.yaml --no-timeline
```

字幕ファイルの出力も同様に制御できます。
```bash
# SRT形式で字幕ファイルを出力（デフォルト）
python -m zundamotion.main scripts/sample.yaml --subtitle-file

# ASS形式で字幕ファイルを出力
python -m zundamotion.main scripts/sample.yaml --subtitle-file ass

# 字幕ファイル出力を無効化
python -m zundamotion.main scripts/sample.yaml --no-subtitle-file
```

キャラクターごとのデフォルト設定は、台本ファイル内の`defaults`セクションで定義します。音声設定だけでなく、字幕の色などもキャラクターに紐付けて設定できます。

行ごとの字幕位置や装飾を上書きしたい場合は、`say.subtitle` 配下に設定してください。`say` 直下の `x` / `y` はキャラクターや他要素の座標と競合するため、字幕用には使いません。

```yaml
defaults:
  characters:
    copetan:
      speaker_id: 3
      pitch: 0.1
      speed: 1.1
      subtitle:
        font_color: "#90EE90"
        stroke_color: "white"
    engy:
      speaker_id: 8
      speed: 0.95
      subtitle:
        font_color: "#E6E6FA"
        stroke_color: "black"
```

これらの設定は、`config.yaml`でも指定可能です。

```yaml
system:
  timeline:
    enabled: true
    format: "md" # "md", "csv", "both", "none" から選択
  subtitle_file:
    enabled: true
    format: "srt" # "srt", "ass", "both", "none" から選択
```

Markdown入力では、frontmatter の `markdown` セクションで画像化するパネルの見た目を調整できます。`text.font_size` は希望サイズとして扱われ、入り切らない場合は `min_font_size` まで自動で縮小します。`#` 見出し、箇条書き、引用はプレーンテキストではなく Markdown らしい見た目に整形して描画します。

```yaml
markdown:
  layer:
    scale: 0.86
    position: {x: 0, y: -72}
  panel:
    margin: {x: 180, y: 42}
    padding: {x: 56, y: 42}
    background:
      color: "#0F172A"
      opacity: 0.92
      border_color: "#E2E8F0"
      border_width: 3
      radius: 28
  text:
    font_path: /usr/share/fonts/opentype/ipafont-gothic/ipag.ttf
    font_size: 50
    min_font_size: 30
    color: "#F8FAFC"
```

---

## 💡 今後の機能拡張予定

- [ ] **キャラクター表現の強化**: 表情差分や口パクの自動生成に対応し、キャラクターの表現力を向上させます。
- [x] **シーン間トランジション**: YAMLの `scene.transition` を適用（映像 xfade ＋ 音声 acrossfade）。

以下は、台本ファイルでのトランジション設定の記述例です。

`transitions.wait_padding_seconds` が 0 より大きい場合、シーン同士を直接重ねず、前シーンを最後まで再生してから終端フレームを静止保持し、その後に次シーン先頭とトランジションします。トランジションに使った次シーン先頭は後続本編から消費されるため、OP→本編、本編→EP のような境界で先頭の音声や口パクが二重に見えないことを基本仕様とします。

```yaml
scenes:
  - id: intro
    bg: "assets/bg/sample_video.mp4"
    lines:
      - text: "最初のシーンです。"
    transition: # このシーンの後に適用されるトランジション
      type: "fade" # トランジションの種類 (例: fade, dissolve, wipeleftなど)
      duration: 1.0 # トランジションの期間 (秒)

  - id: topic
    bg: "assets/bg/street.png"
    lines:
      - text: "次のシーンです。"
```

---

## ⚙️ 最適化オプション（config.yaml）

動画背景で静的オーバーレイのないシーンにおけるベース映像生成の最適化を制御できます。

```yaml
video:
  # 静的オーバーレイが無いシーンでベース映像を生成する最小行数
  # N未満ならベースを作らず、背景を一度だけ正規化して各行へ伝搬（重複スケール回避）
  scene_base_min_lines: 6
  # CPU中心のときだけ auto/2 を検討。GPU時は1推奨
  scene_workers: 1

voice:
  # AudioPhaseで最大2本まで先行並列化（VOICEVOX安定性優先）
  parallel_workers: auto

system:
  # 字幕なしのシーン動画を内部キャッシュし、字幕だけの再生成を速くする
  cache_scene_base_video: true
  # *_no_sub.mp4 は必要なときだけ有効化
  generate_no_sub_video: false
```

挙動:
- 静的オーバーレイが1つ以上ある場合は常にベース映像を生成（静的レイヤを事前合成）。
- 静的オーバーレイが無い場合、行数が `scene_base_min_lines` 未満ならベース生成をスキップし、背景動画を一度だけ正規化して各行の合成に使います（`normalized=True`/`pre_scaled=True` 伝搬）。
- 行数がしきい値以上なら、再利用効率の観点からベース映像を生成します。
- `system.cache_scene_base_video: true` の場合、シーン結合後かつ字幕焼き込み前の動画を `scene_<id>_base` として内部キャッシュします。字幕テキスト、字幕位置、フォントなどを調整した再生成では、このベース動画を再利用し、字幕焼き込みからやり直せます。`*_no_sub.mp4` を成果物として出力する `system.generate_no_sub_video` とは別機能です。

---

## 🚀 パフォーマンスと運用（上級者向け）

- GPUオーバーレイ方針: 完成版の字幕焼き込みは字幕装飾に応じて `ASS/libass` と `PNG` を自動切替します。RGBAを含む overlay は引き続きCPU側で合成し、RGBAを含まない場合はGPU（overlay_cuda/scale_cuda or scale_npp）を利用します。
- CUDA診断とフォールバック: CUDAフィルタのスモーク/実行時に失敗した場合、初回のみ `ffmpeg -buildconf` / `ffmpeg -filters` / `nvidia-smi -L` / `nvcc --version` をINFOで自動出力し、CPUフィルタにフォールバックします。`scale_cuda` が無い環境では自動で `scale_npp` を使用します。
- ハイブリッドGPUスケール: RGBAオーバーレイでCPU合成となる場合でも、背景のスケーリングのみGPUで実施してからCPUへ戻す最適化が可能です（`video.gpu_scale_with_cpu_overlay: true` 既定有効）。CUDA が使えない環境では OpenCL によるスケール専用（`scale_opencl`）をスモークに通った場合に限り自動で利用します。
 - CUDAフィルタ有効化（DevContainer）: `.devcontainer/Dockerfile.gpu` は既定でBtbNプリビルドを導入します。環境により `overlay_cuda/scale_cuda` が実行失敗する場合は、`BUILD_FFMPEG_FROM_SOURCE=1` を指定してFFmpegを `--enable-cuda-nvcc --enable-libnpp --enable-nonfree` でビルドしてください（`.devcontainer/.env`）。
 - 画質プリセット連動のスケーラ最適化: `--quality` に応じてCPUスケーラのフラグを変更します（speed=fast_bilinear, balanced=bicubic, quality=lanczos）。設定から直指定する場合は `video.scale_flags` を利用できます。
 - 字幕PNGプリキャッシュ: `video.precache_subtitles: true` でシーン内の字幕PNGを事前生成（プロセスプール並列）。VideoPhase中の待ち・ばらつきを低減します。
 - 字幕PNGワーカー共有: 字幕PNGプリキャッシュと実合成の両方で同じ `ProcessPoolExecutor` を共有し、シーンまたぎの立ち上げコストを避けます。
 - 字幕焼き込みモード: 軽量な字幕ボックスは `ASS/libass`、角丸や枠線や背景画像を含む装飾付き字幕は `PNG` を自動選択します。
 - 音声生成の先行起動: AudioPhase は先に音声タスクを投げてからタイムライン順に回収するため、VOICEVOX待ちの直列化を緩和します。既定の `voice.parallel_workers=auto` は安定性優先で最大2並列です。
 - シーン並列描画: `video.scene_workers` を `auto` または整数で指定すると、シーン単位で並列レンダリングします。GPUパスでは競合しやすいため既定は `1` です。
  - 単純シーン fast path: 背景静止画・単一キャラ・通常発話だけのシーンは、GPU エンコード時だけ 1 シーン 1 FFmpeg に寄せる fast path を使います。CPU では巨大 filter graph が遅くなりやすいため適用しません。
- スレッドとプロファイル:
  - `FFMPEG_PROFILE_MODE=1` で `-benchmark -stats` を付与し、FFmpegの所要・スループットを収集できます。
  - `FFMPEG_THREADS` で `-threads` を明示上書き可能。
  - CPUフィルタ経路で `--jobs auto/0` の場合、各クリップFFmpegの `-threads` は `nproc // clip_workers` に自動調整（過剰スレッド化の抑制）。NVENC/GPU 経路では `-threads 0`（自動）。
  - CPUフィルタ経路では `-filter_threads`/`-filter_complex_threads` を保守的にキャップ（既定=4）。`FFMPEG_FILTER_THREADS_CAP`/`FFMPEG_FILTER_COMPLEX_THREADS_CAP` で上限を調整できます。
- 自動チューニング（初期クリップ計測）:
  - `video.auto_tune: true` で初回数クリップ（既定4）を計測し、CPU overlay が支配的なら `filter_threads` の上限と `clip_workers` を保守的に調整します。CPUコア数に応じて 2→3/4 ワーカーまで再探索する軽量ヒューリスティクスを追加し、平均/90パーセンタイル時間をログ出力します。
  - 字幕PNGプリキャッシュ: `video.precache_subtitles: true`（既定）で各シーンの字幕PNGを事前生成。`video.precache_min_lines` を設定すると、`precache_subtitles=false` 時でもシーン行数が閾値以上なら自動有効化。
  - キャラPNG事前スケール: 立ち絵PNGは Pillow で目標スケールに事前変換しキャッシュ。CPU overlay 時は `scale` フィルタを省略し、`format=rgba` のみで合成（`CHAR_CACHE_DISABLE=1` で無効化）。
  - 口パクタイムラインのキャッシュ: 音声WAVとパラメータ（fps/閾値）に基づきJSONをキャッシュ（`cache/`）。`--no-cache` 時はラン内Ephemeralを再利用。
  - CPUモードでも OpenCL overlay を許可（既定は無効）: `video.allow_opencl_overlay_in_cpu_mode: true` を設定し、スモーク合格時に `overlay_opencl` を使用。
  - FPSフィルタの最適化: speedプリセットでは背景スケール時の `fps=` フィルタを省略（`video.apply_fps_filter: false`）し、出力側の `-r` によるCFR固定に任せます。
  - `video.profile_first_clips: 4` で計測クリップ数を変更可能。
  - CPU overlay が支配的な場合は、フィルタ経路をCPUに統一（`set_hw_filter_mode('cpu')`）し、以降の安定性と一貫性を優先します（NVENCエンコードは継続）。
  - CPUフィルタモード時は初期並列を抑制（`clip_workers<=2`）して先頭クリップの過負荷を回避します。
  - オーバーレイが重いシーンは初回から `clip_workers=2` へ寄せ、単一シーンで6本以上の FFmpeg を同時起動して遅くなるケースを避けます。
- リップシンク補正: 口パクタイムラインは `audio_delay` を加味してシフトするようにし、キャラ登場アニメ後に音声を遅延再生するケースでも口の動きが先行しないようにします。
- no_sub 動画は opt-in: `system.generate_no_sub_video: false` を既定にし、必要なときだけ `*_no_sub.mp4` を生成するようにしました。高速化優先時は余分な Finalize/BGM を避けられます。
- 字幕なしシーン内部キャッシュ: `system.cache_scene_base_video: true` を既定にし、字幕焼き込み前の `scene_<id>_base` を再利用します。字幕だけを調整する再生成では `[SceneCache] layer=base HIT` のログが出れば、発話クリップ生成とシーンconcatをスキップできます。
- 完成版 / no_sub の分離: no_sub を有効にした場合は FinalizePhase の出力ファイル名を分け、完成版を no_sub 版で上書きしないようにしました。
- 一時ディレクトリ（RAMディスク）: `USE_RAMDISK=1`（既定）で空き容量が十分なら `/dev/shm` を一時ディレクトリに使用し、I/Oを高速化します。
- 正規化の再実行抑止: 正規化出力に `<name>.meta.json` を隣接保存し、同一 `target_spec` の入力は再正規化をスキップします。
- no-cache時の重複抑止: `--no-cache` でも同一キー生成はプロセス内でin-flight集約し、同一ラン内の重複生成を避けます。生成物は `temp_dir` のEphemeralとして再利用されます。
- concat最適化: `-f concat -c copy` のリストファイルは出力ディレクトリに配置し、I/O局所性を改善しています。

- フィルタ診断ログ: 起動時に `overlay_cuda/scale_cuda/scale_npp/overlay_opencl/scale_opencl` 等の存在とスモークテスト結果（CUDA/OpenCL/scale-only）を INFO ログにサマリ表示します。

設定例（GPUで字幕のGPUオーバーレイを試す）:
```yaml
video:
  gpu_overlay_experimental: true
  auto_tune: true
  profile_first_clips: 4
  precache_subtitles: true
```


## ⚠️ ライセンスと利用ガイドライン

本プロジェクトはMITライセンスの下で公開されています。詳細については[LICENSE](LICENSE)ファイルをご確認ください。
同梱素材（`assets/`）の出典・ライセンス・再配布可否は **コードとは別** に管理します。公開前に必ず [assets/ATTRIBUTION.md](assets/ATTRIBUTION.md) を確認・更新してください。
VOICEVOXの利用に関しては、キャラクターごとに商用利用の可否が異なります。必ず[VOICEVOX公式サイトの利用規約](https://voicevox.hiroshiba.jp/)をご確認ください。

---

## 🧑‍💻 制作者

- c_a_p_engineer ([X (旧Twitter)](https://x.com/c_a_p_engineer))

---

## ✅ よくあるエラーと対処法

| エラー                                           | 対処法                                                   |
| --------------------------------------------- | ----------------------------------------------------- |
| `ModuleNotFoundError: No module named 'yaml'` | `pip install -r requirements.txt`                     |
| `ffprobe not found`                           | Dockerfile に `apt install ffmpeg` を追加                 |
| `No module named 'zundamotion'`               | `PYTHONPATH=.` を指定 or `python -m zundamotion.xxx` で実行 |
| `Validation Error: ...`                       | YAML台本の構文、素材パス、またはパラメータ値を確認してください。エラーメッセージに行番号と列番号が示されます。 |

## キャラクターアセット構成（表情ディレクトリ対応）

本プロジェクトは、表情ごとのディレクトリ構成を優先して素材を探索します。従来のフラット配置（`<expr>.png`、`mouth/`・`eyes/`直下）もフォールバックで引き続き利用可能です。

探索順（ベース立ち絵）

1) `assets/characters/<name>/<expr>/base.png`
2) 互換: `assets/characters/<name>/<expr>.png`
3) `assets/characters/<name>/default/base.png`
4) 互換: `assets/characters/<name>/default.png`

探索順（口/目の差分）

- 口: `assets/characters/<name>/<expr>/mouth/{close,half,open}.png` → `assets/characters/<name>/mouth/{...}` → 互換: `assets/characters/<name>/mouth/<expr>/{...}`
- 目: `assets/characters/<name>/<expr>/eyes/{open,close}.png` → `assets/characters/<name>/eyes/{...}` → 互換: `assets/characters/<name>/eyes/<expr>/{...}`

推奨ディレクトリ例

```
assets/
  characters/
    copetan/
      default/
        base.png
        mouth/
          close.png
          half.png
          open.png
        eyes/
          open.png
          close.png
      smile/
        base.png
        mouth/
          close.png
          half.png
          open.png
        eyes/
          open.png
          close.png
```

運用ルール

- キャンバスサイズと原点（左上）を全ファイルで統一してください（ズレ防止）。
- `expression` 名は小文字英字で台本の `characters[].expression` と一致させることを推奨します。
- 最低限必要: `default/base.png` と `default/mouth/{close,half,open}.png`, `default/eyes/{open,close}.png`

移行について（このリポジトリの既存素材）

- Copetan と Engy の立ち絵は `default/` 配下に統一済みです（`base.png`＋`mouth/`＋`eyes/`）。
- 旧来の `default.png` や `mouth/*` 直下のファイルは整理済みで、今後はディレクトリ構成版のみを管理対象とします。
- ずんだもん／めたん素材はリポジトリから削除しました。必要に応じて各自のプロジェクトで管理してください。

注意

- 古い命名（例: `default!.png` など記号入り）は今後の運用で避けてください。必要に応じて `default/base.png` へ置き換えてください。
