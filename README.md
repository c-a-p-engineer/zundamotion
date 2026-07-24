# Zundamotion

Zundamotion は、YAML 台本から `.mp4` 動画を生成するツールです。  
VOICEVOX による音声合成、FFmpeg による映像合成、字幕焼き込み、BGM/SE 合成、立ち絵表示をまとめて扱います。

公開デモサイト: [Zundamotion feature demos](https://c-a-p-engineer.github.io/zundamotion/)

この README は入口ページです。詳細な手順や仕様は `docs/` と `scripts/script_cheatsheet.md` に分離しています。

## まず把握すること

- 台本は YAML で書きます。
- 背景、立ち絵、字幕、音声、BGM を 1 本の動画へ合成します。
- 公式サポート対象は lock で固定した最新安定系列の CPython 3.14 系です。
- Python 3.13以前と3.15以降の未検証版、alpha / beta / RC / dev 版は公式サポート対象外です。
- 再現可能な実行環境として Docker / Dev Container の利用を推奨します。
- 利用者向けの詳細設定は [`scripts/script_cheatsheet.md`](scripts/script_cheatsheet.md) を見れば足ります。
- 機能一覧と実装状況は [`docs/features.md`](docs/features.md) を参照してください。

## 主な機能

- VOICEVOX 連携による通常発話音声生成
- FFmpeg ベースの背景、立ち絵、字幕、音声合成
- BGM / 効果音 / 前景オーバーレイ / テキストバッジ
- SRT / ASS 字幕ファイル出力
- `include` / `vars` による台本の再利用
- `--no-voice` による無音トラック生成
- Markdown 入力からの中間台本生成

## 最短の使い方

### 1. 依存を用意する

必要なのは主に以下です。

- Python
- FFmpeg / ffprobe
- VOICEVOX Engine

セットアップ詳細:

- 開発環境 / Dev Container / Codex Cloud: [`docs/guides/setup_and_runtime.md`](docs/guides/setup_and_runtime.md)
- submodule として使う場合: [`docs/guides/submodule.md`](docs/guides/submodule.md)

Dev Container は CPU runtime を標準にし、GPU は GPU Compose override を追加します。
通常の開発 image build では FFmpeg をコンパイルせず、checksum 固定 BtbN archive を導入します。
Python、FFmpeg、VOICEVOX、フォントの固定値と更新・ロールバック手順は
[runtime_version_policy.md](docs/guides/runtime_version_policy.md) を参照してください。

### 2. サンプルを実行する

```bash
python -m zundamotion.main scripts/sample.yaml -o output/sample.mp4
```

音声なしで最小確認する場合:

```bash
python -m zundamotion.main scripts/sample.yaml -o output/sample.mp4 --no-voice --no-cache
```

CLI 実行例、ログ形式、GPU/NVENC 確認、字幕出力、`--project-root` の説明は [`docs/guides/setup_and_runtime.md`](docs/guides/setup_and_runtime.md) を参照してください。

## 台本を書くときの入口

- YAML の基本構造: [`scripts/script_cheatsheet.md#基本構造`](scripts/script_cheatsheet.md#基本構造)
- シーンと行: [`scripts/script_cheatsheet.md#行とシーン`](scripts/script_cheatsheet.md#行とシーン)
- キャラクター表示: [`scripts/script_cheatsheet.md#キャラクター表示`](scripts/script_cheatsheet.md#キャラクター表示)
- BGM と音声チューニング: [`scripts/script_cheatsheet.md#bgm-と音声チューニング`](scripts/script_cheatsheet.md#bgm-と音声チューニング)
- 前景オーバーレイ: [`scripts/script_cheatsheet.md#前景オーバーレイ-fg_overlays`](scripts/script_cheatsheet.md#前景オーバーレイ-fg_overlays)
- 効果音: [`scripts/script_cheatsheet.md#効果音-sound_effects`](scripts/script_cheatsheet.md#効果音-sound_effects)
- サンプル台本一覧: [`docs/script_samples.md`](docs/script_samples.md)

## よく使うドキュメント

- docs 入口: [`docs/README.md`](docs/README.md)
- 機能一覧: [`docs/features.md`](docs/features.md)
- サンプル台本一覧: [`docs/script_samples.md`](docs/script_samples.md)
- 台本チートシート: [`scripts/script_cheatsheet.md`](scripts/script_cheatsheet.md)
- セットアップと実行: [`docs/guides/setup_and_runtime.md`](docs/guides/setup_and_runtime.md)
- パフォーマンスと運用: [`docs/guides/performance_tuning.md`](docs/guides/performance_tuning.md)
- キャラクター素材: [`docs/guides/character_assets.md`](docs/guides/character_assets.md)
- プロジェクト構造: [`docs/guides/project_structure.md`](docs/guides/project_structure.md)
- submodule 利用: [`docs/guides/submodule.md`](docs/guides/submodule.md)
- 実生成動画付き機能デモサイト: [公開サイト](https://c-a-p-engineer.github.io/zundamotion/) / [`site/README.md`](site/README.md)

## サンプル台本

- 標準サンプル: [`scripts/sample.yaml`](scripts/sample.yaml)
- 縦長レイアウト: [`scripts/sample_vertical.yaml`](scripts/sample_vertical.yaml)
- シーン遷移: [`scripts/sample_transitions.yaml`](scripts/sample_transitions.yaml)
- 字幕スタイル: [`scripts/sample_subtitle_styles.yaml`](scripts/sample_subtitle_styles.yaml)
- Markdown 入力: [`scripts/sample_markdown.md`](scripts/sample_markdown.md)

一覧は [`docs/script_samples.md`](docs/script_samples.md) にまとめています。

## プロジェクト構造

大まかな構成は次のとおりです。

```text
.
├── assets/      # 背景、立ち絵、BGM、SE
├── output/      # 出力動画
├── scripts/     # YAML 台本とサンプル
├── docs/        # ガイド、設計メモ、機能一覧
└── zundamotion/ # 本体コード
```

詳細な構造説明は [`docs/guides/project_structure.md`](docs/guides/project_structure.md) を参照してください。

## よくある参照先

- GPU / NVENC / OpenCL の確認方法: [`docs/guides/setup_and_runtime.md`](docs/guides/setup_and_runtime.md)
- 高速化オプション: [`docs/guides/performance_tuning.md`](docs/guides/performance_tuning.md)
- キャラ表情ディレクトリや mouth / eyes 差分: [`docs/guides/character_assets.md`](docs/guides/character_assets.md)
- 不採用にした機能の判断記録: [`docs/issues_pending.md`](docs/issues_pending.md), [`docs/guides/song_mode_rejected.md`](docs/guides/song_mode_rejected.md)

## ライセンス

本プロジェクトは MIT License です。  
同梱素材の出典や再配布条件は [`assets/ATTRIBUTION.md`](assets/ATTRIBUTION.md) を確認してください。  
VOICEVOX の利用条件は [VOICEVOX 公式サイト](https://voicevox.hiroshiba.jp/) を参照してください。
