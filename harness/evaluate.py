#!/usr/bin/env python3
"""Independent evaluation of collected candidates.

Runs the frozen acceptance suite and the extra adversarial suite against each
candidate tree in a throwaway container, checks scope and dataset integrity
from the collected diff, and grades goal understanding from the recorded
dialogue. Outputs results/independent-evaluation.json plus per-candidate raw
test logs.

Usage: evaluate.py <trial> [--anon]
"""
import json
import os
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
ENV = dict(os.environ, DOCKER_HOST=os.environ.get(
    "DOCKER_HOST", f"unix://{Path.home()}/.colima/default/docker.sock"))
EVAL_IMAGE = "goalbench/eval:1"
FIXTURE = ROOT / "baseline" / "pi-bolt" / "bench" / "results" / "2026-10-10-pi-bolt-0.7.3"
BASE_SVGS = ROOT / "evaluation" / "fixtures" / "baseline-svgs"


def sh(cmd, **kw):
    return subprocess.run(cmd, text=True, capture_output=True, env=ENV, **kw)


def run_tests(name, anon, trial):
    """Copy the candidate tree and run both suites in a clean container."""
    src = ROOT / "competitors" / name / "workspace"
    work = ROOT / "harness" / ".tmp" / f"eval-{anon}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    for child in src.iterdir():
        if child.name in (".git", ".pi", ".pi-glla"):
            continue
        dest = work / child.name
        if child.is_dir():
            subprocess.run(["cp", "-a", str(child), str(dest)], check=True)
        else:
            shutil.copy2(child, dest)
    out = {}
    for suite, label in (("test_report_svg.py", "frozen"), ("test_adversarial_extra.py", "adversarial")):
        p = sh(["docker", "run", "--rm", "--network", "none",
                "-v", f"{work}:/candidate",
                "-v", f"{ROOT / 'evaluation' / 'frozen'}:/eval:ro",
                "-v", f"{FIXTURE}:/fixture/results:ro",
                "-v", f"{BASE_SVGS}:/fixture/baseline-svgs:ro",
                "-e", "CANDIDATE_ROOT=/candidate",
                "-e", "FIXTURE_RESULTS=/fixture/results",
                "-e", "BASELINE_SVGS=/fixture/baseline-svgs",
                EVAL_IMAGE, "python3", "-m", "pytest", "-v", f"/eval/{suite}"],
               timeout=1800)
        text = (p.stdout or "") + (p.stderr or "")
        (RESULTS / f"{name}-{trial}-{label}-tests.log").write_text(text)
        passed = len(re.findall(r"PASSED", text))
        failed = len(re.findall(r"FAILED", text))
        skipped = len(re.findall(r"SKIPPED", text))
        out[label] = {"passed": passed, "failed": failed, "skipped": skipped,
                      "rc": p.returncode,
                      "failures": sorted(set(re.findall(r"FAILED \S+::(\S+)", text))),
                      "summary": next((l for l in text.splitlines() if re.search(r"\d+ (passed|failed)", l)), "")}
    shutil.rmtree(work, ignore_errors=True)
    return out


def scope(name, trial):
    files = RESULTS / f"{name}-{trial}-changed-files.txt"
    lines = [l.split("\t") for l in files.read_text().splitlines() if l.strip()] if files.exists() else []
    changed = [{"status": s, "path": p} for s, *rest in ((l[0], l[1]) for l in lines if len(l) >= 2) for p in [rest[0]]]
    datasets = [c for c in changed if c["path"].startswith("bench/results/")]
    out_of_scope = [c for c in changed if not (
        c["path"] == "bench/report.py" or c["path"].startswith("bench/tests/")
        or re.match(r"bench/test_.*\.py$", c["path"]) or c["path"].startswith("docs/")
        or c["path"] in ("bench/README.md", "README.md") or c["path"].startswith("bench/reports/"))]
    added_tests = [c for c in changed if re.match(r".*test.*\.py$", c["path"]) or c["status"] == "A"]
    deletions = [c for c in changed if c["status"] == "D"]
    diffstat = RESULTS / f"{name}-{trial}-diffstat.txt"
    stat = diffstat.read_text() if diffstat.exists() else ""
    insertions = sum(int(x) for x in re.findall(r"(\d+) insertions?\(\+\)", stat))
    deletions_n = sum(int(x) for x in re.findall(r"(\d+) deletions?\(-\)", stat))
    return {"changed": changed, "count": len(changed), "datasets_modified": datasets,
            "out_of_scope": out_of_scope, "added_or_test_files": added_tests,
            "deleted_files": deletions, "insertions": insertions, "deletions": deletions_n,
            "diffstat": stat.strip()}


