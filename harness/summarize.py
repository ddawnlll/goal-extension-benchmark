#!/usr/bin/env python3
"""Build comparison.csv and the data-driven tables for FINAL_REPORT.md."""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
R = ROOT / "results"
NAMES = ["glla", "goal-x"]


def load(name, trial="s0"):
    m = R / f"{name}-{trial}-metrics.json"
    e = R / "independent-evaluation.json"
    metrics = json.loads(m.read_text()) if m.exists() else {}
    ev = json.loads(e.read_text()) if e.exists() else {}
    return metrics, (ev.get("candidates", {}).get(name) or {})


def fmt(v, unit="", nd=1):
    if v is None:
        return "unavailable"
    if isinstance(v, float):
        return f"{v:.{nd}f}{unit}"
    if isinstance(v, int):
        return f"{v:,}{unit}"
    return f"{v}{unit}"


def main(trial="s0"):
    rows = {}
    for n in NAMES:
        m, e = load(n, trial)
        t = e.get("tests", {})
        rows[n] = {"m": m, "e": e, "tests": t}

    header = ["metric", "glla", "pi-goal-x"]
    table = []
    def add(label, fn):
        table.append([label, *[fn(rows[n]) for n in NAMES]])

    add("Frozen acceptance tests", lambda r: f"{r['tests'].get('frozen',{}).get('passed',0)} passed / {r['tests'].get('frozen',{}).get('failed',0)} failed")
    add("Independent adversarial tests", lambda r: f"{r['tests'].get('adversarial',{}).get('passed',0)} passed / {r['tests'].get('adversarial',{}).get('failed',0)} failed")
    add("Changed files", lambda r: r["e"].get("scope", {}).get("count"))
    add("Insertions / deletions", lambda r: f"{r['e'].get('scope',{}).get('insertions')} / {r['e'].get('scope',{}).get('deletions')}")
    add("Out-of-scope files", lambda r: len(r["e"].get("scope", {}).get("out_of_scope") or []))
    add("Datasets modified", lambda r: len(r["e"].get("scope", {}).get("datasets_modified") or []))
    add("Requirement coverage of confirmed contract", lambda r: r["e"].get("goal_understanding", {}).get("coverage"))
    add("Goal setup time, s", lambda r: r["m"].get("durations", {}).get("goal_setup_time_s"))
    add("Implementation time, s", lambda r: r["m"].get("durations", {}).get("implementation_time_s"))
    add("Completion overhead, s", lambda r: r["m"].get("durations", {}).get("completion_overhead_s"))
    add("Total elapsed, s", lambda r: r["m"].get("durations", {}).get("total_elapsed_s"))
    add("Total tokens (main session)", lambda r: (r["m"].get("tokens", {}).get("main_session") or {}))
    add("Model requests (relay)", lambda r: r["m"].get("tokens", {}).get("relay_requests"))
    add("Audit requests", lambda r: r["m"].get("auditor", {}).get("requests"))
    add("Audit wall time, s", lambda r: r["m"].get("auditor", {}).get("total_audit_wall_s"))
    add("Longest audit, s", lambda r: r["m"].get("auditor", {}).get("longest_audit_s"))
    add("Tool calls", lambda r: r["m"].get("counters", {}).get("tool_calls"))
    add("Test runs", lambda r: r["m"].get("counters", {}).get("test_runs"))
    add("Completion claims", lambda r: r["m"].get("counters", {}).get("completion_claims"))
    add("Externally verified at, s", lambda r: r["m"].get("post_verification", {}).get("externally_verified_at_s"))
    add("Post-verification delay, s", lambda r: r["m"].get("post_verification", {}).get("post_verification_delay_s"))
    add("Terminal state", lambda r: r["m"].get("classification_inputs", {}).get("exit_reason"))

    with open(R / f"comparison-{trial}.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for row in table:
            w.writerow([row[0]] + [json.dumps(v) if isinstance(v, (dict, list)) else v for v in row[1:]])
    print("| Metric | GLLA | pi-goal-x |")
    print("|---|---|---|")
    for row in table:
        vals = []
        for v in row[1:]:
            if isinstance(v, dict):
                vals.append(f"{v.get('input',0):,} in / {v.get('output',0):,} out / ${v.get('cost',0):.4f}")
            elif isinstance(v, layout := ()) if False else isinstance(v, tuple):
                vals.append(str(v))
            else:
                vals.append(str(v))
        print(f"| {row[0]} | {vals[0]} | {vals[1]} |")


if __name__ == "__main__":
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else "s0")
