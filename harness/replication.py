#!/usr/bin/env python3
"""Replication pipeline: collect, timeline, evaluate, aggregate.

Works per (competitor, trial) pair without touching the exploratory `s0`
artifacts: collected trees go to competitors/<name>/<trial>/, derived files to
results/<name>-<trial>-*.

Subcommands:
  collect <trial>              copy volumes out, build patches
  timeline <trial>             phase timings from recorded evidence
  evaluate <trial>             blind independent test run for both candidates
  aggregate                    medians/ranges over all replication trials
"""
import hashlib
import json
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
R = ROOT / "results"
ENV = dict(os.environ, DOCKER_HOST=os.environ.get(
    "DOCKER_HOST", f"unix://{Path.home()}/.colima/default/docker.sock"))
IMAGE = "goalbench/base:1"
EVAL = "goalbench/eval:1"
NAMES = ["glla", "goal-x"]
TRIALS = ["r1", "r2"]
WRITE_TOOLS = {"write", "edit", "str_replace", "create_file", "apply_patch", "multi_edit"}
TEST_RX = re.compile(r"pytest|unittest|test_report|check_svg", re.I)


def sh(cmd, **kw):
    return subprocess.run(cmd, text=True, capture_output=True, env=ENV, **kw)


def docker(*a, **kw):
    return sh(["docker", *a], **kw)


def load_jsonl(p):
    out = []
    try:
        for line in Path(p).read_text(errors="replace").splitlines():
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    except OSError:
        pass
    return out


def cdir(name, trial):
    return ROOT / "competitors" / name / trial


# ------------------------------------------------------------------ collect
def collect(name, trial):
    vol = f"gb-{name}-home"
    relay_vol = f"gb-{name}-relay"
    dest = cdir(name, trial)
    tmp = ROOT / "harness" / ".tmp" / f"collect-{name}-{trial}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    docker("run", "--rm", "--user", "0", "--entrypoint", "/bin/bash",
           "-v", f"{vol}:/h", "-v", f"{relay_vol}:/relaylog:ro", "-v", f"{tmp}:/out", IMAGE, "-lc",
           "set -e; mkdir -p /out/logs /out/sessions /out/agent-config /out/extensions /out/workspace; "
           "cp -a /h/logs/. /out/logs/ 2>/dev/null || true; "
           "cp -a /h/.pi/agent/sessions/. /out/sessions/ 2>/dev/null || true; "
           "cp -a /h/.pi/agent/models.json /h/.pi/agent/settings.json /out/agent-config/ 2>/dev/null || true; "
           "cp -a /h/extensions/. /out/extensions/ 2>/dev/null || true; "
           "cp -a /h/work/. /out/workspace/ 2>/dev/null || true; "
           "cp -a /relaylog/. /out/logs/ 2>/dev/null || true; "
           "rm -rf /out/workspace/.git")
    if dest.exists():
        shutil.rmtree(dest)
    for part in ("logs", "sessions", "agent-config", "extensions", "workspace"):
        shutil.copytree(tmp / part, dest / part, symlinks=True)
    shutil.rmtree(tmp, ignore_errors=True)

    # canonical patch against the pinned baseline
    base = ROOT / "baseline" / "pi-bolt"
    work = ROOT / "harness" / ".tmp" / f"patch-{name}-{trial}"
    shutil.rmtree(work, ignore_errors=True)
    subprocess.run(["cp", "-a", str(base), str(work)], check=True)
    for child in work.iterdir():
        if child.name == ".git":
            continue
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    src = dest / "workspace"
    for child in src.iterdir():
        if child.name in (".pi", ".pi-glla", ".git"):
            continue
        target = work / child.name
        shutil.copytree(child, target, symlinks=True) if child.is_dir() else shutil.copy2(child, target)
    sh(("git", "-C", str(work), "checkout", "--", ".pi"))
    shutil.rmtree(work / ".pi-glla", ignore_errors=True)
    sh(("git", "-C", str(work), "config", "user.email", "eval@benchmark.invalid"))
    sh(("git", "-C", str(work), "config", "user.name", "benchmark-eval"))
    sh(("git", "-C", str(work), "add", "-A"))
    diff = sh(("git", "-C", str(work), "diff", "--cached", "--binary")).stdout
    (R / f"{name}-{trial}.patch").write_text(diff)
    stat = sh(("git", "-C", str(work), "diff", "--cached", "--stat")).stdout
    (R / f"{name}-{trial}-diffstat.txt").write_text(stat)
    files = sh(("git", "-C", str(work), "diff", "--cached", "--name-status")).stdout
    (R / f"{name}-{trial}-changed-files.txt").write_text(files)
    shutil.rmtree(work, ignore_errors=True)
    print(f"{name} {trial}: collected, patch {len(diff)} bytes")
    return stat


