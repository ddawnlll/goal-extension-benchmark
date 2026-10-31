#!/usr/bin/env python3
"""Generate the result charts in assets/ from the committed measurements.

Reads only committed JSON (results/phase-model.json, results/replication-summary.json,
results/replication-comparison.csv) and writes four SVG documents:

  assets/timings.svg          every run's wall clock, with medians and ranges
  assets/phases.svg           where each run's time went
  assets/efficiency.svg       tokens and nominal cost per run
  assets/audit-overhead.svg   audit time and rework after a rejected audit

Standard library only, no timestamps: re-running on a clean checkout reproduces
the committed files byte for byte (`python3 tools/make_charts.py --check`).
"""
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"
ASSETS = ROOT / "assets"

INK = "#111827"
MUTED = "#6b7280"
RULE = "#e5e7eb"
CARD = "#ffffff"
EXT_COLOR = {"glla": "#1d4ed8", "goal-x": "#c2410c"}
SEGMENTS = [
    ("drafting", "Drafting and confirmation", "#94a3b8"),
    ("coding", "Coding and self-testing", "#334155"),
    ("reconciliation", "Contract reconciliation", "#e2e8f0"),
    ("audit", "Model audit", "#0f766e"),
    ("rework", "Rework after rejection", "#b45309"),
    ("settlement", "Settlement", "#cbd5e1"),
]
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
W = 920
PAD = 26


def esc(s):
    return escape(str(s))


def text(x, y, s, size=12, weight=400, fill=INK, anchor="start", extra=""):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}"{extra}>{esc(s)}</text>')


def rect(x, y, w, h, fill, extra=""):
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w, 0):.1f}" height="{h:.1f}" fill="{fill}"{extra}/>'


def header(title, subtitle, height):
    return ([f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" '
             f'viewBox="0 0 {W} {height}" role="img" aria-label="{esc(title)}">',
             f'<rect width="{W}" height="{height}" fill="{CARD}"/>',
             f'<rect x="0.5" y="0.5" width="{W - 1}" height="{height - 1}" fill="none" stroke="{RULE}"/>',
             text(PAD, 34, title, 17, 650),
             text(PAD, 55, subtitle, 12, 400, MUTED)])


def hatch_defs():
    return ('<defs><pattern id="exploratory" width="6" height="6" patternTransform="rotate(45)" '
            'patternUnits="userSpaceOnUse"><rect width="6" height="6" fill="#ffffff"/>'
            '<line x1="0" y1="0" x2="0" y2="6" stroke="#9ca3af" stroke-width="2"/></pattern></defs>')


def runs():
    data = json.loads((RES / "phase-model.json").read_text())
    order = {"s0": 0, "r1": 1, "r2": 2}
    return sorted(data["runs"], key=lambda r: (r["extension"], order[r["trial"]]))


def summary():
    return json.loads((RES / "replication-summary.json").read_text())


def label(r):
    return f"{'GLLA' if r['extension'] == 'glla' else 'pi-goal-x'}  {r['trial']}"


