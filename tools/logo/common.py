"""ロゴシートの共通部品（2026-11-06版）。glyphs_v2.py と同じフォルダに置いて使う。
lines: [(family, text, size, color, tracking), ...]  color は '#hex' か {'base':'#..', 文字番号: '#..'}
"""
import math, sys
sys.path.insert(0, "/home/claude/logo")
from glyphs import text_path, bbox, render

OUT = "/home/claude/logo/out"


def P(pts):
    return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + " Z"


def block(lines, x, y_top, anchor="start", gaps=None):
    gaps = gaps or []
    parts, y, maxw = [], y_top, 0
    for i, (fam, txt, size, color, trk) in enumerate(lines):
        d, w = text_path(fam, txt, size, 0, 0, tracking=trk)
        x0, y0, x1, y1 = bbox(d)
        dx = {"start": x - x0, "middle": x - (x0 + x1) / 2, "end": x - x1}[anchor]
        dy = y - y0
        if isinstance(color, dict):
            cx = 0
            for j, ch in enumerate(txt):
                dj, wj = text_path(fam, ch, size, cx, 0)
                if ch != " ":
                    parts.append(f'<path fill="{color.get(j, color["base"])}" transform="translate({dx:.1f},{dy:.1f})" d="{dj}"/>')
                cx += wj + trk * size
        else:
            parts.append(f'<path fill="{color}" transform="translate({dx:.1f},{dy:.1f})" d="{d}"/>')
        maxw = max(maxw, x1 - x0)
        y += (y1 - y0) + (gaps[i] if i < len(gaps) else 0)
    return "\n".join(parts), maxw, y - y_top


def measure(lines, gaps=None):
    _, w, h = block(lines, 0, 0, "start", gaps)
    return w, h


def label(txt, x, y, color="#9a9a9a"):
    d, _ = text_path("noto-bold", txt, 22, x, y, anchor="middle")
    return f'<path fill="{color}" d="{d}"/>'


def horiz(mark, mw, mh, lines, gaps, cx, cy, mark_h, gap):
    s = mark_h / mh
    tw, th = measure(lines, gaps)
    total = mw * s + gap + tw
    x0 = cx - total / 2
    g = f'<g transform="translate({x0:.1f},{cy - mark_h/2:.1f}) scale({s:.4f})">{mark}</g>'
    t, _, _ = block(lines, x0 + mw * s + gap, cy - th / 2, "start", gaps)
    return g + t, total


def vert(mark, mw, mh, lines, gaps, cx, top, mark_h, gap):
    s = mark_h / mh
    g = f'<g transform="translate({cx - mw*s/2:.1f},{top:.1f}) scale({s:.4f})">{mark}</g>'
    t, _, th = block(lines, cx, top + mark_h + gap, "middle", gaps)
    return g + t, mark_h + gap + th


def svg_doc(W, H, body, bg="#ffffff"):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}"><rect width="{W}" height="{H}" fill="{bg}"/>{body}</svg>'


def save(name, svg, mark, mw, mh, width=1200):
    render(svg, f"{OUT}/{name}.png", f"{OUT}/{name}.svg", width=width)
    pad = max(mw, mh) * 0.08
    m = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{-pad} {-pad} {mw+2*pad} {mh+2*pad}" width="600" height="{600*(mh+2*pad)/(mw+2*pad):.0f}"><rect x="{-pad}" y="{-pad}" width="{mw+2*pad}" height="{mh+2*pad}" fill="#fff"/>{mark}</svg>'
    render(m, f"{OUT}/{name}_mark.png", width=600)


def arc_text(fam, txt, r, cx, cy, size, fill, top=True, track=0.15):
    items = []
    for ch in txt:
        if ch == " ":
            items.append((None, size * 0.32)); continue
        items.append(text_path(fam, ch, size, 0, 0))
    tot = sum(w for _, w in items) + track * size * (len(items) - 1)
    span = tot / r
    out, cum = [], 0
    for d, w in items:
        if top:
            a = -math.pi / 2 - span / 2 + (cum + w / 2) / r; rot = math.degrees(a) + 90
        else:
            a = math.pi / 2 + span / 2 - (cum + w / 2) / r; rot = math.degrees(a) - 90
        if d:
            x, y = cx + r * math.cos(a), cy + r * math.sin(a)
            out.append(f'<path fill="{fill}" d="{d}" transform="translate({x:.1f},{y:.1f}) rotate({rot:.2f}) translate({-w/2:.1f},0)"/>')
        cum += w + track * size
    return "\n".join(out)