# ----------------------------------------------------------------- timeline
def timeline(name, trial):
    d = cdir(name, trial)
    final = json.loads((d / "logs" / "final-state.json").read_text())
    ms, c = final["milestones"], final["counters"]
    ev = load_jsonl(d / "logs" / "events.jsonl")
    relay = load_jsonl(d / "logs" / "relay.jsonl")

    tool_events = []
    for e in ev:
        rec = e.get("record") or {}
        if e.get("dir") == "pi" and rec.get("type") == "tool_execution_start":
            tool_events.append({"t": e["t"], "name": rec.get("toolName"),
                                "args": rec.get("args") or {}})
    writes = [t for t in tool_events
              if (t["name"] or "").lower() in WRITE_TOOLS]
    tests = [t for t in tool_events
             if (t["name"] or "").lower() == "bash" and TEST_RX.search(str(t["args"].get("command", "")))]

    def at(tool_name, pred=lambda a: True):
        for t in tool_events:
            if (t["name"] or "") == tool_name and pred(t["args"]):
                return t["t"]
        return None

    claims = [t for t in tool_events if "complete" in (t["name"] or "").lower()
              or (t["name"] or "") == "update_goal"]
    claim_t = min((t["t"] for t in claims), default=(ms.get("first_completion_claim") or {}).get("t"))

    # audit facts from the extension's own records
    audits = load_jsonl(d / "workspace" / ".pi-glla" / "audits.jsonl")
    audit_jobs = []
    for prog in (d / "workspace" / ".pi-glla" / "audit-jobs").glob("*/progress.json"):
        try:
            audit_jobs.append(json.loads(prog.read_text()))
        except Exception:
            pass
    gx_events = load_jsonl(d / "workspace" / ".pi" / "goals" / "goal_events.jsonl")
    status_complete_t = None
    for e in ev:
        rec = e.get("record") or {}
        if rec.get("type") == "extension_ui_request" and rec.get("method") == "setWidget":
            blob = "\n".join(rec.get("widgetLines") or [])
            if re.search(r"complete|verified|archived|done", blob, re.I) and status_complete_t is None:
                pass  # widget text is noisy; persisted state is authoritative

    total = final.get("duration_seconds")
    confirmed = (ms.get("goal_confirmed") or {}).get("t")
    first_write = writes[0]["t"] if writes else None
    last_write = writes[-1]["t"] if writes else None
    reqs = [r for r in relay if r.get("path", "").endswith("chat/completions")]
    req_t = [r["t_wall"] for r in reqs if r.get("t_wall")]
    gaps = [b - a for a, b in zip(sorted(req_t), sorted(req_t)[1:])]

    return {
        "name": name, "trial": trial,
        "started_utc": final.get("started_utc") or (ms.get("started_utc")),
        "total_elapsed_s": total,
        "goal_confirmed_s": confirmed,
        "first_code_write_s": first_write,
        "last_code_write_s": last_write,
        "code_writes": len(writes),
        "test_commands": len(tests),
        "first_test_s": tests[0]["t"] if tests else None,
        "last_test_s": tests[-1]["t"] if tests else None,
        "first_completion_claim_s": claim_t,
        "completion_tool": claims[0]["name"] if claims else None,
        "requests": len(reqs),
        "requests_failed": len([r for r in reqs if r.get("status") not in (200, None)]),
        "max_request_gap_s": round(max(gaps), 1) if gaps else None,
        "audit_verdicts": [
            {"at": a.get("at"), "verdict": a.get("verdict")} for a in audits
        ],
        "audit_jobs": [
            {"elapsedMs": j.get("elapsedMs"), "round": j.get("round"), "phase": j.get("phase")}
            for j in audit_jobs
        ],
        "goal_events": [
            {"type": e.get("type"), "at": e.get("at")} for e in gx_events
            if e.get("type") in ("goal_created", "completion_requested", "audit_started",
                                 "audit_result", "goal_completed", "goal_archived")
        ],
        "counters": c,
        "exit_reason": final.get("exit_reason"),
        "tokens_main": None,
    }


