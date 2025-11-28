import re
from pathlib import Path
from typing import Any, Dict

from ...exceptions import ValidationError


BACKGROUND_FIT_CHOICES = {
    "stretch",
    "contain",
    "cover",
    "fit_width",
    "fit_height",
}

ANCHOR_CHOICES = {
    "top_left",
    "top_center",
    "top_right",
    "middle_left",
    "middle_center",
    "middle_right",
    "bottom_left",
    "bottom_center",
    "bottom_right",
}

HEX_COLOR_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
RGB_COLOR_RE = re.compile(r"^rgba?\(.*\)$", re.IGNORECASE)
HSL_COLOR_RE = re.compile(r"^hsla?\(.*\)$", re.IGNORECASE)


def _is_valid_color_string(value: str) -> bool:
    if HEX_COLOR_RE.match(value):
        return True
    if RGB_COLOR_RE.match(value) or HSL_COLOR_RE.match(value):
        return True
    if value.lower().startswith("0x"):
        try:
            int(value[2:], 16)
            return True
        except ValueError:
            return False
    if value.isalpha():
        return True
    return False


def _validate_background_options(
    cfg: Dict[str, Any], container_id: str
) -> None:
    fit = cfg.get("fit")
    if fit is not None:
        if not isinstance(fit, str):
            raise ValidationError(
                f"Background fit for {container_id} must be a string."
            )
        if fit.lower() not in BACKGROUND_FIT_CHOICES:
            raise ValidationError(
                f"Background fit for {container_id} must be one of {sorted(BACKGROUND_FIT_CHOICES)}."
            )

    fill_color = cfg.get("fill_color")
    if fill_color is not None:
        if not isinstance(fill_color, str) or not _is_valid_color_string(fill_color):
            raise ValidationError(
                f"Background fill_color for {container_id} must be a valid color string."
            )

    anchor = cfg.get("anchor")
    if anchor is not None:
        if not isinstance(anchor, str) or anchor not in ANCHOR_CHOICES:
            raise ValidationError(
                f"Background anchor for {container_id} must be one of {sorted(ANCHOR_CHOICES)}."
            )

    position = cfg.get("position")
    if position is not None:
        if not isinstance(position, dict):
            raise ValidationError(
                f"Background position for {container_id} must be a dictionary."
            )
        for axis in ("x", "y"):
            val = position.get(axis)
            if val is None:
                continue
            if not isinstance(val, (int, float, str)):
                raise ValidationError(
                    f"Background position '{axis}' for {container_id} must be a number or string expression."
                )

