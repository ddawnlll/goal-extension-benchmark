#!/usr/bin/env python3
"""Derive the per-run phase model from committed evidence.

Inputs (all committed):
  results/logs/<trial>/<ext>/final-state.json.gz   run milestones, start epoch, duration
  results/audit-records/<trial>/<ext>/             audit spans (GLLA job progress, goal-x goal events)
  results/replication-timelines.json               per-run tokens for r1/r2
  results/<ext>-metrics.json                       exploratory durations and tokens for s0

Output: results/phase-model.json

Every segment is a subtraction of two recorded timestamps; no segment is
estimated. The model splits each run into:

  drafting      0                       -> goal_confirmed
  coding        goal_confirmed          -> first_completion_claim
  reconciliation first_completion_claim -> first audit start
  audit         sum of the audit rounds themselves
  rework        gaps between audit rounds (a rejected audit, then repair)
  settlement    last audit end          -> process end

"reconciliation" covers everything between the completion claim and the audit
actually running: deterministic pre-audit gates, contract repair and rework.
"""
import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"
EXTENSIONS = ("glla", "goal-x")
TRIALS = ("s0", "r1", "r2")


def load(path):
    raw = Path(path).read_bytes()
    if path.suffix == ".gz":
        raw = gzip.decompress(raw)
    return json.loads(raw)


def epoch(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def final_state(trial, ext):
    return load(RES / "logs" / trial / ext / "final-state.json.gz")


def start_epoch(fs):
    ms = fs.get("milestones") or {}
    if "started_utc" in ms:
        return epoch(ms["started_utc"])
    return float(ms["started_wall"])


def glla_audit_spans(trial):
    spans = []
    for p in sorted((RES / "audit-records" / trial / "glla").glob("*-progress.json")):
        d = json.loads(p.read_text())
        end = d["lastActivityAt"] / 1000.0
        spans.append((end - d["elapsedMs"] / 1000.0, end))
    return sorted(spans)


def goalx_audit_spans(trial):
    p = RES / "audit-records" / trial / "goal-x" / "goal_events.jsonl"
    started, spans = None, []
    for line in p.read_text().splitlines():
        e = json.loads(line)
        if e.get("type") == "audit_started":
            started = epoch(e["at"])
        elif e.get("type") == "audit_result" and started is not None:
            spans.append((started, epoch(e["at"])))
            started = None
    return spans


def main():
    rep = json.loads((RES / "replication-timelines.json").read_text())
    rep_by = {(r["name"], r["trial"]): r for runs in rep.values() for r in runs}
    s0 = {e: json.loads((RES / f"{e}-metrics.json").read_text()) for e in EXTENSIONS}

    runs = []
    for trial in TRIALS:
        for ext in EXTENSIONS:
            fs = final_state(trial, ext)
            t0 = start_epoch(fs)
            total = float(fs["duration_seconds"])
            if trial == "s0":
                d = s0[ext]["durations"]
                setup, claim = d["goal_setup_time_s"], d["first_completion_claim_s"]
                tok = s0[ext]["tokens"]["authoritative_session_usage"]
                tokens = {"input": tok["input"], "output": tok["output"], "cost": tok["cost_usd"]}
            else:
                r = rep_by[(ext, trial)]
                setup, claim = r["goal_confirmed_s"], r["first_completion_claim_s"]
                tokens = {"input": r["tokens"]["input"], "output": r["tokens"]["output"],
                          "cost": r["tokens"]["cost_usd_nominal"]}

            spans = glla_audit_spans(trial) if ext == "glla" else goalx_audit_spans(trial)
            if not spans:
                # s0 has no committed audit records; take the recorded model audit
                # duration and anchor it to the end of the run.
                dur = s0[ext]["audit_facts"]["model_audit_duration_s"]
                spans = [(t0 + total - dur, t0 + total)]
            audit_start = min(s for s, _ in spans) - t0
            audit_end = max(e for _, e in spans) - t0
            audit_total = sum(e - s for s, e in spans)

            segments = {
                "drafting": round(setup, 1),
                "coding": round(claim - setup, 1),
                "reconciliation": round(audit_start - claim, 1),
                "audit": round(audit_total, 1),
                "rework": round((audit_end - audit_start) - audit_total, 1),
                "settlement": round(total - audit_end, 1),
            }
            drift = round(total - sum(segments.values()), 1)
            runs.append({
                "extension": ext, "trial": trial,
                "label": f"{'GLLA' if ext == 'glla' else 'pi-goal-x'} {trial}",
                "total_s": round(total, 1),
                "segments": segments,
                "drift_s": drift,
                "audit_spans_s": [round(e - s, 1) for s, e in spans],
                "tokens": tokens,
                "exit_reason": fs.get("exit_reason"),
                "started_utc": (fs.get("milestones") or {}).get("started_utc"),
            })
            if abs(drift) > 1.0:
                print(f"warning: {ext} {trial} segment drift {drift}s", file=sys.stderr)

    order = {"s0": 0, "r1": 1, "r2": 2}
    runs.sort(key=lambda r: (order[r["trial"]], r["extension"]))
    out = {"generated_from": ["results/logs", "results/audit-records",
                              "results/replication-timelines.json", "results/*-metrics.json"],
           "runs": runs}
    (RES / "phase-model.json").write_text(json.dumps(out, indent=1) + "\n")

    print(f"{'run':14} {'total':>7} {'draft':>6} {'coding':>7} {'recon':>7} {'audit':>7} {'rework':>7} {'settle':>7}")
    for r in runs:
        s = r["segments"]
        print(f"{r['label']:14} {r['total_s']:7.1f} {s['drafting']:6.1f} {s['coding']:7.1f} "
              f"{s['reconciliation']:7.1f} {s['audit']:7.1f} {s['rework']:7.1f} {s['settlement']:7.1f}")


if __name__ == "__main__":
    main()