def tokens(d):
    tot = {"input": 0, "output": 0, "cacheRead": 0, "cost": 0.0, "messages": 0}
    files = list((d / "sessions").glob("*.jsonl")) + list(
        (d / "workspace" / ".pi-glla" / "audit-jobs").glob("*/session.jsonl"))
    for f in files:
        for line in f.read_text(errors="replace").splitlines():
            try:
                r = json.loads(line)
            except Exception:
                continue
            m = r.get("message") or {}
            u = m.get("usage") or r.get("usage")
            if not isinstance(u, dict) or not any(k in u for k in ("input", "output", "totalTokens")):
                continue
            tot["messages"] += 1
            for k in ("input", "output", "cacheRead"):
                tot[k] += int(u.get(k) or 0)
            c = u.get("cost")
            if isinstance(c, dict):
                tot["cost"] += float(c.get("total") or 0)
    tot["cost_usd_nominal"] = round(
        tot["input"] * 0.3 / 1e6 + tot["output"] * 1.2 / 1e6 + tot["cacheRead"] * 0.006 / 1e6, 4)
    return tot


# ----------------------------------------------------------------- evaluate
def evaluate(trial):
    mapping = {n: f"C{i+1}" for i, n in enumerate(random.sample(NAMES, 2))}
    out = {"trial": trial, "anonymization": mapping, "candidates": {}}
    for name in NAMES:
        anon = mapping[name]
        src = cdir(name, trial) / "workspace"
        work = ROOT / "harness" / ".tmp" / f"eval-{anon}-{trial}"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        for child in src.iterdir():
            if child.name in (".git", ".pi", ".pi-glla"):
                continue
            tgt = work / child.name
            shutil.copytree(child, tgt, symlinks=True) if child.is_dir() else shutil.copy2(child, tgt)
        tests = {}
        for suite, label in (("test_report_svg.py", "frozen"), ("test_adversarial_extra.py", "adversarial")):
            p = docker("run", "--rm", "--network", "none",
                       "-v", f"{work}:/candidate",
                       "-v", f"{ROOT / 'evaluation' / 'frozen'}:/eval:ro",
                       "-v", f"{ROOT / 'baseline' / 'pi-bolt' / 'bench' / 'results' / '2026-10-10-pi-bolt-0.7.3'}:/fixture/results:ro",
                       "-v", f"{ROOT / 'evaluation' / 'fixtures' / 'baseline-svgs'}:/fixture/baseline-svgs:ro",
                       "-e", "CANDIDATE_ROOT=/candidate",
                       "-e", "FIXTURE_RESULTS=/fixture/results",
                       "-e", "BASELINE_SVGS=/fixture/baseline-svgs",
                       EVAL, "python3", "-m", "pytest", "-v", f"/eval/{suite}")
            text = (p.stdout or "") + (p.stderr or "")
            (R / f"{name}-{trial}-{label}-tests.log").write_text(text)
            tests[label] = {
                "passed": len(re.findall(r"PASSED", text)),
                "failed": len(re.findall(r"FAILED", text)),
                "failures": sorted(set(re.findall(r"FAILED \S+::(\S+)", text))),
                "summary": next((l for l in text.splitlines() if re.search(r"\d+ (passed|failed)", l)), ""),
            }
        files = R / f"{name}-{trial}-changed-files.txt"
        changed = []
        for line in files.read_text().splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                changed.append({"status": parts[0], "path": parts[1]})
        out["candidates"][name] = {
            "anonymous_id": anon, "tests": tests, "changed": changed,
            "datasets_modified": [c for c in changed if c["path"].startswith("bench/results/")],
            "out_of_scope": [c for c in changed if not (
                c["path"] == "bench/report.py" or c["path"].startswith("bench/tests/")
                or re.match(r"bench/test_.*\.py$|bench/check_svg.*\.py$", c["path"])
                or c["path"].startswith("docs/") or c["path"] in ("bench/README.md", "README.md"))],
        }
        shutil.rmtree(work, ignore_errors=True)
    (R / f"replication-evaluation-{trial}.json").write_text(json.dumps(out, indent=1))
    for n in NAMES:
        t = out["candidates"][n]["tests"]
        print(f"{n} ({mapping[n]}): frozen {t['frozen']['passed']}p/{t['frozen']['failed']}f, "
              f"adversarial {t['adversarial']['passed']}p/{t['adversarial']['failed']}f")
    return out


