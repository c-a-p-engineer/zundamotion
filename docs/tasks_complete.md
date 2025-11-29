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
