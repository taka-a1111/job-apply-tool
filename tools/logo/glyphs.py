"""fontsourceのwoffから文字をアウトライン化してSVGパスにする（2026-11-06版。glyphs.py の名前で置いて使う）。
text_path(family, text, size, x, baseline, anchor, tracking) -> (d, width)
family 例: "cinzel@600", "cormorant-garamond@500", "montserrat@600", "shippori-mincho-b1@700",
           "zen-maru-gothic@700", "zen-kaku-gothic-new@700", "m-plus-rounded-1c@800", "noto-bold", "noto-black"
フォントは FONTDIR に npm pack @fontsource/<名前> して展開したもの（例：fonts/fontsource-montserrat-5.x/package/files/...）。
"""
import glob, re
from fontTools.ttLib import TTFont, TTCollection
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

FONTDIR = "/home/claude/logo/fonts"
_cache = {}


def _fonts(family):
    if family not in _cache:
        fs = []
        if family.startswith("noto-"):
            w = family.split("-")[1].capitalize()
            coll = TTCollection(f"/usr/share/fonts/opentype/noto/NotoSansCJK-{w}.ttc")
            f = next(x for x in coll.fonts if "JP" in x["name"].getDebugName(1))
            fs = [(f, f.getBestCmap(), f.getGlyphSet())]
        else:
            name, _, wt = family.partition("@")
            for p in sorted(glob.glob(f"{FONTDIR}/*/package/files/{name}-*-{wt or '400'}-normal.woff")):
                f = TTFont(p)
                fs.append((f, f.getBestCmap(), f.getGlyphSet()))
        _cache[family] = fs
    return _cache[family]


def _glyph(family, ch):
    for f, cmap, gs in _fonts(family):
        if ord(ch) in cmap:
            return f, gs, cmap[ord(ch)]
    raise KeyError(f"{family} has no {ch}")


def text_path(family, text, size, x=0, baseline=0, anchor="start", tracking=0.0):
    items = []
    for ch in text:
        if ch == " ":
            items.append((None, None, None, size * 0.3))
            continue
        f, gs, name = _glyph(family, ch)
        k = size / f["head"].unitsPerEm
        items.append((f, gs, name, f["hmtx"][name][0] * k))
    total = sum(a for *_, a in items) + tracking * size * (len(items) - 1)
    if anchor == "middle":
        x -= total / 2
    elif anchor == "end":
        x -= total
    parts = []
    for f, gs, name, a in items:
        if f is not None:
            k = size / f["head"].unitsPerEm
            pen = SVGPathPen(gs, ntos=lambda v: f"{v:.1f}")
            gs[name].draw(TransformPen(pen, (k, 0, 0, -k, x, baseline)))
            parts.append(pen.getCommands())
        x += a + tracking * size
    return " ".join(parts), total


def bbox(d):
    xs, ys = [], []
    for cmd, args in re.findall(r"([MLHVCQSTZmlhvcqstz])([^MLHVCQSTZmlhvcqstz]*)", d):
        n = [float(v) for v in re.findall(r"-?\d*\.?\d+(?:e-?\d+)?", args)]
        for i in range(0, len(n) - 1, 2):
            xs.append(n[i]); ys.append(n[i + 1])
    return min(xs), min(ys), max(xs), max(ys)


def render(svg, png, svgpath=None, width=1200):
    import cairosvg
    if svgpath:
        open(svgpath, "w").write(svg)
    cairosvg.svg2png(bytestring=svg.encode(), write_to=png, output_width=width)