# ---------------------------------------------------------------- timings
def timings():
    rs = runs()
    row_h, top, left = 34, 96, 190
    width_px = W - left - 110
    peak = max(r["total_s"] for r in rs)
    scale = width_px / peak
    h = top + row_h * len(rs) + 120
    out = header("Wall clock to an independently verified completion",
                 "seconds per run; lower is better. The shaded runs are the exploratory trial.", h)
    out.append(hatch_defs())
    out.append(text(left, top - 12, "0", 11, 400, MUTED))
    for frac in (0.25, 0.5, 0.75, 1.0):
        x = left + width_px * frac
        out.append(f'<line x1="{x:.1f}" y1="{top - 6}" x2="{x:.1f}" y2="{top + row_h * len(rs) - 10}" '
                   f'stroke="{RULE}"/>')
        out.append(text(x, top - 12, f"{peak * frac:.0f} s", 11, 400, MUTED, "middle"))
    for i, r in enumerate(rs):
        y = top + i * row_h
        color = EXT_COLOR[r["extension"]]
        out.append(text(left - 14, y + 19, label(r), 13, 600 if r["trial"] != "s0" else 400,
                        INK if r["trial"] != "s0" else MUTED, "end"))
        w = r["total_s"] * scale
        out.append(rect(left, y + 4, w, 22, color, ' rx="3"'))
        if r["trial"] == "s0":
            out.append(rect(left, y + 4, w, 22, "url(#exploratory)", ' rx="3"'))
        out.append(text(left + w + 8, y + 20, f"{r['total_s']:.1f} s", 12, 600, INK))
    # medians of the controlled pairs
    s = summary()
    my = top + row_h * len(rs) + 16
    out.append(f'<line x1="{PAD}" y1="{my - 8}" x2="{W - PAD}" y2="{my - 8}" stroke="{RULE}"/>')
    out.append(text(PAD, my + 12, "Controlled pairs only (r1, r2)", 12, 650, INK))
    for j, ext in enumerate(("glla", "goal-x")):
        d = s[ext]["total_elapsed_s"]
        y = my + 36 + j * 26
        x0 = left
        x1 = left + d["max"] * scale
        xm = left + d["median"] * scale
        out.append(text(left - 14, y + 5, "GLLA" if ext == "glla" else "pi-goal-x", 12, 600, INK, "end"))
        out.append(f'<line x1="{x0}" y1="{y}" x2="{x1:.1f}" y2="{y}" stroke="{EXT_COLOR[ext]}" stroke-width="4"/>')
        out.append(f'<line x1="{x0}" y1="{y - 6}" x2="{x0}" y2="{y + 6}" stroke="{EXT_COLOR[ext]}" stroke-width="2"/>')
        out.append(f'<line x1="{x1:.1f}" y1="{y - 6}" x2="{x1:.1f}" y2="{y + 6}" stroke="{EXT_COLOR[ext]}" stroke-width="2"/>')
        out.append(f'<circle cx="{xm:.1f}" cy="{y}" r="6" fill="{CARD}" stroke="{EXT_COLOR[ext]}" stroke-width="3"/>')
        out.append(text(x1 + 10, y + 5, f"median {d['median']:.1f} s  (range {d['min']:.1f}–{d['max']:.1f})",
                        12, 600, INK))
    out.append("</svg>")
    return "\n".join(out) + "\n"


# ----------------------------------------------------------------- phases
def phases():
    rs = runs()
    row_h, top, left = 36, 112, 190
    width_px = W - left - 120
    peak = max(r["total_s"] for r in rs)
    scale = width_px / peak
    h = top + row_h * len(rs) + 56
    out = header("Where the time went",
                 "mutually exclusive phases of each run, in seconds", h)
    lx = PAD
    for key, name, color in SEGMENTS:
        out.append(rect(lx, 74, 10, 10, color, ' rx="2"'))
        out.append(text(lx + 15, 83, name, 11, 400, MUTED))
        lx += 18 + len(name) * 5.6
    for i, r in enumerate(rs):
        y = top + i * row_h
        out.append(text(left - 14, y + 19, label(r), 13, 600 if r["trial"] != "s0" else 400,
                        INK if r["trial"] != "s0" else MUTED, "end"))
        x = left
        for key, _name, color in SEGMENTS:
            v = r["segments"].get(key, 0.0)
            if v <= 0:
                continue
            w = v * scale
            out.append(rect(x, y + 4, w, 22, color, ' rx="2"'))
            if w >= 42:
                ink = "#ffffff" if key in ("coding", "audit") else INK
                out.append(text(x + w / 2, y + 19, f"{v:.0f}", 10.5, 600, ink, "middle"))
            x += w
        out.append(text(x + 8, y + 20, f"{r['total_s']:.0f} s", 11.5, 600, INK))
    out.append("</svg>")
    return "\n".join(out) + "\n"


