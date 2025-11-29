1. **Ken Burns/Transformキーフレーム実装** (優先度: P0)  
   - 詳細: `clips[].kenburns`と`motion.keyframes`をfilter_complexに落とし込み、位置/スケール/回転を時系列補間できるようにする。  
   - 実装イメージ: zoompan/scale/rotateを合成し、enable式で時間制御。キーフレームは線形/イージング補間をサポート。  
   - 補足: `docs/design/yaml_schema_draft.md`と`docs/design/parser_and_builder.md`のモデルに沿ってIR→フィルタビルダーを実装。

2. **速度変更（スロー/早送り）機能追加** (優先度: P0)  
   - 詳細: クリップ単位で再生速度を指定し、映像はsetpts、音声はatempoで同期させる。  
   - 実装イメージ: `clips[].speed`をIRに追加し、filter_complexでsetpts=PTS/速度、音声はatempoを複数段で適用。  
   - 補足: 0.5x〜2.0xを安全範囲とし、音声なしの場合はatempo省略。

3. **ノイズ/ブレンドモード/プリセットトランジション拡張** (優先度: P1)  
   - 詳細: 未対応エフェクト（`noise`）、ブレンドモード（screen/multiply/addition）、グリッチ/フラッシュ系プリセットを追加。  
   - 実装イメージ: overlayエフェクトプラグインにnoiseとblend filter、プリセットは短尺のvfチェーン（flash=fade+threshold等）を登録。  
   - 補足: `docs/design/ffmpeg_filter_mapping.md`に追記し、プラグイン登録テーブルを更新。

4. **BGMループ指定の実装** (優先度: P1)  
   - 詳細: BGMトラックにloopフラグ/回数を持たせ、動画尺に合わせて繰り返し再生。  
   - 実装イメージ: `aloop`またはconcatで音声を延長し、amix前に長さ調整。  
   - 補足: `bgm_phase.py`と`ffmpeg_audio.py`にloop処理を追加し、サンプルYAMLも更新。

5. **Jカット/Lカット対応** (優先度: P1)  
   - 詳細: シーン/行の音声を映像より前後にずらせるオプションを追加。  
   - 実装イメージ: `audio_offset_ms`を行/シーンに追加し、concat前にadelay/atrimで調整。  
   - 補足: タイムライン出力にもオフセットを反映。

6. **EQ/コンプレッサー/リバーブの簡易オーディオエフェクト** (優先度: P2)  
   - 詳細: BGM/ボイスに基本エフェクトを適用できるようにする。  
   - 実装イメージ: `anequalizer`/`acompressor`/`aecho`(簡易リバーブ)をオプション指定でfilter_complexに追加。  
   - 補足: 依存追加なしでFFmpeg標準フィルタを使用。

7. **クロマキー（グリーンバック）対応** (優先度: P2)  
   - 詳細: オーバーレイ動画/画像に`colorkey`/`chromakey`を適用できるようにする。  
   - 実装イメージ: overlay前にchromakeyフィルタを挟み、パラメータは`key_color`/`similarity`/`blend`をYAMLで指定。  
   - 補足: 透過後はrgba維持→最終yuv420p。

8. **LUT/カラーグレーディング強化** (優先度: P2)  
   - 詳細: lut3d以外のカラーホイール/トーンカーブを簡易指定できるようにする。  
   - 実装イメージ: `curves`プリセット、`colorbalance`をパラメータ化し、overlay_basicプラグインに登録。  
   - 補足: 既存lut3dとの併用順序を明文化。

9. **手ブレ補正（スタビライズ）** (優先度: P3)  
   - 詳細: 映像素材に対し`vidstabdetect/vidstabtransform`を適用し揺れを軽減。  
   - 実装イメージ: 前処理フェーズでstabデータを生成し、clipレンダリング時にtransformを適用。  
   - 補足: 追加依存を避けFFmpeg標準フィルタで実装。

10. **テンプレート/プリセット管理** (優先度: P3)  
    - 詳細: OP/EDやテロップスタイルを再利用できるプリセット管理を追加。  
    - 実装イメージ: `templates/`ディレクトリのYAMLをインポートし、スキーマに`use_template`フィールドを設けてマージ。  
    - 補足: タスク完了後、サンプルテンプレートをscriptsに追加。

11. **アセット管理/プロキシ生成** (優先度: P3)  
    - 詳細: 大容量素材向けにプロキシを生成し、編集用低解像度→最終高解像度に差し替えるフローを整備。  
    - 実装イメージ: ffmpegで低解像度proxy作成し、configで`use_proxy`指定時にproxyパスを参照、最終出力でオリジナルを使用。  
    - 補足: キャッシュキーに元解像度/更新時刻を含める。

12. **複数シーケンス管理** (優先度: P3)  
    - 詳細: シーケンス単位でタイムラインを分け、最終的に連結または個別出力できるようにする。  
    - 実装イメージ: `sequences[]`をトップレベルに追加し、各sequenceがscenes配列を持つ構造をサポート。  
    - 補足: timeline出力とtransition適用をシーケンス境界で制御。

13. **書き出しプリセット（解像度/ビットレート）** (優先度: P3)  
    - 詳細: 配信先向けプリセット（YouTube/Twitter/TikTokなど）の解像度・ビットレート・フォーマットを選択可能にする。  
    - 実装イメージ: `output.presets`を定義し、CLI `--preset`で選択しVideoParams/AudioParamsへ反映。  
    - 補足: 既存のHW検出ロジックと組み合わせて安全なデフォルトを提供。
