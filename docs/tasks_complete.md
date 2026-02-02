1. **OpenCLスモークテストのscale_opencl互換修正** (完了日: 2026-02-01)  
   - 完了内容: `scale_opencl` を named options（`w=`/`h=`）に統一し、OpenCL smoke test と clip renderer のフィルタグラフへ反映。ユーティリティとテストを追加。  
   - メモ: FFmpeg 7+ の "No option name near 'WxH'" を回避。

2. **GPUバックエンド不在時のCPUモード自動切替** (完了日: 2026-02-01)  
   - 完了内容: GPU overlay/scale-only が両方無効な場合に HW filter mode を CPU へ切替え、スレッド設定の過剰並列を抑制。  
   - メモ: 切替理由をログに記録。

3. **Docker GPU/NVENC診断のREADME追記** (完了日: 2026-02-01)  
   - 完了内容: `nvidia-smi`/`libnvidia-encode` の確認と `NVIDIA_DRIVER_CAPABILITIES=video` 指定をREADMEへ追記。  
   - メモ: NVENCが使えない場合の対処手順を明文化。

1. **台本のinclude/vars対応** (完了日: 2026-01-28)  
   - 完了内容: `include` による台本再利用、`${VAR}` 置換、include境界のトランジション指定、デバッグ用の解決結果ダンプを追加。  
   - メモ: サンプル台本とチートシートの記載も追加。

1. **MVP機能優先度テーブル作成** (完了日: 2025-11-30)  
   - 完了内容: 一般的な動画編集機能をMVP/優先高/将来候補に分類し、用途説明付きテーブルとしてdocs/features.mdに整理。  
   - メモ: カテゴリ別にFFmpeg実装可否と難易度を考慮し、MVPで必要な入出力の前提を明文化。

2. **YAMLスキーマ草案作成（シーン/クリップ/トランジション/テキスト）** (完了日: 2025-11-30)  
   - 完了内容: `scenes`,`clips`,`overlays`,`transitions`,`texts`構造でパン&ズーム、Transform、簡易トランジション、テロップを表現するフィールド例を`docs/design/yaml_schema_draft.md`に作成。  
   - メモ: 時間単位ms、必須/デフォルト/将来拡張（meta/easing/anchor/position_mode）を明記。

3. **FFmpegフィルタ対応表ドラフト** (完了日: 2025-11-30)  
   - 完了内容: `zoompan/scale/crop/rotate/overlay/xfade`等を機能別に対応付け、チェーン組み立て例・命名規約・色空間・HW前提を`docs/design/ffmpeg_filter_mapping.md`に整理。  
   - メモ: フィルタはCPU前提、エンコードはHW選択可。透過は`rgba`→最終`yuv420p`で統一。

4. **YAML→中間表現パーサ実装設計** (完了日: 2025-11-30)  
   - 完了内容: Scene/Clip/Transition/TextなどのIRモデル案とバリデーション方針（必須/時間整合/パス解決/デフォルト適用）を`docs/design/parser_and_builder.md`に整理。  
   - メモ: pydantic想定の型チェック、INPUT_ERROR分類、Ken Burns長の調整、相対パスの絶対化を明記。

5. **filter_complex生成器の骨組み設計** (完了日: 2025-11-30)  
   - 完了内容: filter_complex組み立ての責務分離（clip/overlay/text/screen_fx/transition）、ラベル命名規約、中間ラベル例、CPUフィルタ＋HWエンコード方針を`docs/design/parser_and_builder.md`に記載。  
   - メモ: 透過は`rgba`→最終`yuv420p`、FPS/解像度の入口正規化、acrossfade同期を記載。

6. **ドキュメント/README断片更新** (完了日: 2025-11-30)  
   - 完了内容: 設計ドキュメントへの導線を`docs/features.md`に追記し、新規設計資料を整備。  
   - メモ: 設計リンク集としてyaml_schema_draft/ffmpeg_filter_mapping/parser_and_builderを記載。