# ------------------------------------------------------------- efficiency
def efficiency():
    rs = runs()
    row_h, top, left = 32, 108, 190
    token_w = 320
    cost_w = 240
    cost_x = left + token_w + 62
    peak_tok = max(r["tokens"]["input"] + r["tokens"]["output"] for r in rs)
    peak_cost = max(r["tokens"]["cost"] for r in rs)
    h = top + row_h * len(rs) + 52
    out = header("Model usage per run",
                 "input plus output tokens, and cost at list prices for the pinned model", h)
    out.append(text(left, top - 12, "tokens", 11, 600, MUTED))
    out.append(text(cost_x, top - 12, "nominal cost (USD)", 11, 600, MUTED))
    for i, r in enumerate(rs):
        y = top + i * row_h
        out.append(text(left - 14, y + 18, label(r), 12.5, 600 if r["trial"] != "s0" else 400,
                        INK if r["trial"] != "s0" else MUTED, "end"))
        tok = r["tokens"]["input"] + r["tokens"]["output"]
        w = token_w * tok / peak_tok
        out.append(rect(left, y + 4, w, 18, EXT_COLOR[r["extension"]], ' rx="3"'))
        out.append(text(left + w + 8, y + 18, f"{tok / 1000:.0f}k", 11.5, 600, INK))
        cw = cost_w * r["tokens"]["cost"] / peak_cost
        out.append(rect(cost_x, y + 4, cw, 18, EXT_COLOR[r["extension"]], ' rx="3"'))
        out.append(text(cost_x + cw + 8, y + 18, f"${r['tokens']['cost']:.3f}", 11.5, 600, INK))
    out.append("</svg>")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------- audit overhead
def audit_overhead():
    rs = runs()
    row_h, top, left = 34, 104, 190
    width_px = W - left - 190
    peak = max(r["segments"]["audit"] + r["segments"]["rework"] for r in rs) or 1
    scale = width_px / peak
    h = top + row_h * len(rs) + 64
    out = header("Audit overhead",
                 "model audit time, and repair time after a rejected audit", h)
    out.append(rect(PAD, 74, 10, 10, "#0f766e", ' rx="2"'))
    out.append(text(PAD + 15, 83, "model audit", 11, 400, MUTED))
    out.append(rect(PAD + 110, 74, 10, 10, "#b45309", ' rx="2"'))
    out.append(text(PAD + 125, 83, "rework after rejection", 11, 400, MUTED))
    for i, r in enumerate(rs):
        y = top + i * row_h
        out.append(text(left - 14, y + 19, label(r), 13, 600 if r["trial"] != "s0" else 400,
                        INK if r["trial"] != "s0" else MUTED, "end"))
        a = r["segments"]["audit"]
        rw = r["segments"]["rework"]
        x = left
        if a > 0:
            out.append(rect(x, y + 4, a * scale, 22, "#0f766e", ' rx="2"'))
            if a * scale > 44:
                out.append(text(x + a * scale / 2, y + 19, f"{a:.0f}", 10.5, 600, "#ffffff", "middle"))
            x += a * scale
        if rw > 0:
            out.append(rect(x, y + 4, rw * scale, 22, "#b45309", ' rx="2"'))
            if rw * scale > 30:
                out.append(text(x + rw * scale / 2, y + 19, f"{rw:.0f}", 10.5, 600, "#ffffff", "middle"))
            x += rw * scale
        share = 100.0 * (a + rw) / r["total_s"]
        out.append(text(x + 8, y + 19, f"{a + rw:.0f} s · {share:.0f}% of run", 11.5, 600, INK))
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main():
    ASSETS.mkdir(exist_ok=True)
    charts = {"timings.svg": timings(), "phases.svg": phases(),
              "efficiency.svg": efficiency(), "audit-overhead.svg": audit_overhead()}
    check = "--check" in sys.argv
    bad = 0
    for name, svg in charts.items():
        try:
            ET.fromstring(svg)  # fail loudly if a chart is not well-formed XML
        except ImportError:
            # Some Python builds ship without a working pyexpat; generation must
            # still work there. tools/check_svg.py validates the files with a
            # normal interpreter (and the container used for verification).
            print("note: this interpreter has no xml parser; skipping in-process validation")
        path = ASSETS / name
        if check:
            same = path.exists() and path.read_text() == svg
            print(f"{name}: {'identical' if same else 'DIFFERS'}")
            bad += 0 if same else 1
        else:
            path.write_text(svg)
            print(f"wrote {path.relative_to(ROOT)} ({len(svg)} bytes)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
