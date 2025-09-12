# 📋 Zundamotion タスクリスト（優先度順・再整理）

本ファイルは、最新ログを踏まえた改善タスクを優先度順に記載します（完了済みは削除）。
各タスクは「背景 / 目的 / 方針 / 実装イメージ / 成果確認」の形式で詳細化します。

参照ログ（最新→古い順）: `logs/20250911_062724_974.log`, `logs/20250910_045352_758.log`, `logs/20250910_041524_580.log`

最新観測サマリ（2025-09-11 実行）:
- 総所要: 160.19s。内訳: AudioPhase 8.46s / VideoPhase 133.79s / BGMPhase 2.17s / FinalizePhase 13.52s。
- ボトルネック: VideoPhase（約83%）。`Filter path usage: cuda_overlay=0, opencl_overlay=0, gpu_scale_only=21, cpu=0`。
  - 背景スケールはGPUのみ、合成はCPU overlay（ハイブリッド）。
  - Scene Base生成が「静的オーバーレイ=0」でも各シーン10–15s程度発生。
- FFmpegスレッド自動調整: nproc=12 → `clip_workers=3`, `threads=4`, `filter_threads=2`。
- ConcatCopyは高速（~170MB/s）。


## P0（新機能）VNモード：シーン内キャラ持続表示の導入（非破壊）

ビジュアルノベル風の「登場後は退場まで常時表示」「退場後は非表示」を、シーン内限定で実現する。
既存挙動（行ごとスナップショット）を既定として維持し、`characters_persist` 有効時のみ差分解釈に切り替える。

参考コードと発見点:
- 立ち絵の解決と合成は `zundamotion/components/video.py:520` 以降。
- 行レンダ入口（effective_characters 決定ポイント）は `zundamotion/components/pipeline_phases/video_phase.py:780` 付近。
- 座標式は `zundamotion/utils/ffmpeg_ops.py:246` `calculate_overlay_position` を利用。

### VN-00 用語と仕様の確定（設計のみ）
- 背景: 仕様の曖昧さを解消し実装に落とす。
- 目的: シーン内での持続表示・差分指定・演出のON/OFFを明確化。
- 方針:
  - characters_persist: シーン内でキャラ状態（可視・表情・位置等）を持続させるフラグ。既定は false。
  - スロット: `slot: left|center|right` を `anchor/position` に変換（anchor=`bottom_center`）。
    - x: left→ `-(W/4)`, center→ `0`, right→ `+(W/4)`（Wは動画幅）。
    - y: `-(H*0.02)` として僅かに上げる（微調整可）。
  - フォーカス: 行単位でON/OFF可能。ON時は「発話者以外」を軽く減光（例: `eq=brightness=-0.05:saturation=0.9`）。既定はOFF。
  - トランジション: enter/exit にフェード適用（既定 250ms）。
  - 自動登場: なし。必ず `enter`（または `visible:true`）で明示。
  - 口パク/まばたき: 口パクは発話者のみ／まばたきはその行で可視な全員に適用。
- 実装イメージ: 下位タスク VN-01〜03 に従い段階導入。
- 成果確認: サンプル台本で「登場→継続→退場」が期待通り・フォーカス/フェードが効く。

### VN-01 スキーマ拡張（台本・既定値）
- 背景: 差分指定と演出を台本で表現可能にする。
- 目的: 互換性を保ちながら最小キー追加でVNモードを有効化。
- 方針（追加キー案）:
  - 既定（scriptまたはconfig）
    - `script.defaults.characters_persist: false`（既定）
    - `script.defaults.vn.focus.enabled: false`
    - `script.defaults.vn.transitions.enter_ms: 250`
    - `script.defaults.vn.transitions.exit_ms: 250`
    - `script.defaults.vn.focus.brightness_delta: -0.05`
    - `script.defaults.vn.focus.saturation: 0.9`
  - 行レベル（差分）
    - `characters: [{ name, enter|exit, expression, slot|position, scale, z }]`
    - `reset_characters: true`（その行頭で全員退場）
    - `vn: { focus: true|false }`（行単位の上書き）
