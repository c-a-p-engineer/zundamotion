# エフェクト拡張性再設計プラン (更新版)

## 背景 / 課題
- `OverlayMixin._build_effect_filters` にエフェクト別の分岐が直列に書かれ、追加ごとに条件分岐が肥大化している。
- パラメータ検証がなく、YAML の typo や型ずれが実行時まで検知されにくい。
- エフェクト間の依存・順序・スケール/色空間前提が明文化されておらず、複数エフェクト併用時の破綻リスクがある。
- 仕様の参照点がコードのみで、利用者/実装者向けのドキュメントとサンプルが不足している。

## 目的 / 非目的
- 目的: エフェクト追加の変更範囲を "エフェクト定義" に閉じ込め、OCP に近づける。入力検証とデフォルト補完を型安全に行い、順序・適用条件を明示化してテスト容易性を上げる。サンプル台本とドキュメントを揃えてオンボーディングを短縮する。
- 非目的: FFmpeg 実行パスの最適化や GPU パイプラインの導入は別イニシアティブとする（後続のパフォーマンス検証で扱う）。

## 設計原則 / 方針
- **Registry + Strategy**: `EffectRegistry` にエフェクト名→ビルダーを登録し、分岐を排除。
- **型/スキーマ検証**: `pydantic` または dataclass + `jsonschema` でエフェクトごとに型/範囲チェック（既存依存を前提に追加依存は最小）。
- **責務分離**: FFmpeg フィルタ文字列生成と設定検証/デフォルト補完を分離。オーバーレイ本体はビルダーの結果のみを連結。
- **順序制御**: エフェクトリストを指定順で尊重しつつ、`order`/`phase` メタデータで前後制御を許容（デフォルトは指定順）。
- **観測性と安全なフォールバック**: フィルタ構成を DEBUG/JSON ログに残し、未サポートフィルタは警告ログ＋スキップで安全停止を優先。
- **拡張ポイント公開**: 新規エフェクト追加手順・検証観点を本ドキュメントに明示し、サンプル台本を同梱する。

## 主要コンポーネント案
- `zundamotion/components/video/effects/base.py`
  - `EffectContext`: fps/色空間/スケール/動画長など共通メタデータを保持。
  - `EffectBuilder` Protocol: `build(params: EffectParams, ctx: EffectContext) -> EffectFilter`。
  - `EffectFilter`: `filters: list[str]`, `order_hint: int|None` を持つ単純 DTO。
- `zundamotion/components/video/effects/registry.py`
  - `EffectRegistry` シングルトン/モジュールレベル辞書。
  - `register(name: str, builder: EffectBuilder)` / `build(name, params, ctx)` を提供。
  - 未知エフェクトは型付き例外 `UnknownEffectError` を早期スロー。
- `zundamotion/components/video/effects/schemas.py`
  - エフェクトごとの Pydantic モデル例: `BlurEffect`, `EqEffect`, `RotateEffect` など。
  - 共通フィールド: `type`, `enable`, `order`, `when` (条件式/時間範囲) をオプションで持つ。
- `zundamotion/components/video/effects/builtin/*.py`
  - 各エフェクト専用ビルダー。入力モデル→FFmpeg フィルタ文字列を生成。
  - 例: `blur.py`, `vignette.py`, `color.py (eq/hue/curves)`, `unsharp.py`, `lut3d.py`, `rotate.py`。
- `OverlayMixin._build_effect_filters`
  - 役割を `EffectRegistry` 呼び出しに限定し、合成順序制御と enable 条件の判定のみ担当。

## データフロー(案)
1. YAML `effects` 配列を読み込み、要素ごとに `EffectRegistry.build` に委譲。
2. `EffectRegistry` は名前から対応モデルを選択し、バリデーション→デフォルト補完→`EffectFilter` 生成。
3. `OverlayMixin` は `EffectFilter.filters` を `steps` に extend。`order_hint` がある場合は安定ソート。
4. `enable` 条件や `when` (時刻条件) がある場合、`enable='between(...)'` などをビルダーが組み立て。
5. 生成したフィルタ列をログ出力し、E2E テストでフィルタ文字列をスナップショット確認。