# ---------------------------------------------------------------- aggregate
def aggregate():
    rows = {}
    for trial in TRIALS:
        meta = json.loads((R / f"trial-{trial}-runmeta.json").read_text())
        for run in meta["runs"]:
            name = run["name"]
            tl = timeline(name, trial)
            tl["tokens"] = tokens(cdir(name, trial))
            tl["valid"] = run["valid"]
            tl["invalid_reasons"] = run["invalid_reasons"]
            tl["relay_failed"] = run["relay"]["failed"]
            tl["relay_requests"] = run["relay"]["requests"]
            tl["sleep_events"] = len(run.get("sleep_events") or [])
            tl["externally_verified_at_s"] = run.get("externally_verified_at_s")
            rows.setdefault(name, []).append(tl)
    (R / "replication-timelines.json").write_text(json.dumps(rows, indent=1))
    summary = {}
    for name, runs in rows.items():
        valid = [r for r in runs if r["valid"]]
        def stat(key, f=None):
            f = f or (lambda r, k=key: r.get(k))
            vals = [f(r) for r in valid if f(r) is not None]
            if not vals:
                return None
            return {"median": round(statistics.median(vals), 1),
                    "min": round(min(vals), 1), "max": round(max(vals), 1), "n": len(vals)}
        summary[name] = {
            "runs": len(runs), "valid": len(valid),
            "total_elapsed_s": stat("total_elapsed_s"),
            "goal_confirmed_s": stat("goal_confirmed_s"),
            "first_code_write_s": stat("first_code_write_s"),
            "first_completion_claim_s": stat("first_completion_claim_s"),
            "last_code_write_s": stat("last_code_write_s"),
            "post_last_write_s": stat("total_elapsed_s", lambda r: (r["total_elapsed_s"] - r["last_code_write_s"])
                                      if r.get("last_code_write_s") else None),
            "requests": stat("requests"),
            "input_tokens": stat("tokens", lambda r: r["tokens"]["input"]),
            "output_tokens": stat("tokens", lambda r: r["tokens"]["output"]),
            "cache_read": stat("tokens", lambda r: r["tokens"]["cacheRead"]),
            "cost_usd": stat("tokens", lambda r: r["tokens"]["cost_usd_nominal"]),
            "max_request_gap_s": stat("max_request_gap_s"),
            "audit_verdicts": [r["audit_verdicts"] for r in valid],
            "audit_jobs": [r["audit_jobs"] for r in valid],
        }
    (R / "replication-summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "collect":
        for n in NAMES:
            collect(n, sys.argv[2])
    elif cmd == "collect-one":
        collect(sys.argv[2], sys.argv[3])
    elif cmd == "timeline":
        for n in NAMES:
            print(json.dumps(timeline(n, sys.argv[2]), indent=1))
    elif cmd == "evaluate":
        evaluate(sys.argv[2])
    elif cmd == "aggregate":
        aggregate()
