"""Example user plugin demonstrating *overlay-only* shake presets.

This file is intentionally self-contained so that a user can drop only
``plugins/examples/user_simple/plugin.py`` into ``~/.zundamotion/plugins``
and have it discovered without a ``plugin.yaml`` manifest. The plugin is
limited to **foreground overlays** (画面シェイクではなく、前景オーバーレイのみを揺らす)。

Included presets
----------------
- Shake: 正弦波の回転で前景オーバーレイを小刻みに揺らす。
- Soft shake: 既存の ``blur``/``eq`` を足して柔らかい揺れにする。
- Shake + fanfare: 揺れ + 軽い色味調整 + デフォルト効果音を自動付与しやすい形。

Implementation notes
--------------------
- ``PLUGIN_META`` embeds minimal情報 (id/version/kind/provides/capabilities)
  をインライン化し、マニフェストなしでロード可能にしている。
- 各プリセットは ``BUILDERS`` に登録し、``resolve_overlay_effects`` を
  使って既存エフェクトを組み合わせる。
- ``capabilities.default_sound_effects`` に ``shake_fanfare`` 用の効果音を
  宣言しており、スクリプトローダーが未指定時に自動注入する。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from zundamotion.components.video.overlay_effects import resolve_overlay_effects


OverlayParams = Dict[str, Any]


PLUGIN_META = {
    # ユーザプラグインを一意に識別するID。スコープを明示する prefix を推奨。
    "id": "example.overlay.user-simple",
    # 後方互換が崩れる場合は semver で更新する。
    "version": "1.2.0",
    # ``overlay`` であることを宣言する（ビルトイン/ユーザ共通のローダが参照）。
    "kind": "overlay",
    # ローダUIやデバッグログで表示される説明文。
    "description": "User-defined sample overlay plugin focusing on shake presets",
    # 提供するエフェクト（type 名）を列挙する。台本では ``type: shake`` のように参照。
    "provides": ["shake", "soft_shake", "shake_fanfare"],
    # 追加能力を宣言するセクション。ここではデフォルト効果音を定義し、
    # スクリプトローダーが sound_effects 未指定の場合に自動で注入する。
    "capabilities": {
        "default_sound_effects": {
            "shake_fanfare": [
                {
                    "path": "assets/se/rap_fanfare.mp3",
                    "start_time": 0.0,
                    "volume": 0.7,
                }
            ]
        }
    },
    "enabled": True,
}


def _build_shake(params: OverlayParams) -> List[str]:
    """Minimal shake effect using a sinusoidal rotation.

    Parameters
    ----------
    amplitude_deg: float
        回転の振幅。大きくするほど揺れが激しくなる。
    frequency_hz: float
        1秒あたりの揺れ周期。値を上げると速く揺れる。
    """

    amplitude_deg = float(params.get("amplitude_deg", 2.0))
    frequency_hz = float(params.get("frequency_hz", 3.0))
    angle_expr = f"({amplitude_deg}*PI/180)*sin(2*PI*{frequency_hz}*t)"
    return [f"rotate={angle_expr}:fillcolor=none"]


def _build_soft_shake(params: OverlayParams) -> List[str]:
    """Preset that layers a subtle blur and tint on top of shake.

    既存の ``blur`` と ``eq`` を組み合わせ、揺れつつ柔らかい発光を付与する。
    個別パラメータが未指定の場合は控えめなデフォルトを採用。
    """

    blur_sigma = params.get("blur", 6.0)
    exposure = params.get("exposure", 0.04)
    return resolve_overlay_effects(
        [
            {"type": "shake", "amplitude_deg": params.get("amplitude_deg", 1.6), "frequency_hz": params.get("frequency_hz", 2.4)},
            {"type": "blur", "sigma": blur_sigma},
            {"type": "eq", "brightness": exposure, "saturation": 0.08},
        ]
    )


def _build_shake_fanfare(_: OverlayParams) -> Optional[List[str]]:
    """Fixed-value shake preset that pairs well with a short fanfare SFX.

    値は固定にしており、音付きの演出を素早く再利用したいケース向け。
    ``capabilities.default_sound_effects`` で効果音を宣言済みなので、
    台本側で sound_effects を書かなくても自動付与される。
    """

    filters = resolve_overlay_effects(
        [
            {"type": "shake", "amplitude_deg": 2.5, "frequency_hz": 3.4},
            {"type": "eq", "contrast": 0.06, "saturation": 0.05},
        ]
    )
    return filters or None


BUILDERS = {
    "shake": _build_shake,
    "soft_shake": _build_soft_shake,
    "shake_fanfare": _build_shake_fanfare,
}