- 実装イメージ:
  - `components/config_validate.py` にキーを許容（必須ではない）。
  - `components/script_loader.py:1` で既定値マージは既存の仕組みを流用。
- 成果確認: 追加キーがエラーなく読み込め、既存台本も動作不変。

### VN-02 CharacterTracker 設計と追加（VideoPhase）
- 背景: 行ごとに差分を適用し有効キャラ集合を生成する必要。
- 目的: シーン内でキャラ状態を保持・更新して `effective_characters` を出力。
- 方針:
  - `CharacterState`: {name, visible, expression, slot|position, scale, z, entering, exiting} を保持。
  - シーン開始でリセット、`reset_characters` で全消し。
  - 行の `characters[]` を差分として適用（enter/exit/表情/スロット/座標/スケール）。
  - スロット→座標は `calculate_overlay_position` 前提で `anchor='bottom_center'` + 既定オフセットに正規化。
  - フォーカス判定: 既定+行上書き、`speaker_name` を発話者として記録。
  - 口パク/まばたき: その行の可視キャラ集合と発話者から `face_anim` メタを構築。
- 実装イメージ:
  - 実装箇所: `components/pipeline_phases/video_phase.py:780` 付近に `CharacterTracker` を導入。
  - `characters_persist:false` の場合は従来どおり `line.characters` をそのまま使用。
- 成果確認: ログに tracker の適用が出力され、`effective_characters` が差分通り生成。

### VN-03 行レンダリングへの組み込みとキャッシュキー拡張
- 背景: 見た目の変化がキャッシュ衝突しないようにする。
- 目的: `get_or_create` キーに視覚状態を反映するハッシュを追加。
- 方針:
  - `characters_effective_hash` を `video_cache_data` に追加（name/expression/scale/anchor/position/z/focus/entering/exiting）。
  - VNモード時は「静的レイヤのベース取り込み」を原則OFF（enter/exit/フォーカスが効かなくなるため）。
- 実装イメージ:
  - 実装箇所: `components/pipeline_phases/video_phase.py:920` 前後（talk系の `video_cache_data` 構築部）。
  - ベース最適化制御: `video_phase.py:398` 以降の静的判定に `characters_persist` を加味。
- 成果確認: 同一音声でも見た目が異なる場合にキャッシュ取り違えが起きない。

### VN-04 VideoRenderer 最小改修（フォーカス・トランジション）
- 背景: キャラOverlay段で効果を注入する必要。
- 目的: 既存のFilterグラフに最小変更でフォーカス/フェードを適用。
- 方針:
  - フォーカス: `active_speaker` と `vn.focus` を `render_clip` に渡し、各キャラの合成直前に `eq=brightness=Δb:saturation=s` を付与（発話者以外）。
  - フェード: `entering/exiting` に応じて `fade=t=in/out:d=ms/1000` をキャラストリームへ付与（1回限り）。
  - 既定値は `config.video` または `defaults.vn` から取得。
- 実装イメージ:
  - 実装箇所: `components/video.py:520` 以降のキャラ合成部分。
  - `characters_config` の各要素に `{ entering, exiting }` を付加し、`line_config` で `{ active_speaker, vn: { focus } }` を受ける。
- 成果確認: サンプルで非発話者が減光、enter/exitにフェードがのる。

### VN-05 Config 読み込み・バリデーションの拡張
- 背景: 新キーの読み書きで失敗しないようにする。
- 目的: 互換性を壊さずに新キーを許容。
- 方針: `config_validate.py` に `script.defaults.vn.*` と行の `reset_characters`/`vn.focus` を追加許容。
- 実装イメージ: `zundamotion/components/config_validate.py:1` に型・既定の緩い検証を追加。
- 成果確認: 新旧台本でバリデーションエラーが出ない。

### VN-06 検証用サンプル台本と再生性テスト
- 背景: 手動検証の手間を下げる。
- 目的: 最小ケースで仕様が満たされることを確認。
- 方針: 3〜5行のシーンで「登場→継続→別キャラ登場→退場」「フォーカスON/OFF」を含むYAMLを用意。
- 実装イメージ: `assets/` 配下の既存キャラ素材で再生。`tests/` に期待スクリーンショット（任意）。
- 成果確認: 目視で仕様どおり、ログにVNパスの診断が出る。