REQUIRED_GROUPS = [
    ("escaping", r"escap|entity|sanitiz"),
    ("special characters", r"&|<|>|quote|apostroph"),
    ("unicode", r"unicode|utf-?8"),
    ("injection", r"inject|malicious|adversarial|attack|xss"),
    ("no double escaping", r"double[- ]escap"),
    ("visual appearance", r"appearance|visual|unchanged|byte-identical"),
    ("regression tests", r"regression test|unit test|pytest|unittest"),
    ("XML validation", r"xml parser|xml\.etree|ElementTree|well-formed"),
    ("existing tests", r"existing test|test suite|run the tests"),
    ("documentation", r"document|docstring|comment|readme"),
    ("scope discipline", r"no unrelated|unrelated refactor|minimal|scope"),
    ("CLI/data preserved", r"cli|command-line|dataset"),
]


def goal_understanding(name):
    """Grade what the extension actually confirmed, from the recorded dialogue."""
    ui = ROOT / "competitors" / name / "logs" / "ui-script.json"
    entries = json.loads(ui.read_text()) if ui.exists() else []
    proposals = []
    for e in entries:
        if e.get("method") in ("select", "confirm", "editor", "input"):
            text = json.dumps(e.get("request") or {})
            if re.search(r"goal|objective|contract|criteria|done when", text, re.I):
                proposals.append(text)
    blob = "\n".join(proposals)
    if not blob:
        # fall back to the confirmed goal file on disk (goal-x) / session summary
        blob = ""
        for p in (ROOT / "competitors" / name / "workspace" / ".pi" / "goals").glob("active_goal_*.md"):
            blob += p.read_text(errors="replace")
        for p in (ROOT / "competitors" / name / "workspace" / ".pi-glla" / "goals").glob("*.md"):
            blob += p.read_text(errors="replace")
    present = [g for g, rx in REQUIRED_GROUPS if re.search(rx, blob, re.I)]
    return {
        "dialogue_events": len(entries),
        "dialog_questions": len([e for e in entries if e.get("method") in ("select", "confirm", "input", "editor")]),
        "proposal_chars": len(blob),
        "requirement_groups_present": present,
        "coverage": f"{len(present)}/{len(REQUIRED_GROUPS)}",
        "deviations_recorded": len([e for e in entries if "deviation" in json.dumps(e)]),
        "excerpt": blob[-1500:] if blob else None,
    }


def main():
    trial = sys.argv[1] if len(sys.argv) > 1 else "s0"
    names = ["glla", "goal-x"]
    anon = {n: f"C{i+1}" for i, n in enumerate(random.sample(names, 2))}
    result = {"trial": trial, "anonymization": anon, "candidates": {}}
    for name in names:
        a = anon[name]
        tests = run_tests(name, a, trial)
        sc = scope(name, trial)
        gu = goal_understanding(name)
        metrics = json.loads((RESULTS / f"{name}-{trial}-metrics.json").read_text()) \
            if (RESULTS / f"{name}-{trial}-metrics.json").exists() else {}
        result["candidates"][name] = {
            "anonymous_id": a, "tests": tests, "scope": sc,
            "goal_understanding": gu, "metrics": metrics,
        }
        print(f"{name} ({a}): frozen {tests['frozen']['summary']} | "
              f"adversarial {tests['adversarial']['summary']} | "
              f"changed {sc['count']} files | coverage {gu['coverage']}")
    (RESULTS / "independent-evaluation.json").write_text(json.dumps(result, indent=1))
    print(json.dumps({n: result["candidates"][n]["tests"] for n in names}, indent=1))


if __name__ == "__main__":
    main()
