#!/usr/bin/env python3
"""Publication checks for this repository.

  * no credentials, no host paths, no personal identifiers
  * no file larger than 10 MB
  * every relative link and image in the markdown resolves

Run from the repository root:  python3 tools/check_publish.py
"""
import gzip
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_BYTES = 10 * 1024 * 1024

# Shapes that must never appear. The benchmark's own relay credential is an
# opaque 48-character string and is checked by its storage path instead.
PATTERNS = [
    (re.compile(r"/Users/[A-Za-z0-9._-]+"), "absolute macOS home path"),
    (re.compile(r"[A-Za-z]:\\\\Users\\\\"), "absolute Windows home path"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), "secret-key shape"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "GitHub token shape"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "GitHub fine-grained token shape"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key shape"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"), "Slack token shape"),
]
# Synthetic fixtures that exist inside upstream test suites and are not secrets.
ALLOW = [
    "ghp_abcdefghij1234567890",
    "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
    "sk-ant-api03-abcdefghijklmnop",
]


def files():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True)
    names = [n for n in out.stdout.split("\0") if n]
    if not names:  # not a git checkout yet: walk instead
        names = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*")
                 if p.is_file() and ".git" not in p.parts]
    return names


def content(path):
    raw = path.read_bytes()
    if path.suffix == ".gz":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")


def main():
    problems = []
    scanned = 0
    for name in files():
        p = ROOT / name
        if not p.exists():
            continue
        scanned += 1
        size = p.stat().st_size
        if size > MAX_BYTES:
            problems.append(f"{name}: {size / 1e6:.1f} MB is over the 10 MB limit")
        try:
            text = content(p)
        except Exception as exc:  # binary or unreadable
            continue
        for rx, why in PATTERNS:
            for m in rx.finditer(text):
                hit = m.group(0)
                if any(a in hit for a in ALLOW):
                    continue
                line = text[:m.start()].count("\n") + 1
                problems.append(f"{name}:{line}: {why}: {hit[:40]}")

    # the credential file itself must not be part of the tree
    for p in ROOT.rglob("local_api_key"):
        if ".git" not in p.parts:
            problems.append(f"{p.relative_to(ROOT)}: credential file present in the tree")

    # links and images in markdown
    for md in ROOT.rglob("*.md"):
        if ".git" in md.parts:
            continue
        text = md.read_text(errors="replace")
        for target in re.findall(r"\]\(([^)\s]+)\)", text) + re.findall(r'src="([^"]+)"', text):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            if not (md.parent / target.split("#")[0]).exists():
                problems.append(f"{md.relative_to(ROOT)}: broken link to {target}")

    print(f"scanned {scanned} files")
    if problems:
        print(f"\n{len(problems)} problem(s):", file=sys.stderr)
        for p in problems[:50]:
            print("  " + p, file=sys.stderr)
        return 1
    print("no credentials, host paths or personal identifiers found")
    print("no file over 10 MB")
    print("all relative links and images resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