### VN-07 ドキュメント（README/テンプレ）
- 背景: 台本作者が使い始めやすくする。
- 目的: キー一覧・スロット早見表・サンプルを追加。
- 方針: READMEの「スクリプト書き方」に VN モード節を追加。
- 実装イメージ: スロット→座標の式、注意点（ベース取り込みの制限、フォーカスの既定OFF等）を記載。
- 成果確認: 新規ユーザがこの節のみで利用開始できる。

### VN-08 後続: video.py の責務分割（設計のみ、実装は別フェーズ）
- 背景: `video.py` が肥大（入力列構築・背景・立ち絵・字幕・GPU/CPU切替が一体）。
- 目的: 責務分離で保守性を高め、VN演出の追加を安全にする。
- 方針（クラス分割案）:
  - BackgroundBuilder: 背景正規化/ループ/シーンベース。
  - CharacterOverlayBuilder: 立ち絵の入力投入・事前スケール・フィルタ断片生成（フォーカス/フェード含む）。
  - ClipCommandBuilder: 入力/マップ/フィルタグラフを最終コマンドに組立。
  - VideoRenderer: 上記のオーケストレーションのみ。
- 実装イメージ: まずは設計ドキュメント（クラス境界と責務）を `docs/` に作成。
- 成果確認: 設計合意後、実装タスクへ分割可能な状態。


## P1（品質向上・高速化）

### 00. FFmpeg を CUDAフィルタ入りビルドへ切替（環境整備）
- 背景: 現状 `overlay_cuda` が不可のため、合成がCPU支配で VideoPhase が長い。
- 目的: `overlay_cuda`/`scale_cuda`/`scale_npp` を有効化し、GPU内で合成→NVENCへ直接渡して往復コストを削減。
- 方針: DevContainer/DockerでCUDA対応FFmpegをビルドまたは採用（`--enable-cuda-nvcc --enable-libnpp --enable-nonfree`）。スモークテストとフィルタ一覧をログ出力し自動判定を強化。
- 実装イメージ: `.devcontainer/Dockerfile.gpu` 切替、起動時に `ffmpeg -filters`/`-buildconf` を1回だけログへ。`utils/ffmpeg_hw.py` で `set_hw_filter_mode` とスモークの分岐を調整。
- 成果確認: ログに `cuda_overlay>0` が出現し、VideoPhase時間が大幅短縮。

### 01. Scene Base の無駄レンダ回避（静的オーバーレイ0件時はスキップ）
- 背景: `generated base with 0 static overlay(s)` でも各シーン10–15sのベース生成が発生。
- 目的: 静的前景が無いケースでのベース生成を省略し、行クリップの合成へ直行。
- 方針: Sceneごとに「静的前景=0」かつ「背景が正規化済み」の条件でベース生成をバイパス。
- 実装イメージ: `video_phase.py` のベース生成分岐にガードを追加。バイパス時は行合成の背景入力を正規化済みパスに差し替え。
- 成果確認: ベース生成時間=0s、VideoPhase合計の短縮（シーン数×10–15s）。

### 02. 既存最適化の効果検証＆チューニング（VideoPhase短縮）
- 背景: 字幕PNGプリキャッシュ/キャラPNG事前スケール/スケーラ最適化/FPSフィルタ抑制により改善中。
- 目的: 閾値・プリセットの最適化と回帰防止。
- 方針: `precache_min_lines`/`CHAR_ALPHA_THRESHOLD`/`scene_base_min_lines`/`allow_opencl_overlay_in_cpu_mode` を調整、遅い行Top5を継続計測。
- 実装イメージ: 既存設定とヒューリスティクスの調整値を `templates/config.yaml` とコード定数で管理、ログに比較結果を出力。
- 成果確認: VideoPhase 133.79sからの更なる5–10%短縮。

