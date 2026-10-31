#!/usr/bin/env python3
"""Derive a phase timeline for each competitor from its collected artifacts.

Everything here is reconstructed from recorded evidence (RPC event stream with
monotonic timestamps, the relay request log, tool-call arguments and the
extensions' persisted state). Nothing is inferred from an assistant message
alone.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
R = ROOT / "results"
WRITE_TOOLS = {"write", "edit", "str_replace", "create_file", "apply_patch", "multi_edit"}
TEST_RX = re.compile(r"pytest|unittest|test_report|report\.py", re.I)


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


def timeline(name, trial="s0"):
    comp = ROOT / "competitors" / name
    ev = load_jsonl(comp / "logs" / "events.jsonl")
    final = json.loads((comp / "logs" / "final-state.json").read_text())
    relay = load_jsonl(comp / "logs" / "relay.jsonl")
    ms = final["milestones"]

    writes, tests, tests_ok = [], [], []
    for e in ev:
        rec = e.get("record") or {}
        if e.get("dir") != "pi":
            continue
        if rec.get("type") == "tool_execution_start":
            args = rec.get("args") or {}
            tool = (rec.get("toolName") or "").lower()
            path = str(args.get("path") or args.get("file_path") or args.get("filePath") or "")
            if tool in WRITE_TOOLS or (path.endswith((".py", ".md", ".yml")) and tool in WRITE_TOOLS | {"patch"}):
                writes.append({"t": e["t"], "tool": tool, "path": path})
            cmd = str(args.get("command") or "")
            if tool == "bash" and TEST_RX.search(cmd) and "report.py --images" not in cmd:
                tests.append({"t": e["t"], "cmd": cmd[:200]})
        if rec.get("type") == "tool_execution_end" and not rec.get("isError"):
            pass

    # Successful test commands: tool_execution_end without error correlated by time.
    ends = [(e["t"], (e.get("record") or {})) for e in ev
            if e.get("dir") == "pi" and (e.get("record") or {}).get("type") == "tool_execution_end"]
    for tst in tests:
        nxt = [t for t, r in ends if t >= tst["t"] and not r.get("isError")]
        if nxt:
            tests_ok.append(nxt[0])

    # Model requests with wall-clock -> session-relative seconds
    t0 = final["started_wall"] if "started_wall" in final else None
    start_wall = None
    for e in ev:
        if e.get("kind") == "milestone" and e.get("name") == "process_launch":
            start_wall = e["wall"]
            break
    audit = []
    if start_wall:
        for r in relay:
            if r.get("path", "").endswith("chat/completions"):
                audit.append({
                    "t": round(r["t_wall"] - start_wall, 1),
                    "duration": round(r.get("duration") or 0, 1),
                    "audit": bool(r.get("audit")),
                    "status": r.get("status"),
                })
    audit_only = [a for a in audit if a["audit"]]

    # Persisted goal status transitions (goal-x) / ledger (glla)
    goal_status = []
    for p in comp.glob("workspace/.pi/goals/goal_events.jsonl"):
        for row in load_jsonl(p):
            goal_status.append(row)
    for p in comp.glob("workspace/.pi-glla/audits.jsonl"):
        for row in load_jsonl(p):
            goal_status.append(row)

    last_write = writes[-1]["t"] if writes else None
    first_audit = audit_only[0]["t"] if audit_only else None
    last_audit_end = max((a["t"] + a["duration"] for a in audit_only), default=None)
    total = final.get("duration_seconds")

    return {
        "name": name,
        "total_elapsed_s": total,
        "goal_submitted_s": 0.0,
        "goal_confirmed_s": (ms.get("goal_confirmed") or {}).get("t"),
        "first_code_write_s": writes[0]["t"] if writes else None,
        "last_code_write_s": last_write,
        "code_writes": len(writes),
        "write_paths": sorted({w["path"] for w in writes if w["path"]}),
        "test_commands": len(tests),
        "first_test_s": tests[0]["t"] if tests else None,
        "last_test_s": tests[-1]["t"] if tests else None,
        "first_audit_s": first_audit,
        "last_audit_end_s": round(last_audit_end, 1) if last_audit_end else None,
        "audit_requests": len(audit_only),
        "audit_wall_s": round(sum(a["duration"] for a in audit_only), 1) if audit_only else None,
        "longest_audit_s": round(max((a["duration"] for a in audit_only), default=0), 1) if audit_only else None,
        "requests": len(audit),
        "requests_failed": len([a for a in audit if a["status"] not in (200, None)]),
        "first_status_complete_s": (ms.get("first_status_complete") or {}).get("t"),
        "first_completion_claim_s": (ms.get("first_completion_claim") or {}).get("t"),
        "settled_s": total,
        "audit_span_after_last_write_s": round(total - last_write, 1) if last_write else None,
        "goal_status_records": len(goal_status),
    }


if __name__ == "__main__":
    out = {n: timeline(n) for n in ("glla", "goal-x")}
    (R / "timelines.json").write_text(json.dumps(out, indent=1))
    for n, t in out.items():
        print(n, json.dumps(t, indent=1))
