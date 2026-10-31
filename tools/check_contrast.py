#!/usr/bin/env python3
"""WCAG contrast audit for the chart palette.

Two classes of pair are enforced:

  text     every token used for type against every surface it is drawn on: >= 4.5:1
  graphics the two series colors and the audit fill against the surface: >= 3:1

Light "band" fills (contract reconciliation, settlement) are intentionally pale
and are reported as exempt: every band carries a direct numeric label, so the
fill is not required to read the chart (docs/DESIGN.md, accessibility rules).

Exit code is non-zero if any enforced pair fails.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chartkit import THEMES  # noqa: E402


def lum(hex_color):
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def ratio(a, b):
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


TEXT_ON = [
    ("ink", ["surface", "panel", "wash", "glla_soft", "goalx_soft"]),
    ("muted", ["surface", "panel", "wash"]),
    ("faint", ["surface", "panel"]),
    ("on_accent", ["glla", "goalx"]),
    ("on_seg", ["seg_audit", "seg_coding", "seg_rework"]),
    ("ink", ["seg_drafting", "seg_recon", "seg_settle"]),
]
GRAPHIC_ON = [
    ("glla", "surface"),
    ("goalx", "surface"),
    ("seg_audit", "surface"),
]
EXEMPT = ["seg_recon", "seg_settle", "seg_drafting", "rule", "rule_strong"]


def main():
    failures = 0
    for theme, tokens in THEMES.items():
        print(f"\n{theme}")
        for fg, backgrounds in TEXT_ON:
            for bg in backgrounds:
                r = ratio(tokens[fg], tokens[bg])
                ok = r >= 4.5
                failures += 0 if ok else 1
                print(f"  text    {fg:10} on {bg:11} {r:5.2f}  {'ok' if ok else 'FAIL'}")
        for fg, bg in GRAPHIC_ON:
            r = ratio(tokens[fg], tokens[bg])
            ok = r >= 3.0
            failures += 0 if ok else 1
            print(f"  graphic {fg:10} on {bg:11} {r:5.2f}  {'ok' if ok else 'FAIL'}")
        for name in EXEMPT:
            r = ratio(tokens[name], tokens["surface"])
            print(f"  exempt  {name:10} on surface   {r:5.2f}  (direct label)")
    print(f"\n{failures} failing pair(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
