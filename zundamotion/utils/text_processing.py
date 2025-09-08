import re
from typing import Tuple


def parse_reading_markup(
    text: str,
    subtitle_reading_display: str = "none",
) -> Tuple[str, str]:
    """
    Parse inline reading markup and return (display_text, tts_text).

    Supported syntaxes:
      - [display|reading]
      - display{reading}

    Args:
      text: Original line text, possibly containing markup.
      subtitle_reading_display: "none" -> display only the display part,
                                 "paren" -> display as "display（reading）".

    Returns:
      Tuple(display_text, tts_text)
    """
    if not isinstance(text, str) or not text:
        return str(text or ""), str(text or "")

    disp = text
    tts = text

    def _replace_bracket(m):
        d = m.group(1)
        r = m.group(2)
        return f"{d}（{r}）" if subtitle_reading_display == "paren" else d

    def _replace_bracket_tts(m):
        return m.group(2)

    # [display|reading]
    bracket_pat = re.compile(r"\[([^\[\]\|]+)\|([^\[\]\|]+)\]")
    disp = bracket_pat.sub(_replace_bracket, disp)
    tts = bracket_pat.sub(_replace_bracket_tts, tts)

    # display{reading}
    # Cautious pattern: non-brace run then {reading}
    curly_pat = re.compile(r"([^{}\n\r\t ]+)\{([^{}]+)\}")

    def _replace_curly(m):
        d = m.group(1)
        r = m.group(2)
        return f"{d}（{r}）" if subtitle_reading_display == "paren" else d

    def _replace_curly_tts(m):
        return m.group(2)

    disp = curly_pat.sub(_replace_curly, disp)
    tts = curly_pat.sub(_replace_curly_tts, tts)

    return disp, tts

