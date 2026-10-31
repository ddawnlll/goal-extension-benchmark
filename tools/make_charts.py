#!/usr/bin/env python3
"""Generate the result charts in assets/ from the committed measurements.

Four compositions, each in a light and a dark variant:

  hero        medians, ranges, cost and outcome in one panel
  timing      every run's wall clock, controlled and exploratory
  phases      where each run's time went
  efficiency  audit overhead and model usage, side by side

Standard library only, no clocks: re-running on a clean checkout reproduces the
committed files byte for byte (`python3 tools/make_charts.py --check`).

Visual rules live in docs/DESIGN.md; tokens and primitives in tools/chartkit.py.
"""
import json
import math
import statistics
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chartkit as K  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"
ASSETS = ROOT / "assets"

SEGMENTS = [
    ("drafting", "Drafting", "seg_drafting", "ink"),
    ("coding", "Coding", "seg_coding", "on_seg"),
    ("reconciliation", "Contract reconciliation", "seg_recon", "ink"),
    ("audit", "Model audit", "seg_audit", "on_seg"),
    ("rework", "Rework", "seg_rework", "on_seg"),
    ("settlement", "Settlement", "seg_settle", "ink"),
]
EXT_LABEL = {"glla": "GLLA", "goal-x": "pi-goal-x"}
EXT_COLOR = {"glla": "glla", "goal-x": "goalx"}
ORDER = {"r1": 0, "r2": 1, "s0": 2}


def load():
    model = json.loads((RES / "phase-model.json").read_text())["runs"]
    summary = json.loads((RES / "replication-summary.json").read_text())
    model.sort(key=lambda r: (list(EXT_LABEL).index(r["extension"]), ORDER[r["trial"]]))
    return model, summary


def controlled(runs):
    return [r for r in runs if r["trial"] != "s0"]


def fmt_s(v):
    return f"{v:,.0f} s" if v >= 10 else f"{v:.1f} s"


# ------------------------------------------------------------------- hero
def stats(values):
    v = sorted(values)
    return {"median": statistics.median(v), "min": v[0], "max": v[-1]}


