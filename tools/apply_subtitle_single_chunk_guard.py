from pathlib import Path

path = Path('zundamotion/components/video/overlays.py')
text = path.read_text(encoding='utf-8')
old = '            if segment_plan.use_segment_mode:\n'
new = '''            if segment_plan.use_segment_mode and len(segment_plan.ranges) > 1:\n'''
if text.count(old) != 1:
    raise RuntimeError(f'expected one segment condition, got {text.count(old)}')
text = text.replace(old, new, 1)
marker = '        self.subtitle_overlay_stats["chunks"] = 1\n'
insert = '''            elif segment_plan.use_segment_mode:\n                logger.info(\n                    "[SubtitleOverlay] Single-chunk segment plan uses full burn "\n                    "to preserve CFR/timestamp stability (base=%.2fs, subtitles=%d)",\n                    float(base_dur),\n                    len(subtitles),\n                )\n\n'''
pos = text.index(marker, text.index('    async def apply_subtitle_overlays('))
text = text[:pos] + insert + text[pos:]
path.write_text(text, encoding='utf-8')