## マイルストーンとスコープ
- **M1: 土台追加** (registry + DTO + バリデーション枠組み)
  - Deliverable: `EffectRegistry`, `EffectContext`, `EffectFilter` の導入と呼び出し箇所差し替え。
- **M2: 既存エフェクト移植** (blur/vignette/eq/hue/curves/unsharp/lut3d/rotate)
  - Deliverable: 各エフェクトのビルダー化、旧分岐の削除、互換パス。
- **M3: 検証強化と観測性**
  - Deliverable: Pydantic での範囲チェック、未知キー拒否、DEBUG/JSON ログ、`ffmpeg` サポート検出フック。
- **M4: サンプル・ドキュメント**
  - Deliverable: サンプル台本（registry 検証用）、`README`/`docs/script_samples.md` 更新、追従ガイド。
- **M5: リグレッションと切替**
  - Deliverable: ユニット/統合テスト充実、既存 YAML の互換確認、非推奨パラメータの警告ログ。

## 字幕エフェクトへの適用方針
- テキスト固有のエフェクト（バウンス等）も同一の registry + builder 形式に寄せ、`SubtitleEffectContext` を共有する。
- `resolve_subtitle_effects` で順序を保持しつつ未知タイプは警告の上スキップ、ビルダー例外も握りつぶして耐障害性を確保する。
- 新規ビルダー追加時は `tests/test_subtitle_effects_registry.py` にスナップショット/エラー系テストを追加し、`docs/script_samples.md` で使用例を更新する。

## テスト戦略 (最低限)
- **ユニット**: 各ビルダーの入力→フィルタ文字列スナップショット、検証エラー確認、order ソート確認。
- **統合**: サンプル YAML（`scripts/sample_effects_registry.yaml`）で複数エフェクトを併用し、生成 `ffmpeg` コマンド文字列を検証（実行はモック/スタブ）。
- **回帰**: 既存サンプル(`scripts/sample_*`)が従来通り動くことを確認。

## 移行時の既知リスクと緩和
- **FFmpeg バージョン差異**: 使用フィルタのサポート検知を `ffmpeg_capabilities` で行い、未サポート時は警告＋スキップ。
- **性能劣化**: フィルタ連結数増による CPU 負荷。並列ジョブ数調整と事前メディア最適化で緩和。
- **設定破壊**: バリデーション強化により既存 YAML が落ちる可能性。非推奨パラメータは警告ログ＋互換経路を用意し、段階的廃止。

## 実装ガイド / 追加時の手順チェックリスト
1. `schemas.py` に新エフェクトの入力モデルを追加し、範囲チェックとデフォルト値を定義する（未知キー拒否）。
2. `builtin/<name>.py` にビルダーを追加し、`EffectFilter(filters=["..."])` を返す。`order_hint` が必要ならここで指定。
3. `registry.py` へ `register("<name>", builder)` を追加し、既存 YAML の文字列/エイリアスを列挙する。
4. ログ出力にフィルタ名と主要パラメータを含める（JSON ログ対応）。
5. ユニットテスト: 入力→フィルタ文字列スナップショット、検証エラー（境界値/未知キー）、`order` の安定ソート。
6. ドキュメント/サンプル: `docs/script_samples.md` と `scripts/` に例を追記し、チートシートとのリンクを更新する。

## 今後の拡張余地
- `zoompan` 等のモーション系、`color grading LUT` のキャッシュ、`effect presets` の追加。
- CLI フラグ `--effect-preset <name>` で共通スタイルを適用する仕組み。
- effect ごとの GPU 対応/色空間前提を `EffectContext` に反映し、最適フィルタを選択。
