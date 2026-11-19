"""Wrap the map's SVG in a page of its own size, so the PDF is one sheet.

The SVG is inlined rather than linked, which keeps it vector in the PDF:
text stays selectable and it does not blur when anyone zooms in.
"""
import io, re

ROOT = r"C:\Users\vedul\OneDrive\Desktop\term 2\Sprinto"
svg = io.open(ROOT + r"\components-map-v10.svg", encoding="utf-8").read()

w = int(re.search(r'width="(\d+)"', svg).group(1))
h = int(re.search(r'height="(\d+)"', svg).group(1))
# CSS inches at 96 px/in, capped at 22in wide so it opens at a sane zoom.
scale = min(1.0, 22 * 96 / w)
pw, ph = w * scale / 96, h * scale / 96

html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Sprinto components map v10</title>
<style>
  @page {{ size: {pw:.2f}in {ph:.2f}in; margin: 0; }}
  html, body {{ margin: 0; padding: 0; background: #fff; }}
  svg {{ display: block; width: {pw:.2f}in; height: {ph:.2f}in; }}
</style></head><body>
{svg}
</body></html>
"""
out = ROOT + r"\_mapprint.html"
io.open(out, "w", encoding="utf-8").write(html)
print(f"{out}\npage {pw:.2f}in x {ph:.2f}in from {w}x{h}px")