### 03. OpenCL overlay 安定性検証（オプトイン）
- 背景: CPUモードでも OpenCL overlay を限定的に許可するオプトインがあるが、環境差が大きい。
- 目的: 対象環境での安定性と速度向上を検証し既定値の是非を判断。
- 方針: `video.allow_opencl_overlay_in_cpu_mode: true` の計測、失敗時フォールバックの動作確認。
- 実装イメージ: スモーク通過時のみ `overlay_opencl` を使用。障害検知で一度だけ診断出力→CPUへバックオフ。
- 成果確認: ログ `opencl_overlay>0` かつ VideoPhase短縮、エラー未増。


## P2（改善・将来・機能追加）


### 02. 複数キャラクター同時配置（レイアウト・Z順・自動配置）
- 背景: 2人/3人ショットなど同時表示ニーズ。
- 目的: `characters[]` を同時合成し、Z順・レイアウトを簡便に指定。
- 方針: `z`/`anchor`/`layout(two_shot/three_shot)`/`safe_margin` を拡張。
- 実装イメージ: テンプレレイアウト（左右/三分割）と自動スケール、重なり回避ロジックを実装。
- 成果確認: 被り・はみ出しなしで配置、Z順が意図通り。

### 03. アニメーション基盤（キーフレーム/式/プリセット）
- 背景: キャラクターや前景に揺れ/スウェイ/ズーム等の動きを付けたい。
- 目的: `position/scale/rotate/opacity` をキーまたは時間式で制御し、プリセットも提供。
- 方針: `anim` ブロック導入（keys or expr）。easing、sin/cos、減衰などをサポート。
- 実装イメージ: FFmpeg式を `overlay/rotate/scale` にバインド。`shake/sway/bob/jiggle` のプリセット展開。
- 成果確認: デモYAMLで滑らかな動作、プレビュー/本番で一致。

### 04. カメラワーク（パン/ズーム/ティルトの擬似）
- 背景: 静止背景でも動きを演出したい。
- 目的: シーン全体に擬似的なカメラ移動を適用。
- 方針: 背景に `zoompan/scale` と `crop` を組み合わせ、`anim` 同等の指定で制御。
- 実装イメージ: 安全枠（overscan）と境界処理、イージング対応。
- 成果確認: イントロ/アウトロで滑らかなパン・ズームが適用。

### 05. マスク/マット・カスタムワイプ
- 背景: 形状に沿った表示/トランジション需要。
- 目的: マスクPNGやマット合成、ロゴ形状ワイプを実現。
- 方針: `alphamerge`/`colorkey`/`format=yuva444p` の組合せで実装。
- 実装イメージ: `fg_overlays[*].mask` や `transitions[*].wipe` を追加し、ルックアップで適用。
- 成果確認: カスタム形状での合成/ワイプが崩れなく動作。

### 06. ローワーサード/テロップ（テンプレ）
- 背景: 名前帯・解説帯の需要。
- 目的: テンプレ＋簡易APIで素早く統一デザインを適用。
- 方針: `lower_third` テンプレを複数同梱、テキスト/色/位置のオプション。
- 実装イメージ: PNGテンプレ合成 or drawtextプリセット化、アニメ入退場（ease）。
- 成果確認: デモ台本で統一感のあるローワーサードが適用。

### 07. ピクチャー・イン・ピクチャー（PIP）
- 背景: 解説/リアクション等での小画面表示。
- 目的: 角丸/影/枠のPIPを簡単指定。
- 方針: PIPレイヤを追加し、枠/シャドウを filter_complex で合成。
- 実装イメージ: `pip: {src, rect, radius, shadow, border}` のスキーマ追加。
- 成果確認: 配置/枠/影のオプションが反映。

### 08. カラオケ風字幕（進行ハイライト）
- 背景: 読み上げ進行に同期した強調表示。
- 目的: 視認性と没入感の向上。
- 方針: 語/モーラ単位のタイムスタンプを用いてハイライトレイヤを生成。
- 実装イメージ: 分割PNG/マスク or `subtitles` フィルタ、タイムラインに進行率を記録。
- 成果確認: 音声とハイライトの誤差 < 100ms。