def _validate_fg_overlays(container: Dict[str, Any], container_id: str) -> None:
    """Validate foreground overlay configuration for a scene or line.

    Parameters
    ----------
    container: Dict[str, Any]
        Dictionary potentially containing ``fg_overlays``.
    container_id: str
        Identifier used in error messages (e.g., "scene 'id'" or "scene 'id', line 2").

    Raises
    ------
    ValidationError
        If any foreground overlay entry is invalid.
    """

    fg_overlays = container.get("fg_overlays")
    if fg_overlays is None:
        return

    if not isinstance(fg_overlays, list):
        raise ValidationError(
            f"Foreground overlays for {container_id} must be a list."
        )

    for fg_idx, fg in enumerate(fg_overlays):
        if not isinstance(fg, dict):
            raise ValidationError(
                f"Foreground overlay at {container_id}, index {fg_idx} must be a dictionary."
            )

        fg_id = fg.get("id", f"fg_{fg_idx}")
        src = fg.get("src")
        if not src or not isinstance(src, str):
            raise ValidationError(
                f"Foreground overlay '{fg_id}' in {container_id} must have a string 'src' path."
            )
        src_path = Path(src)
        if not src_path.exists() or not src_path.is_file():
            raise ValidationError(
                f"Foreground overlay '{fg_id}' source file '{src}' not found for {container_id}."
            )

        mode = fg.get("mode")
        if mode not in {"overlay", "blend", "chroma", "alpha"}:
            raise ValidationError(
                f"Foreground overlay '{fg_id}' in {container_id} has invalid mode '{mode}'."
            )

        if mode == "blend":
            blend_mode = fg.get("blend_mode")
            if blend_mode not in {"screen", "add", "multiply", "lighten"}:
                raise ValidationError(
                    f"Foreground overlay '{fg_id}' in {container_id} requires a valid 'blend_mode'."
                )

        if mode == "chroma":
            chroma = fg.get("chroma")
            if not isinstance(chroma, dict):
                raise ValidationError(
                    f"Foreground overlay '{fg_id}' in {container_id} must have a 'chroma' dictionary."
                )
            key_color = chroma.get("key_color")
            if not isinstance(key_color, str) or not key_color.startswith("#"):
                raise ValidationError(
                    f"Foreground overlay '{fg_id}' in {container_id} has invalid chroma key_color '{key_color}'."
                )
            similarity = chroma.get("similarity", 0.1)
            blend = chroma.get("blend", 0.0)
            if not isinstance(similarity, (int, float)) or not (0.0 <= similarity <= 1.0):
                raise ValidationError(
                    f"Foreground overlay '{fg_id}' in {container_id} chroma similarity must be between 0.0 and 1.0."
                )
            if not isinstance(blend, (int, float)) or not (0.0 <= blend <= 1.0):
                raise ValidationError(
                    f"Foreground overlay '{fg_id}' in {container_id} chroma blend must be between 0.0 and 1.0."
                )

        opacity = fg.get("opacity")
        if opacity is not None and (
            not isinstance(opacity, (int, float)) or not (0.0 <= opacity <= 1.0)
        ):
            raise ValidationError(
                f"Foreground overlay '{fg_id}' in {container_id} opacity must be between 0.0 and 1.0."
            )

        position = fg.get("position", {})
        if not isinstance(position, dict):
            raise ValidationError(
                f"Foreground overlay '{fg_id}' in {container_id} position must be a dictionary."
            )
        for axis in ("x", "y"):
            val = position.get(axis, 0)
            if not isinstance(val, (int, float)):
                raise ValidationError(
                    f"Foreground overlay '{fg_id}' in {container_id} position '{axis}' must be a number."
                )

        scale = fg.get("scale", {})
        if not isinstance(scale, dict):
            raise ValidationError(
                f"Foreground overlay '{fg_id}' in {container_id} scale must be a dictionary."
            )
        for dim in ("w", "h"):
            val = scale.get(dim)
            if val is not None and (not isinstance(val, (int, float)) or val <= 0):
                raise ValidationError(
                    f"Foreground overlay '{fg_id}' in {container_id} scale '{dim}' must be a positive number."
                )
        keep_aspect = scale.get("keep_aspect")
        if keep_aspect is not None and not isinstance(keep_aspect, bool):
            raise ValidationError(
                f"Foreground overlay '{fg_id}' in {container_id} scale 'keep_aspect' must be a boolean."
            )

        timing = fg.get("timing", {})
        if not isinstance(timing, dict):
            raise ValidationError(
                f"Foreground overlay '{fg_id}' in {container_id} timing must be a dictionary."
            )
        start = timing.get("start", 0.0)
        if not isinstance(start, (int, float)) or start < 0:
            raise ValidationError(
                f"Foreground overlay '{fg_id}' in {container_id} timing start must be non-negative."
            )
        duration = timing.get("duration")
        if duration is not None and (
            not isinstance(duration, (int, float)) or duration <= 0
        ):
            raise ValidationError(
                f"Foreground overlay '{fg_id}' in {container_id} timing duration must be positive."
            )
        loop = timing.get("loop")
        if loop is not None and not isinstance(loop, bool):
            raise ValidationError(
                f"Foreground overlay '{fg_id}' in {container_id} timing loop must be a boolean."
            )

        fps = fg.get("fps")
        if fps is not None and (not isinstance(fps, int) or fps <= 0):
            raise ValidationError(
                f"Foreground overlay '{fg_id}' in {container_id} fps must be a positive integer."
            )

        preserve_color = fg.get("preserve_color")
        if preserve_color is not None and not isinstance(preserve_color, bool):
            raise ValidationError(
                f"Foreground overlay '{fg_id}' in {container_id} preserve_color must be a boolean."
            )

        # Optional effects list (order-preserving)
        effects = fg.get("effects")
        if effects is not None:
            if not isinstance(effects, list):
                raise ValidationError(
                    f"Foreground overlay '{fg_id}' in {container_id} effects must be a list."
                )
            for eff_idx, eff in enumerate(effects):
                if isinstance(eff, str):
                    continue
                if not isinstance(eff, dict):
                    raise ValidationError(
                        f"Foreground overlay '{fg_id}' in {container_id} effects[{eff_idx}] must be a string or dictionary."
                    )
                eff_type = eff.get("type")
                if not isinstance(eff_type, str) or not eff_type:
                    raise ValidationError(
                        f"Foreground overlay '{fg_id}' in {container_id} effects[{eff_idx}] requires a string 'type'."
                    )


