# ユーザーサンプルプラグイン実装ガイド（overlay shake 編）

本ドキュメントは `plugins/examples/user_simple/plugin.py` を題材に、
マニフェスト無しでドロップインできる前景オーバーレイ専用プラグインの
実装方法をまとめたものです。画面全体のシェイクとは異なり、
**前景オーバーレイだけを揺らす**シナリオを想定しています。

## 1. プラグインの基本形
- 単一ファイル `plugin.py` に `PLUGIN_META` と `BUILDERS` を同居させる。
- `PLUGIN_META` に `id`/`version`/`kind`/`provides`/`capabilities` を記載。
  - `kind: overlay` を宣言するとオーバーレイとして解決される。
  - `provides` にエフェクト type 名（例: `shake`）を並べ、台本から参照できるようにする。
  - `capabilities.default_sound_effects` にプリセットごとのデフォルト効果音を
    定義すると、台本が `sound_effects` 未指定でもローダが自動付与する。
- `BUILDERS` は `type` 名をキーに、FFmpeg フィルタ文字列リストを返す関数を登録する。

### PLUGIN_META の例
```python
PLUGIN_META = {
    "id": "example.overlay.user-simple",
    "version": "1.2.0",
    "kind": "overlay",
    "description": "User-defined sample overlay plugin focusing on shake presets",
    "provides": ["shake", "soft_shake", "shake_fanfare"],
    "capabilities": {
        "default_sound_effects": {
            "shake_fanfare": [
                {"path": "assets/se/rap_fanfare.mp3", "start_time": 0.0, "volume": 0.7}
            ]
        }
    },
    "enabled": True,
}
```

## 2. 実装済みプリセットの構成
`plugins/examples/user_simple/plugin.py` には揺れ系の3プリセットを実装しています。

| プリセット | 内容 | パラメータ | 用途 |
| --- | --- | --- | --- |
| `shake` | 正弦波回転による最小限の揺れ | `amplitude_deg` / `frequency_hz` | シンプルな揺れ演出 |
| `soft_shake` | `shake` + `blur` + `eq` で柔らかい光を付加 | 上記 + `blur`/`exposure` | 優しい揺れを出したいとき |
| `shake_fanfare` | 固定値の揺れ + 軽い色味調整。`default_sound_effects` で効果音を自動付与 | パラメータ固定 | 音付きの演出を即席で使いたいとき |

各プリセットは `resolve_overlay_effects` を介してビルトインのエフェクトを再利用することで、
新規コードを最小に保ちつつ表現力を高めています。

## 3. 配置と検出
1. ファイルを `~/.zundamotion/plugins/user_simple/plugin.py` にコピーするだけでOK。
   - `plugin.yaml` は不要。`PLUGIN_META` がインラインでロードされる。
2. アプリを再起動するとプラグインが検出され、台本で `type: shake` 等が利用可能。

## 4. サンプル台本での使い方
`scripts/sample_user_overlay_plugin.yaml` は以下を実演します。
- `shake`: 素の揺れ。
- `soft_shake`: ぼかし＆軽い発光付き揺れ。
- `shake_fanfare`: 音が自動付与される揺れ＋色味プリセット（台本には `sound_effects` を書かない）。

## 5. 拡張のヒント
- 効果音を別ファイルにしたい場合は `default_sound_effects` のパスを書き換えるだけで済む。
- 追加プリセットを作る場合は、`BUILDERS` に関数を足し、`provides` と `capabilities` を更新する。
- 画面全体を揺らす用途とは分離したい場合、説明文に「前景のみ」を明記し、
  台本側も overlay セクションに限定して利用する。

## 6. 既知の制約
- このプラグインは前景オーバーレイ専用。背景シェイクや3D変形は対象外。
- 効果音の自動付与は「未指定の場合のみ」機能する。台本に `sound_effects` を書けばそれが優先される。

## 7. トラブルシュート
- プラグインが見つからない: ファイルパスを `~/.zundamotion/plugins/**/plugin.py` に置いているか確認。
- 透過が失われる: 既知の透明度維持修正済みビルドを使用しているか確認し、`mode: overlay` を設定する。