### 09. BGM ビート検出と自動カット合わせ
- 背景: 音楽の拍にカット/台詞を寄せたい。
- 目的: テンポ感の向上と一体感。
- 方針: オンセット検出→微調整（許容±数百ms）。
- 実装イメージ: librosa等でbeat/onset抽出→台詞開始時刻補正。
- 成果確認: クリックデバッグと視聴で自然な一致。

### 10. SRT/WebVTT の入出力（双方向）
- 背景: 外部ツールとの互換性要求。
- 目的: SRT/ASS/VTT のインポート/エクスポート対応。
- 方針: `Timeline` を拡張して双方向変換を実装。
- 実装イメージ: parser/writer を追加し、CLIで指定可能に。
- 成果確認: 既存ツールとの往復で差分最小。

### 11. プレビュー高速レンダリングモード
- 背景: 調整反復を高速化したい。
- 目的: 低解像度・低ビットレートでのクイック出力。
- 方針: `--preview` で `VideoParams` を縮小、字幕PNGは共通キャッシュ。
- 実装イメージ: 720p/540pプリセット、CRF/ビットレートを軽量化。
- 成果確認: 所要時間が大幅短縮（品質はプレビュー用途）。

### 12. 背景除去/クロマキー（簡易）
- 背景: グリーンバックや静止画の単純除去需要。
- 目的: 破綻の少ない色キー/差分合成を提供。
- 方針: `colorkey`/`chromakey` の適用、差分は限定提供。
- 実装イメージ: `fg_overlays[*].chroma` の拡張、塗り足し/エッジブラーを追加。
- 成果確認: 境界ノイズ・色抜けが許容範囲。

### 13. パーティクル（雨/雪/キラ）プリセット
- 背景: 手軽に演出を強化したい。
- 目的: 軽量素材/手続きでの雨・雪・キラ演出。
- 方針: 既存素材のタイリング/ループ＆色調整をテンプレ化。
- 実装イメージ: `effects[]` に `particles: {type, density, speed, color}` を追加。
- 成果確認: 種別ごとの見た目が安定し負荷が許容内。

### 14. VOICEVOX 音声合成の並列化（スピーカー単位の上限）
- 背景: 今回はAudioが支配的でないが、大規模台本で効果が見込める。
- 目的: スループット向上と安定性（レート制限回避）。
- 方針: `asyncio.Semaphore` による全体/話者別上限、タイムアウト/リトライ調整。
- 実装イメージ: クライアント層で並列制御、メトリクスをログ化。
- 成果確認: 大規模台本で短縮、エラー未増。

### 15. YAMLスキーマ拡張（assets辞書・字幕スタイルテンプレ）
- 背景: パス直書きや冗長なスタイル指定の負担。
- 目的: スキーマの簡素化/可読性向上。
- 方針: assets辞書/スタイルテンプレ参照を追加、`script_loader` で解決。
- 実装イメージ: `assets: {logo: path, ...}` と `subtitle.styles[]` のテンプレ機構。
- 成果確認: 台本の重複削減・編集性向上。

### 16. 自動ポーズ/句読点ルール
- 背景: 句読点での自然な間の需要。
- 目的: 自然な発話テンポの実現。
- 方針: テキスト整形でポーズを挿入、音声生成と同期。
- 実装イメージ: 句読点/記号ごとに既定ポーズ、上書きパラメータ対応。
- 成果確認: 聴感上の自然さ、タイムライン整合。

### 17. サムネ/チャプター自動生成
- 背景: 公開準備の効率化。
- 目的: キーシーン静止画とYouTubeチャプターTXTを自動作成。
- 方針: `Timeline` のシーン境界/台詞見出しから生成。
- 実装イメージ: ffmpegでサムネ抽出、md/txtでチャプター出力。
- 成果確認: 生成物の内容/時刻が妥当。

### 18. プロジェクトテンプレ/テーマ
- 背景: 新規プロジェクト立ち上げの簡略化。
- 目的: スタイル/構成の再利用性向上。
- 方針: `templates/` 整備とCLIスキャフォールド。
- 実装イメージ: 複数テーマの雛形、READMEチュートリアル付き。
- 成果確認: ひな形からの生成が成功。