def _validate_plugins_config(cfg: Dict[str, Any]) -> None:
    if not isinstance(cfg, dict):
        raise ValidationError("'plugins' section must be a dictionary when provided.")
    enabled = cfg.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise ValidationError("'plugins.enabled' must be a boolean.")

    for key in ("paths", "allow", "deny"):
        val = cfg.get(key)
        if val is None:
            continue
        if not isinstance(val, list):
            raise ValidationError(f"'plugins.{key}' must be a list when provided.")
        for idx, item in enumerate(val):
            if not isinstance(item, str):
                raise ValidationError(
                    f"'plugins.{key}[{idx}]' must be a string path or ID."
                )


def validate_config(config: Dict[str, Any]) -> None:
    """Validate the loaded configuration and script data.

    Raises
    ------
    ValueError
        If the basic structure is invalid.
    ValidationError
        If domain-specific checks fail.
    """
    plugins_cfg = config.get("plugins")
    if plugins_cfg is not None:
        _validate_plugins_config(plugins_cfg)

    video_cfg = config.get("video", {}) or {}
    fit_mode = video_cfg.get("background_fit")
    if fit_mode is not None:
        if not isinstance(fit_mode, str):
            raise ValidationError("'video.background_fit' must be a string.")
        if fit_mode.lower() not in BACKGROUND_FIT_CHOICES:
            raise ValidationError(
                f"'video.background_fit' must be one of {sorted(BACKGROUND_FIT_CHOICES)}."
            )

    background_cfg = config.get("background", {}) or {}
    if background_cfg:
        if not isinstance(background_cfg, dict):
            raise ValidationError("'background' section must be a dictionary.")
        _validate_background_options(background_cfg, "global background")

    script = config.get("script")
    if not isinstance(script, dict):
        raise ValueError("Script data must be a dictionary under the 'script' key.")

    defaults = config.get("defaults", {})
    if defaults:
        cp = defaults.get("characters_persist")
        if cp is not None and not isinstance(cp, bool):
            raise ValidationError(
                "'defaults.characters_persist' must be a boolean."
            )

    transitions_cfg = config.get("transitions")
    if transitions_cfg is not None:
        if not isinstance(transitions_cfg, dict):
            raise ValidationError(
                "'transitions' section must be a dictionary when provided."
            )
        wait_padding = transitions_cfg.get("wait_padding_seconds")
        if wait_padding is not None:
            if not isinstance(wait_padding, (int, float)):
                raise ValidationError(
                    "'transitions.wait_padding_seconds' must be a number."
                )
            if wait_padding < 0:
                raise ValidationError(
                    "'transitions.wait_padding_seconds' must be non-negative."
                )

    scenes = script.get("scenes")
    if not isinstance(scenes, list):
        raise ValueError("Script must contain a 'scenes' list.")

    for scene_idx, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            raise ValidationError(f"Scene at index {scene_idx} must be a dictionary.")

        scene_id = scene.get("id", f"scene_{scene_idx}")
        scene_background_cfg = scene.get("background")
        if scene_background_cfg is not None:
            if not isinstance(scene_background_cfg, dict):
                raise ValidationError(
                    f"Scene '{scene_id}' background must be a dictionary."
                )
            _validate_background_options(
                scene_background_cfg, f"scene '{scene_id}' background"
            )
        cp = scene.get("characters_persist")
        if cp is not None and not isinstance(cp, bool):
            raise ValidationError(
                f"Scene '{scene_id}' characters_persist must be a boolean."
            )

        lines = scene.get("lines")
        if not isinstance(lines, list):
            raise ValidationError(f"Scene '{scene_id}' must contain a 'lines' list.")

        # Validate background image/video path
        bg_path = scene.get("bg", config.get("background", {}).get("default"))
        if bg_path:
            bg_full_path = Path(bg_path)
            if not bg_full_path.exists():
                raise ValidationError(
                    f"Background file '{bg_path}' for scene '{scene_id}' does not exist."
                )
            if not bg_full_path.is_file():
                raise ValidationError(
                    f"Background path '{bg_path}' for scene '{scene_id}' is not a file."
                )

        # Validate scene transition
        transition_config = scene.get("transition")
        if transition_config:
            if not isinstance(transition_config, dict):
                raise ValidationError(
                    f"Transition configuration for scene '{scene_id}' must be a dictionary."
                )
            transition_type = transition_config.get("type")
            if not transition_type:
                raise ValidationError(
                    f"Transition for scene '{scene_id}' must have a 'type'."
                )
            if not isinstance(transition_type, str):
                raise ValidationError(
                    f"Transition type for scene '{scene_id}' must be a string, but got {type(transition_type).__name__}."
                )

            transition_duration = transition_config.get("duration")
            if transition_duration is None:
                raise ValidationError(
                    f"Transition for scene '{scene_id}' must have a 'duration'."
                )
            if not isinstance(transition_duration, (int, float)):
                raise ValidationError(
                    f"Transition duration for scene '{scene_id}' must be a number, but got {type(transition_duration).__name__}."
                )
            if transition_duration <= 0:
                raise ValidationError(
                    f"Transition duration for scene '{scene_id}' must be positive, but got {transition_duration}."
                )

        # Validate BGM path
        bgm_config = scene.get("bgm")
        if bgm_config:
            if not isinstance(bgm_config, dict):
                raise ValidationError(
                    f"BGM configuration for scene '{scene_id}' must be a dictionary."
                )
            bgm_path = bgm_config.get("path")
            if bgm_path:
                bgm_full_path = Path(bgm_path)
                if not bgm_full_path.exists():
                    raise ValidationError(
                        f"BGM file '{bgm_path}' for scene '{scene_id}' does not exist."
                    )
                if not bgm_full_path.is_file():
                    raise ValidationError(
                        f"BGM path '{bgm_path}' for scene '{scene_id}' is not a file."
                    )

            # Validate bgm_volume range
            bgm_volume = bgm_config.get("volume")
            if bgm_volume is not None and not (0.0 <= bgm_volume <= 1.0):
                raise ValidationError(
                    f"BGM volume for scene '{scene_id}' must be between 0.0 and 1.0, but got {bgm_volume}."
                )

        # Validate foreground overlays
        _validate_fg_overlays(scene, scene_id)

        # Validate assets defined in the top-level 'assets' section
        top_level_assets = config.get("assets", {})
        for asset_key, asset_path_str in top_level_assets.items():
            asset_full_path = Path(asset_path_str)
            if not asset_full_path.exists():
                raise ValidationError(
                    f"Asset '{asset_key}' path '{asset_path_str}' does not exist."
                )
            if not asset_full_path.is_file():
                raise ValidationError(
                    f"Asset '{asset_key}' path '{asset_path_str}' is not a file."
                )

        for line_idx, line in enumerate(lines):
            if not isinstance(line, dict):
                raise ValidationError(
                    f"Line at scene '{scene_id}', index {line_idx} must be a dictionary."
                )

            line_background = line.get("background")
            if line_background is not None:
                if not isinstance(line_background, dict):
                    raise ValidationError(
                        f"Background override for scene '{scene_id}', line {line_idx} must be a dictionary."
                    )
                _validate_background_options(
                    line_background,
                    f"scene '{scene_id}', line {line_idx} background",
                )

            _validate_fg_overlays(line, f"scene '{scene_id}', line {line_idx}")

            reset_flag = line.get("reset_characters")
            if reset_flag is not None and not isinstance(reset_flag, bool):
                raise ValidationError(
                    f"Line at scene '{scene_id}', index {line_idx} reset_characters must be a boolean."
                )

            # 'text' or 'wait' key must exist
            if "text" not in line and "wait" not in line:
                raise ValidationError(
                    f"Line at scene '{scene_id}', index {line_idx} must contain 'text' or 'wait'."
                )

            if "text" in line and "wait" in line:
                raise ValidationError(
                    f"Line at scene '{scene_id}', index {line_idx} cannot contain both 'text' and 'wait'."
                )

            if "wait" in line:
                wait_value = line["wait"]
                if isinstance(wait_value, (int, float)):
                    if wait_value <= 0:
                        raise ValidationError(
                            f"Wait duration for scene '{scene_id}', line {line_idx} must be positive, but got {wait_value}."
                        )
                elif isinstance(wait_value, dict):
                    duration = wait_value.get("duration")
                    if duration is None:
                        raise ValidationError(
                            f"Wait dictionary for scene '{scene_id}', line {line_idx} must contain 'duration'."
                        )
                    if not isinstance(duration, (int, float)):
                        raise ValidationError(
                            f"Wait duration for scene '{scene_id}', line {line_idx} must be a number, but got {type(duration).__name__}."
                        )
                    if duration <= 0:
                        raise ValidationError(
                            f"Wait duration for scene '{scene_id}', line {line_idx} must be positive, but got {duration}."
                        )
                else:
                    raise ValidationError(
                        f"Wait value for scene '{scene_id}', line {line_idx} must be a number or a dictionary."
                    )
                continue  # Skip other validations for wait steps

            # Validate speed range
            speed = line.get("speed")
            if speed is not None and not (0.5 <= speed <= 2.0):
                raise ValidationError(
                    f"Speech speed for scene '{scene_id}', line {line_idx} must be between 0.5 and 2.0, but got {speed}."
                )

            # Validate pitch range
            pitch = line.get("pitch")
            if pitch is not None and not (-1.0 <= pitch <= 1.0):
                raise ValidationError(
                    f"Speech pitch for scene '{scene_id}', line {line_idx} must be between -1.0 and 1.0, but got {pitch}."
                )

            # Validate speaker_id type
            speaker_id = line.get("speaker_id")
            if speaker_id is not None and not isinstance(speaker_id, int):
                raise ValidationError(
                    f"Speaker ID for scene '{scene_id}', line {line_idx} must be an integer, but got {type(speaker_id).__name__}."
                )

            # Validate sound_effects
            sound_effects = line.get("sound_effects")
            if sound_effects:
                if not isinstance(sound_effects, list):
                    raise ValidationError(
                        f"Sound effects for scene '{scene_id}', line {line_idx} must be a list."
                    )
                for se_idx, se in enumerate(sound_effects):
                    if not isinstance(se, dict):
                        raise ValidationError(
                            f"Sound effect at scene '{scene_id}', line {line_idx}, index {se_idx} must be a dictionary."
                        )
                    se_path = se.get("path")
                    if not se_path:
                        raise ValidationError(
                            f"Sound effect at scene '{scene_id}', line {line_idx}, index {se_idx} must have a 'path'."
                        )
                    se_full_path = Path(se_path)
                    if not se_full_path.exists():
                        raise ValidationError(
                            f"Sound effect file '{se_path}' for scene '{scene_id}', line {line_idx}, index {se_idx} does not exist."
                        )
                    if not se_full_path.is_file():
                        raise ValidationError(
                            f"Sound effect path '{se_path}' for scene '{scene_id}', line {line_idx}, index {se_idx} is not a file."
                        )

                    se_start_time = se.get("start_time", 0.0)
                    if not isinstance(se_start_time, (int, float)):
                        raise ValidationError(
                            f"Sound effect start_time for scene '{scene_id}', line {line_idx}, index {se_idx} must be a number, but got {type(se_start_time).__name__}."
                        )
                    if se_start_time < 0:
                        raise ValidationError(
                            f"Sound effect start_time for scene '{scene_id}', line {line_idx}, index {se_idx} must be non-negative, but got {se_start_time}."
                        )

                    se_volume = se.get("volume", 1.0)
                    if not isinstance(se_volume, (int, float)):
                        raise ValidationError(
                            f"Sound effect volume for scene '{scene_id}', line {line_idx}, index {se_idx} must be a number, but got {type(se_volume).__name__}."
                        )
                    if not (0.0 <= se_volume <= 1.0):
                        raise ValidationError(
                            f"Sound effect volume for scene '{scene_id}', line {line_idx}, index {se_idx} must be between 0.0 and 1.0, but got {se_volume}."
                        )