def hero(runs, summary, theme):
    ctrl = controlled(runs)
    med = {e: stats([r["total_s"] for r in ctrl if r["extension"] == e]) for e in ("glla", "goal-x")}
    tok = {e: statistics.median([r["tokens"]["input"] + r["tokens"]["output"]
                                 for r in ctrl if r["extension"] == e]) for e in ("glla", "goal-x")}
    cost = {e: statistics.median([r["tokens"]["cost"] for r in ctrl if r["extension"] == e])
            for e in ("glla", "goal-x")}
    ratio = med["glla"]["median"] / med["goal-x"]["median"]
    money = cost["glla"] / cost["goal-x"]
    h = 430
    out = K.frame(
        "Same task. Same model. Same limits.",
        "Two Pi goal extensions, four controlled runs, sixteen independent tests each.",
        theme, h,
        f"Hero summary. GLLA median {med['glla']['median']:.1f} seconds, range "
        f"{med['glla']['min']:.1f} to {med['glla']['max']:.1f}. pi-goal-x median "
        f"{med['goal-x']['median']:.1f} seconds, range {med['goal-x']['min']:.1f} to "
        f"{med['goal-x']['max']:.1f}. That is {ratio:.1f} times the wall clock. Cost per run: "
        f"{cost['glla']:.3f} dollars versus {cost['goal-x']:.3f}. Tokens: {tok['glla'] / 1000:.0f} "
        f"thousand versus {tok['goal-x'] / 1000:.0f} thousand. Both passed 16 of 16 tests. "
        f"No overall winner is declared.", meta="Pi 1.4.0 · Pi-Bolt 1.0.8 · deepseek-v4.1-flash")

    # -- left: wall clock ---------------------------------------------------
    ax0, ax1 = 122, 500
    scale = (ax1 - ax0) / 760.0
    out.append(K.text(28, 112, "Wall clock to a verified completion", K.T["subhead"], 600, "ink",
                      font="display"))
    for tick in (0, 300, 600):
        x = ax0 + tick * scale
        out.append(K.line(x, 130, x, 268, "rule"))
        out.append(K.text(x, 286, f"{tick}s", K.T["micro"], 400, "faint", "middle"))
    for ext, y in (("glla", 172), ("goal-x", 234)):
        d = med[ext]
        x0 = ax0 + d["min"] * scale
        x1 = ax0 + d["max"] * scale
        xm = ax0 + d["median"] * scale
        out.append(K.text(ax0 - 14, y + 5, EXT_LABEL[ext], K.T["caption"], 700,
                          EXT_COLOR[ext], "end"))
        out.append(K.line(x0, y, x1, y, EXT_COLOR[ext], 3, ' opacity="0.5"'))
        out.append(K.line(x0, y - 6, x0, y + 6, EXT_COLOR[ext], 2))
        out.append(K.line(x1, y - 6, x1, y + 6, EXT_COLOR[ext], 2))
        out.append(K.circle(xm, y, 6.5, "surface", EXT_COLOR[ext], 3))
        out.append(K.text(xm, y - 16, f"{d['median']:.0f} s", K.T["body"], 700, "ink", "middle",
                          font="num"))
        out.append(K.text(x0, y + 22, f"{d['min']:.1f}–{d['max']:.1f} s", K.T["micro"], 400,
                          "faint", font="num"))
    out.append(K.hand_underline(ax0, ax0 + 760 * scale, 306, seed=5, amp=0.9))
    out.append(K.text(ax0, 326, "lower is faster", K.T["micro"], 400, "faint"))

    # -- right: the one number ---------------------------------------------
    rx = 580
    out.append(K.line(rx - 30, 104, rx - 30, 340, "rule"))
    out.append(K.text(rx, 112, "In one number", K.T["subhead"], 600, "ink", font="display"))
    out.append(K.text(rx, 196, f"{ratio:.1f}×", 72, 700, "ink", font="num"))
    out.append(K.hand_underline(rx - 2, rx + 150, 208, seed=12, amp=1.4))
    out.append(K.text(rx, 236, "the wall clock, median of the two", K.T["caption"], 400, "muted"))
    out.append(K.text(rx, 254, "controlled pairs. Both finished verified.", K.T["caption"], 400, "muted"))

    rows = [
        (f"cost per run, {money:.1f}× less", f"${cost['glla']:.3f}", f"${cost['goal-x']:.3f}"),
        (f"tokens per run, {tok['glla'] / tok['goal-x']:.1f}× fewer",
         f"{tok['glla'] / 1000:.0f}k", f"{tok['goal-x'] / 1000:.0f}k"),
    ]
    for i, (label, a, b) in enumerate(rows):
        y = 294 + i * 26
        out.append(K.text(rx, y, label, K.T["micro"], 400, "faint"))
        out.append(K.text(rx + 200, y, a, K.T["caption"], 700, "ink", "end", font="num"))
        out.append(K.text(rx + 216, y, "vs", K.T["micro"], 400, "faint"))
        out.append(K.text(rx + 296, y, b, K.T["caption"], 700, "ink", "end", font="num"))
    out.append(K.rect(rx, 360, 250, 26, "wash", 13))
    out.append(K.text(rx + 12, 377, "No overall winner declared", K.T["micro"], 600, "ink"))

    out.append(K.text(28, 408, "Controlled pairs r1–r2 · medians of two runs · exploratory s0 "
                                "excluded from every summary", K.T["micro"], 400, "faint"))
    out.append(K.close())
    return "\n".join(out) + "\n"


