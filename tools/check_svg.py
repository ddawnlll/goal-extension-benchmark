#!/usr/bin/env python3
"""Validate every committed SVG with xml.etree.ElementTree.

Run in any interpreter that has a working pyexpat (the project's verification
container does). Exits non-zero on the first file that does not parse.
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
files = sorted((ROOT / "assets").glob("*.svg"))
if not files:
    print("no SVGs found", file=sys.stderr)
    sys.exit(1)
for p in files:
    root = ET.parse(p).getroot()
    if not root.tag.endswith("svg"):
        print(f"{p.name}: root element is {root.tag}", file=sys.stderr)
        sys.exit(1)
    print(f"{p.name}: ok ({len(root)} top-level children)")
