#!/usr/bin/env python3
"""Design tokens and SVG primitives shared by the chart generator.

The visual language is documented in docs/DESIGN.md. Two rules matter here:

* System fonts only. GitHub serves these SVGs as images, so webfonts never load;
  every stack below resolves on macOS, Windows and Linux.
* Hand-drawn marks are annotations, never data. Jitter is seeded, so the output
  is byte-stable and `make_charts.py --check` stays exact.
"""
import random
from xml.sax.saxutils import escape

FONT_DISPLAY = ("ui-serif, 'Iowan Old Style', 'Palatino Linotype', Palatino, "
                "Georgia, 'Times New Roman', serif")
FONT_TEXT = ("ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', "
             "Helvetica, Arial, sans-serif")
FONT_NUM = ("ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, "
            "'Liberation Mono', monospace")

# Type scale (px). Nothing below 11 renders acceptably at 1x.
T = {"micro": 11, "caption": 12, "body": 13.5, "subhead": 16, "headline": 22, "hero": 46}

THEMES = {
    "light": {
        "surface": "#ffffff",
        "panel": "#f8fafc",
        "ink": "#0f172a",
        "muted": "#475569",
        "faint": "#64748b",
        "rule": "#e2e8f0",
        "rule_strong": "#cbd5e1",
        "glla": "#4338ca",
        "glla_soft": "#e0e7ff",
        "goalx": "#b45309",
        "goalx_soft": "#fef3c7",
        "on_accent": "#ffffff",
        "wash": "#f1f5f9",
        "seg_drafting": "#94a3b8",
        "seg_coding": "#334155",
        "seg_recon": "#e2e8f0",
        "seg_audit": "#0f766e",
        "seg_rework": "#b45309",
        "seg_settle": "#cbd5e1",
        "on_seg": "#ffffff",
    },
    "dark": {
        "surface": "#0b1220",
        "panel": "#111a2e",
        "ink": "#f1f5f9",
        "muted": "#c3cddd",
        "faint": "#8fa0b8",
        "rule": "#26334a",
        "rule_strong": "#33415c",
        "glla": "#a5b4fc",
        "glla_soft": "#1e2547",
        "goalx": "#fbbf24",
        "goalx_soft": "#3a2a10",
        "on_accent": "#0b1220",
        "wash": "#0f1729",
        "seg_drafting": "#475569",
        "seg_coding": "#cbd5e1",
        "seg_recon": "#33415c",
        "seg_audit": "#5eead4",
        "seg_rework": "#fbbf24",
        "seg_settle": "#334155",
        "on_seg": "#0b1220",
    },
}

W = 920
PAD = 28


def esc(s):
    return escape(str(s))


def text(x, y, s, size=T["body"], weight=400, fill="ink", anchor="start",
         font="text", extra=""):
    family = {"display": FONT_DISPLAY, "text": FONT_TEXT, "num": FONT_NUM}[font]
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{family}" font-size="{size}" '
            f'font-weight="{weight}" fill="{{{fill}}}" text-anchor="{anchor}"{extra}>'
            f'{esc(s)}</text>')


def rect(x, y, w, h, fill, rx=0, extra=""):
    r = f' rx="{rx}"' if rx else ""
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w, 0):.1f}" height="{h:.1f}" '
            f'fill="{{{fill}}}"{r}{extra}/>')


def line(x1, y1, x2, y2, stroke="rule", width=1, extra=""):
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{{{stroke}}}" stroke-width="{width}"{extra}/>')


def circle(cx, cy, r, fill="ink", stroke="none", width=0):
    s = f' stroke="{{{stroke}}}" stroke-width="{width}"' if width else ""
    return f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{{{fill}}}"{s}/>'


def path(d, stroke="ink", fill="none", width=1.4, extra=""):
    return (f'<path d="{d}" fill="{{{fill}}}" stroke="{{{stroke}}}" stroke-width="{width}" '
            f'stroke-linecap="round" stroke-linejoin="round"{extra}/>')


