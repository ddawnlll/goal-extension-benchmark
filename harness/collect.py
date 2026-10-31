#!/usr/bin/env python3
"""Collect one run's artifacts out of its disposable volume.

Writes, under competitors/<name>/:
  logs/           runner events, milestones, relay log, final state, stderr
  sessions/       the Pi session transcript(s)
  agent-config/   models.json and settings.json actually used
  extensions/     the pinned extension package as installed
  workspace/      the full modified tree (no .git) for forensics
and under results/:
  <name>-<trial>.patch        canonical diff from the pinned baseline
  <name>-<trial>-metrics.json derived timings and counters
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
ENV = dict(os.environ, DOCKER_HOST=os.environ.get(
    "DOCKER_HOST", f"unix://{Path.home()}/.colima/default/docker.sock"))
IMAGE = "goalbench/base:1"


def sh(cmd, check=False, **kw):
    return subprocess.run(cmd, text=True, capture_output=True, env=ENV, check=check, **kw)


def docker(*a, **kw):
    return sh(["docker", *a], **kw)


def copy_out(name, trial):
    vol = f"gb-{name}-home"
    dest = ROOT / "competitors" / name
    tmp = ROOT / "harness" / ".tmp" / f"collect-{name}-{trial}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    docker("run", "--rm", "--user", "0", "--entrypoint", "/bin/bash",
           "-v", f"{vol}:/h", "-v", f"gb-{name}-relay:/relaylog:ro", "-v", f"{tmp}:/out", IMAGE, "-lc",
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
    return dest


def make_patch(name, trial):
    """Diff the collected tree against the pinned baseline, canonically."""
    base = ROOT / "baseline" / "pi-bolt"
    work = ROOT / "harness" / ".tmp" / f"patch-{name}-{trial}"
    shutil.rmtree(work, ignore_errors=True)
    subprocess.run(["cp", "-a", str(base), str(work)], check=True)
    # Replace the tracked tree with the competitor's, keeping the baseline .git.
    for child in work.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    src = ROOT / "competitors" / name / "workspace"
    for child in src.iterdir():
        if child.name in (".pi", ".pi-glla", ".git"):
            continue
        target = work / child.name
        if child.is_dir():
            shutil.copytree(child, target, symlinks=True)
        else:
            shutil.copy2(child, target)
    # Restore baseline-only Pi project resources that are runtime state, not work.
    sh(("git", "-C", str(work), "checkout", "--", ".pi"))
    shutil.rmtree(work / ".pi-glla", ignore_errors=True)
    sh(("git", "-C", str(work), "config", "user.email", "eval@benchmark.invalid"))
    sh(("git", "-C", str(work), "config", "user.name", "benchmark-eval"))
    sh(("git", "-C", str(work), "add", "-A"))
    diff = sh(("git", "-C", str(work), "diff", "--cached", "--binary"))
    patch = RESULTS / f"{name}-{trial}.patch"
    patch.write_text(diff.stdout)
    stat = sh(("git", "-C", str(work), "diff", "--cached", "--stat")).stdout
    (RESULTS / f"{name}-{trial}-diffstat.txt").write_text(stat)
    files = sh(("git", "-C", str(work), "diff", "--cached", "--name-status")).stdout
    (RESULTS / f"{name}-{trial}-changed-files.txt").write_text(files)
    shutil.rmtree(work, ignore_errors=True)
    return patch, stat, files


def load_jsonl(path):
    out = []
    try:
        for line in Path(path).read_text(errors="replace").splitlines():
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    except OSError:
        pass
    return out


def usage_from_tail(tail):
    """Pull the last provider usage block out of a streamed response tail."""
    if not tail:
        return None
    best = None
    for m in re.finditer(r'"usage"\s*:\s*\{', tail):
        start = m.end() - 1
        depth, i = 0, start
        while i < len(tail):
            if tail[i] == "{":
                depth += 1
            elif tail[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        best = json.loads(tail[start:i + 1])
                    except Exception:
                        pass
                    break
            i += 1
    return best


def metrics(name, trial):
    comp = ROOT / "competitors" / name
    final = json.loads((comp / "logs" / "final-state.json").read_text()) if (comp / "logs" / "final-state.json").exists() else {}
    meta = json.loads((RESULTS / f"{name}-{trial}-runmeta.json").read_text()) \
        if (RESULTS / f"{name}-{trial}-runmeta.json").exists() else {}
    relay = load_jsonl(comp / "logs" / "relay.jsonl")
    ms = final.get("milestones") or {}
    c = final.get("counters") or {}

    def t(key):
        v = ms.get(key)
        return round(v["t"], 3) if isinstance(v, dict) and "t" in v else None

    first_req = min((r["t_wall"] for r in relay if r.get("path", "").endswith("chat/completions")), default=None)
    audit_recs = [r for r in relay if r.get("audit")]
    audit_times = [r.get("t_wall") for r in audit_recs if r.get("t_wall")]
    audit_durations = [r.get("duration") for r in audit_recs if r.get("duration") is not None]

    req_usage = []
    for r in relay:
        u = usage_from_tail(r.get("usage_tail"))
        if u:
            req_usage.append({"t_wall": r.get("t_wall"), "audit": r.get("audit"),
                              "input": u.get("input"), "output": u.get("output"),
                              "cacheRead": u.get("cacheRead") or (u.get("prompt_tokens_details") or {}).get("cached_tokens")})
    verified_wall = None
    if meta.get("externally_verified_at_s") is not None:
        verified_wall = meta["started_wall"] + meta["externally_verified_at_s"]

    def tokens_after(ts):
        if ts is None:
            return None
        sel = [r for r in req_usage if r["t_wall"] and r["t_wall"] >= ts]
        return {"requests": len(sel),
                "input": sum(r["input"] or 0 for r in sel),
                "output": sum(r["output"] or 0 for r in sel)}

    settle = final.get("finished_wall")
    out = {
        "name": name, "trial": trial,
        "classification_inputs": {
            "exit_reason": final.get("exit_reason"),
            "externally_verified_at_s": meta.get("externally_verified_at_s"),
            "duration_seconds": final.get("duration_seconds"),
            "pi_exit_code": final.get("pi_exit_code"),
        },
        "milestones": {k: t(k) for k in (
            "process_launch", "goal_submitted", "first_ui_question", "goal_confirmed",
            "run_started", "first_code_modification", "first_test_run", "first_successful_test_run",
            "first_completion_claim", "first_audit_request", "first_status_complete",
            "first_auditor_child", "agent_settled", "run_stopped")},
        "durations": {
            "goal_setup_time_s": round(t("goal_confirmed") - t("goal_submitted"), 3)
                if t("goal_confirmed") and t("goal_submitted") is not None else None,
            "implementation_time_s": round(t("first_completion_claim") - t("goal_confirmed"), 3)
                if t("first_completion_claim") and t("goal_confirmed") else None,
            "completion_overhead_s": round(final.get("duration_seconds", 0) - t("first_completion_claim"), 3)
                if t("first_completion_claim") and final.get("duration_seconds") else None,
            "total_elapsed_s": final.get("duration_seconds"),
            "time_to_first_claim_vs_acceptance_s": round(settle - (ms.get("first_completion_claim") or {}).get("wall"), 3)
                if settle and (ms.get("first_completion_claim") or {}).get("wall") else None,
        },
        "counters": c,
        "tokens": {
            "main_session": ms.get("tokens"),
            "relay_requests": len([r for r in relay if r.get("path", "").endswith("chat/completions")]),
            "relay_audit_requests": len(audit_recs),
            "relay_usage_records": len(req_usage),
            "relay_input": sum(r["input"] or 0 for r in req_usage) if req_usage else None,
            "relay_output": sum(r["output"] or 0 for r in req_usage) if req_usage else None,
            "after_external_verification": tokens_after(verified_wall),
        },
        "auditor": {
            "requests": len(audit_recs),
            "completed": len([d for d in audit_durations if d is not None]),
            "total_audit_wall_s": round(sum(audit_durations), 2) if audit_durations else None,
            "longest_audit_s": round(max(audit_durations), 2) if audit_durations else None,
            "longest_gap_between_audit_requests_s": round(max(
                (b - a for a, b in zip(sorted(audit_times), sorted(audit_times)[1:])), default=0), 2)
                if len(audit_times) > 1 else None,
            "failed_requests": len([r for r in audit_recs if r.get("status") not in (200, None)]),
            "client_aborts": len([r for r in relay if r.get("client_abort")]),
        },
        "post_verification": {
            "externally_verified_at_s": meta.get("externally_verified_at_s"),
            "settled_at_s": final.get("duration_seconds"),
            "post_verification_delay_s": round(final.get("duration_seconds", 0) - meta["externally_verified_at_s"], 1)
                if meta.get("externally_verified_at_s") is not None and final.get("duration_seconds") else None,
            "verifier_samples": len(meta.get("verifier_samples") or []),
            "first_verifier_pass": next((s for s in (meta.get("verifier_samples") or []) if s.get("ok")), None),
        },
        "process": {"last_rss_kb": final.get("last_rss_kb"), "surviving_children": final.get("surviving_children")},
        "wall_clock": {"started_wall": meta.get("started_wall"), "ended_wall": meta.get("ended_wall"),
                       "wall_seconds": meta.get("wall_seconds")},
        "prompt": {"task_sha256": final.get("task_sha256"), "prompt_sha256": final.get("prompt_sha256")},
        "status_log_tail": (final.get("status_log") or [])[-5:],
        "claims": final.get("claims"),
        "generated_wall": time.time(),
    }
    (RESULTS / f"{name}-{trial}-metrics.json").write_text(json.dumps(out, indent=1))
    return out


def main():
    name, trial = sys.argv[1], sys.argv[2]
    copy_out(name, trial)
    patch, stat, files = make_patch(name, trial)
    m = metrics(name, trial)
    print(f"{name}: patch {patch.stat().st_size} bytes")
    print(stat)
    print(json.dumps(m["durations"], indent=1))
    print(json.dumps(m["counters"]))


if __name__ == "__main__":
    main()