# ----------------------------------------------------------------- timing
def timing(runs, theme):
    h = 400
    out = K.frame(
        "Every run, on one axis",
        "seconds to a verified completion; the exploratory trial is hollow for a reason",
        theme, h,
        "Dot plot of all six runs. Controlled: GLLA 698.7 and 622.2 seconds, "
        "pi-goal-x 297.7 and 430.0 seconds. Exploratory: GLLA 956.0, pi-goal-x 598.9.",
        meta="6 runs · 4 controlled")
    ax0, ax1 = 120, 830
    peak = 1000.0
    scale = (ax1 - ax0) / peak
    for tick in (0, 250, 500, 750, 1000):
        x = ax0 + tick * scale
        out.append(K.line(x, 104, x, 324, "rule"))
        out.append(K.text(x, 342, f"{tick}s", K.T["micro"], 400, "faint", "middle"))
    lanes = {"glla": 162, "goal-x": 250}
    for ext, y in lanes.items():
        out.append(K.text(ax0 - 16, y + 5, EXT_LABEL[ext], K.T["subhead"], 700, EXT_COLOR[ext], "end"))
        mine = [r for r in runs if r["extension"] == ext]
        for r in mine:
            x = ax0 + r["total_s"] * scale
            ghost = r["trial"] == "s0"
            out.append(K.circle(x, y, 6, "surface" if ghost else EXT_COLOR[ext],
                                EXT_COLOR[ext], 2))
            if ghost:
                out.append(K.text(x - 12, y + 4, f"{r['total_s']:.0f}", K.T["micro"], 700,
                                  "faint", "end", font="num"))
            else:
                out.append(K.text(x, y - 16, f"{r['total_s']:.0f}", K.T["micro"], 700,
                                  "ink", "middle", font="num"))
            out.append(K.text(x, y + 26, r["trial"], K.T["micro"], 400,
                              "faint", "middle"))
    # median rail for the controlled runs
    for ext, y in lanes.items():
        d = [r["total_s"] for r in runs if r["extension"] == ext and r["trial"] != "s0"]
        m = sum(d) / len(d)
        x = ax0 + m * scale
        out.append(K.line(x, y - 34, x, y + 12, "ink", 1, ' stroke-dasharray="3 3" opacity="0.5"'))
        out.append(K.text(x, y + 44, f"median {m:.0f}s", K.T["micro"], 600, "muted", "middle"))
    sx = ax0 + 956 * scale
    out.append(K.hand_arrow(sx + 6, 122, sx + 2, 152, seed=21, bend=0.12))
    out.append(K.text(sx - 14, 118, "s0: relay resets and a host sleep", K.T["micro"], 600,
                      "muted", "end"))
    out.append(K.text(ax0, 380, "Controlled pairs r1–r2. s0 is the exploratory campaign, shown for "
                                "transparency and excluded from every summary.", K.T["micro"], 400,
                      "faint"))
    out.append(K.close())
    return "\n".join(out) + "\n"


# ----------------------------------------------------------------- phases
def phases(runs, theme):
    h = 424
    out = K.frame(
        "Where the time went",
        "mutually exclusive phases per run, seconds; the audit is not the whole story",
        theme, h,
        "Stacked phase bars for six runs: drafting, coding, contract reconciliation, audit, "
        "rework and settlement. GLLA r1 spends 211 seconds reconciling its contract before "
        "any audit runs; GLLA r2 spends 268 seconds in two audit rounds plus 42 in rework.",
        meta="6 runs")
    ax0 = 156
    width = 686.0
    peak = max(r["total_s"] for r in runs)
    scale = width / peak
    lx = ax0
    for key, name, color, _ink in SEGMENTS:
        out.append(K.rect(lx, 98, 9, 9, color, 2))
        out.append(K.text(lx + 14, 107, name, K.T["micro"], 400, "muted"))
        lx += 20 + len(name) * 5.9
    y = 132
    prev = None
    for r in runs:
        if prev and prev != r["extension"]:
            y += 16
        prev = r["extension"]
        out.append(K.text(ax0 - 14, y + 13, f"{EXT_LABEL[r['extension']]} {r['trial']}",
                          K.T["caption"], 700 if r["trial"] != "s0" else 400,
                          "ink" if r["trial"] != "s0" else "faint", "end"))
        x = ax0
        for key, _name, color, ink in SEGMENTS:
            v = r["segments"].get(key, 0.0)
            if v <= 0:
                continue
            w = v * scale
            out.append(K.rect(x, y, w, 18, color, 2))
            if w >= 46:
                out.append(K.text(x + w / 2, y + 13, f"{v:.0f}", K.T["micro"], 600, ink, "middle"))
            x += w
        out.append(K.text(x + 8, y + 13, f"{r['total_s']:.0f}s", K.T["micro"], 600, "muted",
                          font="num"))
        y += 46
    # annotate the GLLA r1 reconciliation in place, under its own row
    r1 = next(r for r in runs if r["extension"] == "glla" and r["trial"] == "r1")
    seg = r1["segments"]
    xa = ax0 + (seg["drafting"] + seg["coding"]) * scale
    xb = xa + seg["reconciliation"] * scale
    out.append(K.hand_underline(xa + 2, xb - 2, 162, seed=31, amp=0.8))
    out.append(K.text(xa + 2, 176, "211 s of contract reconciliation, no code defect found",
                      K.T["micro"], 600, "muted"))
    out.append(K.close())
    return "\n".join(out) + "\n"