def paint(svg, theme):
    """Substitute {token} placeholders with the theme's colors."""
    for key, value in THEMES[theme].items():
        svg = svg.replace("{%s}" % key, value)
    return svg


# --------------------------------------------------------------- hand marks
def _wobble(rng, amp):
    return (rng.random() - 0.5) * 2 * amp


def scribble(points, seed, amp=1.1, samples=6, width=1.6, stroke="ink", opacity=0.85):
    """A slightly uneven polyline through the given points, like a pen stroke."""
    rng = random.Random(seed)
    d = []
    for i, (x, y) in enumerate(points):
        d.append(("M" if i == 0 else "L") + f"{x + _wobble(rng, amp):.1f},{y + _wobble(rng, amp):.1f}")
        if i < len(points) - 1:
            nx, ny = points[i + 1]
            for k in range(1, samples + 1):
                t = k / (samples + 1)
                d.append(f"L{x + (nx - x) * t + _wobble(rng, amp):.1f},"
                         f"{y + (ny - y) * t + _wobble(rng, amp):.1f}")
    return path(" ".join(d), stroke=stroke, width=width, extra=f' opacity="{opacity}"')


def hand_underline(x1, x2, y, seed, amp=1.3):
    rng = random.Random(seed)
    lift = rng.uniform(1.2, 2.4)
    pts = [(x1, y), ((x1 + x2) / 2, y + lift), (x2, y - lift * 0.4)]
    return scribble(pts, seed + 1, amp=amp, samples=7)


def hand_circle(cx, cy, rx, ry, seed, amp=1.2):
    rng = random.Random(seed)
    d = []
    steps = 40
    for i in range(steps + 1):
        a = 2 * 3.141592653589793 * i / steps
        wob = _wobble(rng, amp)
        x = cx + (rx + wob) * __import__("math").cos(a)
        y = cy + (ry + wob) * 0.55 * __import__("math").sin(a)
        d.append(("M" if i == 0 else "L") + f"{x:.1f},{y:.1f}")
    return path(" ".join(d), width=1.5, extra=' opacity="0.9"')


def hand_arrow(x1, y1, x2, y2, seed, bend=0.18, amp=1.0):
    rng = random.Random(seed)
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    dx, dy = x2 - x1, y2 - y1
    cx, cy = mx - dy * bend + _wobble(rng, amp), my + dx * bend + _wobble(rng, amp)
    d = f"M{x1:.1f},{y1:.1f} Q{cx:.1f},{cy:.1f} {x2:.1f},{y2:.1f}"
    import math
    ang = math.atan2(y2 - cy, x2 - cx)
    for side in (+1, -1):
        a = ang + side * 0.42
        d += (f" M{x2:.1f},{y2:.1f} L{x2 - 8 * math.cos(a):.1f},"
              f"{y2 - 8 * math.sin(a):.1f}")
    return path(d, width=1.5, extra=' opacity="0.9"')


def frame(title, subtitle, theme, height, aria, meta=""):
    """Common SVG document preamble with accessibility metadata."""
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" '
        f'viewBox="0 0 {W} {height}" role="img" aria-label="{esc(aria)}">',
        f"<title>{esc(title)}</title>",
        f"<desc>{esc(aria)}</desc>",
        rect(0, 0, W, height, "surface"),
        text(PAD, 44, title, T["headline"], 600, "ink", font="display"),
        text(PAD, 68, subtitle, T["caption"], 400, "muted"),
        line(PAD, 84, W - PAD, 84, "rule"),
    ]
    if meta:
        out.append(text(W - PAD, 44, meta, T["micro"], 400, "faint", "end"))
    return out


def close():
    return "</svg>"


def caption(y, s, theme=None):
    return text(PAD, y, s, T["micro"], 400, "faint")


def source_note(y, s):
    return text(PAD, y, s, T["micro"], 400, "faint")
