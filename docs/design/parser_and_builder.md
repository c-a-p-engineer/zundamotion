# YAML→中間表現パーサとfilter_complex生成器の骨組み設計

## 1. 中間表現（IR）モデル案
- 共通: 時間はms、座標はアンカー基準ピクセル。`id`はユニーク必須。
- `Scene`: `id`, `bg`, `duration_ms`, `clips[]`, `overlays[]`, `transitions[]`, `texts[]`.
- `Clip`: `id`, `src`, `in_ms`, `out_ms`, `transform`(position/scale/rotate_deg/anchor/easing), `kenburns`, `motion.keyframes[]`, `effects[]`, `audio`(loop/volume/fade)。
- `Overlay`: `id`, `src`, `start_ms`, `end_ms`, `blend`(mode/opacity), `transform`, `effects[]`.
- `Transition`: `type`, `to_scene`, `start_ms`, `duration_ms`, `params`(direction/scale_from/color)。
- `Text`: `id`, `content`, `start_ms`, `end_ms`, `position`, `style`(font/size/color/stroke/shadow/align), `animate.in/out`, `effects[]`。

## 2. バリデーション方針
- 型/必須チェック: `scene.id`, `clip.src`, `text.content`, `transition.type`は必須。空文字/None禁止。
- 時間一貫性: `start_ms < end_ms`、`out_ms > in_ms`、Transitionの`start_ms+duration_ms`はシーン長以内を原則（自動クランプ可）。
- パス解決: YAMLの相対パスをプロジェクトルート基準で絶対化。存在チェックし、欠損はINPUT_ERRORで報告。
- デフォルト適用: `anchor(0.5,0.5)`, `easing(ease_in_out)`, `transition.duration_ms(800)`, `text.style.size(48)`などを明示適用。
- 正規化: 座標/スケール/回転/ズームを数値化し、`motion.keyframes`は時系列ソート＋重複時刻排除。Ken Burnsは`out_ms - in_ms`と長さを一致させる。
- エラー分類: スキーマ不整合=INPUT_ERROR、外部I/O=EXTERNAL_IO、内部例外=INTERNAL_BUG。

## 3. 実装スケルトン（パーサ）
```python
from pathlib import Path
from typing import Any, Dict
from pydantic import BaseModel, validator, root_validator

class Transform(BaseModel):
    position: dict[str, float] = {"x": 0.0, "y": 0.0}
    scale: float = 1.0
    rotate_deg: float = 0.0
    anchor: dict[str, float] = {"x": 0.5, "y": 0.5}
    easing: str = "ease_in_out"

class Clip(BaseModel):
    id: str
    src: str
    in_ms: int = 0
    out_ms: int | None = None
    transform: Transform | None = None
    kenburns: dict[str, Any] | None = None
    motion: dict[str, Any] | None = None

    @root_validator
    def check_times(cls, v):
        o = v.get("out_ms")
        i = v.get("in_ms", 0)
        if o is not None and o <= i:
            raise ValueError("out_ms must be greater than in_ms")
        return v

def load_ir(doc: Dict[str, Any], base_dir: Path) -> Dict[str, Any]:
    # 1) defaults適用 → 2) path解決 → 3) pydanticで型検証 → 4) 正規化
    # 戻り値はIR辞書 or dataclassツリー
    ...
```

## 4. filter_complex生成器の骨組み
- 責務分離
  - `build_clip`: 背景正規化、Ken Burns/Transform、効果適用 → `[v_clip]`
  - `build_overlays`: 前景/挿入/テロップPNGを`overlay`で順次合成 → `[v_ovN]`
  - `build_text`: `drawtext`またはPNG→overlay、入退場フェードを付与
  - `build_screen_fx`: 画面揺れ/ブラー等を末尾に適用
  - `build_transition`: `[prev][next]xfade`（offset/duration）、音声`acrossfade`同期
- 命名規約
  - 入力: `[v{scene}]`, `[a{scene}]`
  - 中間: `[v{scene}_bg]`, `[v{scene}_kb]`, `[v{scene}_ov{n}]`, `[v{scene}_txt{m}]`
  - 出力: `[v{scene}_final]` → トランジション → `[vout]`
- 組み立てシーケンス（例: 1シーン）
  1. 背景/素材を`scale/pad/crop`で正規化（`format=yuv420p`基本、透過は`rgba`→最後に`yuv420p`）。
  2. Ken Burns or Transform: `zoompan`/`scale`/`rotate`を組み合わせて`[v_clip]`。
  3. 前景/挿入/テキスト: overlayを時間順に適用、必要なら`enable=between(t,...)`。
  4. 画面効果: shake/blur等を末尾に。
  5. 複数シーンを`xfade`で接続、音声は`acrossfade`で同じ`duration_ms`/`offset`。
- ハードウェア前提
  - フィルタはCPU実行を基本。エンコードのみ`-c:v h264_nvenc`等でHWを選択。
  - 透過素材は`format=rgba`→合成後`format=yuv420p`。FPS/解像度はクリップ入口で揃える。