# ------------------------------------------------------------- efficiency
def efficiency(runs, theme):
    h = 428
    out = K.frame(
        "Audit overhead and model usage",
        "left: time inside the audit and repair loop. right: tokens and cost per run.",
        theme, h,
        "Two panels. Audit seconds per run on the left with the share of the run; GLLA r2 "
        "adds 42 seconds of rework after a rejected audit. Tokens and nominal cost on the "
        "right; GLLA runs use about 230 thousand tokens, pi-goal-x runs 80 to 150 thousand.",
        meta="6 runs")
    lx0, lx1 = 156, 420
    out.append(K.text(28, 108, "Audit and repair", K.T["subhead"], 600, "ink", font="display"))
    peak_a = max(r["segments"]["audit"] + r["segments"]["rework"] for r in runs)
    sa = (lx1 - lx0) / peak_a
    y = 136
    prev = None
    for r in runs:
        if prev and prev != r["extension"]:
            y += 12
        prev = r["extension"]
        out.append(K.text(lx0 - 14, y + 13, f"{EXT_LABEL[r['extension']]} {r['trial']}",
                          K.T["caption"], 700 if r["trial"] != "s0" else 400,
                          "ink" if r["trial"] != "s0" else "faint", "end"))
        a = r["segments"]["audit"]
        rw = r["segments"]["rework"]
        x = lx0
        out.append(K.rect(x, y, a * sa, 18, EXT_COLOR[r["extension"]], 2,
                          ' opacity="0.9"'))
        if a * sa > 40:
            out.append(K.text(x + a * sa / 2, y + 13, f"{a:.0f}", K.T["micro"], 600,
                              "on_accent", "middle"))
        x += a * sa
        if rw:
            out.append(K.rect(x, y, rw * sa, 18, "ink", 2, ' opacity="0.28"'))
            out.append(K.text(x + rw * sa / 2, y + 13, f"{rw:.0f}", K.T["micro"], 600, "ink",
                              "middle"))
            x += rw * sa
        share = 100 * (a + rw) / r["total_s"]
        out.append(K.text(500, y + 13, f"{share:.0f}%", K.T["micro"], 600, "muted", "end", font="num"))
        y += 46
    out.append(K.text(28, 406, "Bars are colored by extension; the faded segment is rework "
                                "after a rejected audit. Percentages are of the whole run.",
                      K.T["micro"], 400, "faint"))

    # right panel
    out.append(K.line(552, 96, 552, 356, "rule"))
    rx0, rx1 = 640, 800
    out.append(K.text(576, 108, "Model usage", K.T["subhead"], 600, "ink", font="display"))
    out.append(K.text(576, 126, "tokens in + out, then nominal cost · color is the extension",
                      K.T["micro"], 400, "faint"))
    peak_t = max(r["tokens"]["input"] + r["tokens"]["output"] for r in runs)
    st = (rx1 - rx0) / peak_t
    y = 152
    prev = None
    for r in runs:
        if prev and prev != r["extension"]:
            y += 12
        prev = r["extension"]
        tok = r["tokens"]["input"] + r["tokens"]["output"]
        out.append(K.rect(rx0, y, tok * st, 14, EXT_COLOR[r["extension"]], 2, ' opacity="0.9"'))
        out.append(K.text(rx1 + 10, y + 11, f"{tok / 1000:.0f}k", K.T["micro"], 600, "ink",
                          font="num"))
        out.append(K.text(rx1 + 44, y + 11, f"${r['tokens']['cost']:.3f}", K.T["micro"], 400,
                          "faint", font="num"))
        y += 34
    out.append(K.close())
    return "\n".join(out) + "\n"


CHARTS = {"hero": hero, "timing": timing, "phases": phases, "efficiency": efficiency}


def main():
    runs, summary = load()
    ASSETS.mkdir(exist_ok=True)
    check = "--check" in sys.argv
    bad = 0
    for name, fn in CHARTS.items():
        for theme in ("light", "dark"):
            svg = K.paint(fn(runs, summary, theme) if fn is hero else fn(runs, theme), theme)
            try:
                ET.fromstring(svg)
            except ImportError:
                pass
            path = ASSETS / f"{name}-{theme}.svg"
            if check:
                same = path.exists() and path.read_text() == svg
                print(f"{path.name}: {'identical' if same else 'DIFFERS'}")
                bad += 0 if same else 1
            else:
                path.write_text(svg)
                print(f"wrote {path.relative_to(ROOT)} ({len(svg)} bytes)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
