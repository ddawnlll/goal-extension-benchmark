#!/usr/bin/env python3
"""Benchmark runner: drives one isolated Pi-Bolt instance over RPC.

Runs inside the worker container, as the unprivileged `agent` user. It owns the
Pi-Bolt child process, answers extension UI requests from a recorded policy,
instruments the lifecycle with an external monotonic clock, and writes:

  <logs>/events.jsonl   every record exchanged with Pi, timestamped
  <logs>/milestones.json curated lifecycle timestamps and counters
  <logs>/samples.jsonl  periodic process/tree/git/relay samples
  <logs>/ui-script.json every extension UI question and the scripted answer
  <logs>/final-state.json terminal state and evidence

It never modifies the shared task and never edits the worker's code itself.
"""
import json
import os
import queue
import re
import select
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

CFG = json.loads(Path("/home/agent/run/config.json").read_text())
NAME = CFG["name"]
LOGS = Path("/home/agent/logs")
WORK = Path("/home/agent/work")
RELAY_LOG = Path(CFG.get("relay_log", "/var/log/relay/relay.jsonl"))

EVENTS = LOGS / "events.jsonl"
SAMPLES = LOGS / "samples.jsonl"
UI_SCRIPT = LOGS / "ui-script.json"
MILESTONES = LOGS / "milestones.json"
FINAL = LOGS / "final-state.json"

MONO = time.monotonic
T0 = MONO()

# ---------------------------------------------------------------- shared task
# The clarification answer is identical for both competitors and is derived
# only from the shared task text, so neither extension gets extra information.
CLARIFY = (
    "Use the shared task exactly as written. Keep every listed requirement and constraint. "
    "Do not narrow the scope, do not drop the adversarial tests, do not drop XML-parser "
    "validation, and do not change the CLI or benchmark datasets. If something is genuinely "
    "ambiguous, choose the most conservative standard-library implementation and say so."
)

# Requirement tokens used to judge whether a proposed contract kept the task.
REQUIRED = [
    ("escap", r"escap|xml escaping|entity|sanitiz"),
    ("special chars", r"&|<|>|quote|apostroph|special char"),
    ("unicode", r"unicode|utf-?8"),
    ("injection", r"inject|malicious|adversarial|attack|xss"),
    ("double escape", r"double[- ]escap"),
    ("appearance", r"appearance|visual|unchanged output|existing output"),
    ("regression tests", r"regression test|test|pytest|unittest"),
    ("xml validation", r"xml parser|xml\.etree|parse.*xml|validat"),
    ("existing tests", r"existing test|test suite|run.*test"),
    ("documentation", r"document|comment|docstring|readme"),
    ("scope", r"no unrelated|unrelated refactor|minimal|scope"),
    ("cli/data", r"cli|command-line|dataset|interface"),
]
APPROVE_WORDS = re.compile(r"approve|confirm|accept|yes|proceed|start|begin|continue|use audit|enable", re.I)
REJECT_WORDS = re.compile(r"skip|disable|without audit|no audit|off\b|cancel|discard", re.I)
DONE_WORDS = re.compile(
    r"\b(goal (?:is )?(?:complete|completed|verified|done)|all (?:tasks|items) (?:are )?complete|"
    r"verified complete|completion accepted|goal archived|no active goal|audit (?:passed|approved)|"
    r"<approved\s*/?>)\b",
    re.I,
)
CLAIM_WORDS = re.compile(
    r"\b(done|complete|completed|finished|implemented|all tests pass|tests pass|ready for review|"
    r"verification complete)\b",
    re.I,
)
TEST_CMD = re.compile(
    r"(pytest|unittest|python3? -m (?:pytest|unittest)|python3? .*test|report\.py|xml\.etree|"
    r"\./test\.sh|vitest|npm test)",
    re.I,
)
DEFAULT_LIMIT_S = 3600
LIMIT_S = float(CFG.get("max_seconds", DEFAULT_LIMIT_S))
STALL_S = float(CFG.get("stall_seconds", 300))
STATUS_POLL_S = float(CFG.get("status_poll_seconds", 0))
MAX_UI = int(CFG.get("max_ui_answers", 60))


def now():
    return {"t": round(MONO() - T0, 3), "wall": round(time.time(), 3)}


def utc(wall=None):
    import datetime as _dt
    return _dt.datetime.fromtimestamp(wall or time.time(), _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def append(path, record):
    with path.open("a") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


milestones = {
    "name": NAME,
    "extension": CFG["extension"],
    "trial": CFG.get("trial", "s0"),
    "started_wall": time.time(),
    "started_utc": utc(),
    "limit_seconds": LIMIT_S,
    "thinking": CFG.get("thinking"),
}
counters = {
    "ui_questions": 0,
    "ui_answers": 0,
    "ui_deviations": 0,
    "turns": 0,
    "tool_calls": 0,
    "test_runs": 0,
    "test_runs_ok": 0,
    "audit_requests": 0,
    "audit_completions": 0,
    "audit_failures": 0,
    "completion_claims": 0,
    "status_polls": 0,
    "compactions": 0,
    "retries": 0,
}
ui_log = []
status_log = []
claims = []
audit_seen = set()
relay_pos = 0
last_activity = MONO()
last_substantive = MONO()


def mark(key, extra=None):
    if key not in milestones:
        milestones[key] = {**now(), "utc": utc(), **(extra or {})}
        append(EVENTS, {"dir": "harness", "kind": "milestone", "name": key, **milestones[key]})


# ------------------------------------------------------------------ process
env = dict(os.environ)
env.update(CFG.get("env", {}))
cmd = [
    "pi", "--mode", "rpc",
    "--provider", CFG["provider"],
    "--model", CFG["model"],
    "--thinking", CFG.get("thinking", "high"),
    "--session-dir", str(Path(env.get("PI_CODING_AGENT_DIR", "/home/agent/.pi/agent")) / "sessions"),
    "--continue",
    "--name", f"{NAME}-{CFG.get('trial', 's0')}",
]
if CFG.get("extra_args"):
    cmd += CFG["extra_args"]

mark("process_launch", {"cmd": cmd})
proc = subprocess.Popen(cmd, cwd=str(WORK), env=env, stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
mark("pi_pid", {"pid": proc.pid})

stderr_path = LOGS / "pi-stderr.log"
stderr_fh = stderr_path.open("ab")


def pump_stderr():
    for line in iter(proc.stderr.readline, b""):
        stderr_fh.write(line)
        stderr_fh.flush()


threading.Thread(target=pump_stderr, daemon=True).start()

line_q = queue.Queue()
def pump_stdout():
    while True:
        line = proc.stdout.readline()
        if not line:
            line_q.put(None)
            return
        line_q.put(line)

threading.Thread(target=pump_stdout, daemon=True).start()


def next_record(timeout=0.5):
    try:
        line = line_q.get(timeout=timeout)
    except queue.Empty:
        return False, None
    if line is None:
        return True, None
    try:
        return True, json.loads(line)
    except Exception:
        return True, {"type": "__unparsed__", "raw": line[:500].decode("utf-8", "replace")}

# ------------------------------------------------------------------ RPC I/O
write_lock = threading.Lock()
response_waiters = {}
responses = {}


def send(obj):
    raw = (json.dumps(obj, ensure_ascii=False) + "\n").encode()
    with write_lock:
        try:
            proc.stdin.write(raw)
            proc.stdin.flush()
        except (BrokenPipeError, ValueError):
            pass
    append(EVENTS, {"dir": "host", **now(), "record": obj})


def request(obj, timeout=30):
    rid = obj.setdefault("id", f"h{int(MONO() * 1000) % 10**9}")
    ev = threading.Event()
    response_waiters[rid] = ev
    send(obj)
    ev.wait(timeout)
    return responses.get(rid)


def handle_ui(req):
    """Deterministic, identical policy for both competitors. Every question and
    answer is recorded; approvals are gated on requirement coverage."""
    counters["ui_questions"] += 1
    method = req.get("method")
    text = " ".join(str(req.get(k) or "") for k in ("title", "message", "prefill"))
    if req.get("options"):
        text += " " + " | ".join(str(o) for o in req["options"])
    entry = {"t": round(MONO() - T0, 3), "method": method, "request": req, "decision": None}
    if method in ("select", "confirm", "input", "editor") and "first_ui_question" not in milestones:
        mark("first_ui_question", {"method": method, "text": text[:2000]})

    if counters["ui_answers"] >= MAX_UI:
        entry["decision"] = "cancelled:cap"
        reply = {"type": "extension_ui_response", "id": req["id"], "cancelled": True}
    elif method == "confirm":
        coverage = [name for name, rx in REQUIRED if re.search(rx, text, re.I)]
        entry["coverage"] = coverage
        if len(coverage) >= 4 or not re.search(r"goal|objective|contract|criteria|plan", text, re.I):
            entry["decision"] = "confirmed:true"
            reply = {"type": "extension_ui_response", "id": req["id"], "confirmed": True}
        else:
            counters["ui_deviations"] += 1
            entry["decision"] = "confirmed:true_with_recorded_deviation"
            entry["deviation"] = f"proposal covered only {len(coverage)}/{len(REQUIRED)} requirement groups"
            reply = {"type": "extension_ui_response", "id": req["id"], "confirmed": True}
    elif method == "select":
        options = [str(o) for o in req.get("options") or []]
        pick = None
        for o in options:
            if REJECT_WORDS.search(o):
                continue
            if re.search(r"audit", o, re.I) and APPROVE_WORDS.search(o):
                pick = o
                break
        if pick is None:
            for o in options:
                if APPROVE_WORDS.search(o) and not REJECT_WORDS.search(o):
                    pick = o
                    break
        if pick is None:
            pick = next((o for o in options if not REJECT_WORDS.search(o)), options[0] if options else None)
        entry["decision"] = f"select:{pick}"
        reply = {"type": "extension_ui_response", "id": req["id"], "value": pick}
    elif method in ("input", "editor"):
        entry["decision"] = "clarify"
        reply = {"type": "extension_ui_response", "id": req["id"], "value": CLARIFY}
    else:
        entry["decision"] = "ignored"
        if method in ("setWidget", "setStatus", "notify", "setTitle"):
            blob = "\n".join(str(x) for x in (req.get("widgetLines") or [])) or str(req.get("statusText") or req.get("message") or req.get("title") or "")
            if blob:
                status_log.append({"t": round(MONO() - T0, 3), "source": method, "text": blob[-4000:]})
                check_status_text(blob, method)
        ui_log.append(entry)
        UI_SCRIPT.write_text(json.dumps(ui_log, indent=1))
        return
    counters["ui_answers"] += 1
    if method == "confirm" and reply.get("confirmed") and "goal_confirmed" not in milestones:
        mark("goal_confirmed", {"method": method, "via": "extension_ui_confirm"})
    if method in ("select", "input", "editor") and "goal_confirmed" not in milestones \
            and re.search(r"goal|objective|contract|plan", text, re.I):
        mark("goal_confirmed", {"method": method, "via": f"extension_ui_{method}"})
    ui_log.append(entry)
    UI_SCRIPT.write_text(json.dumps(ui_log, indent=1))
    if "first_ui_answer" not in milestones:
        mark("first_ui_answer", {"method": method})
    append(EVENTS, {"dir": "harness", **now(), "kind": "ui_answer", "request": req.get("id"),
                    "method": method, "decision": entry["decision"]})
    send(reply)


def status_text_records():
    return [s for s in status_log[-6:]]


terminal_evidence = []


def check_status_text(blob, source):
    """A completion signal is only a candidate: the loop requires it to be
    stable and requires audit evidence before treating it as terminal."""
    global terminal_evidence
    if DONE_WORDS.search(blob):
        terminal_evidence.append({"t": round(MONO() - T0, 3), "source": source, "text": blob[-1500:]})
        if "first_status_complete" not in milestones:
            mark("first_status_complete", {"source": source, "text": blob[-1500:]})


STATE_ROOTS = [WORK / ".pi-glla", WORK / ".pi" / "goals", WORK / ".pi" / "goal-x"]
state_seen = {}


def poll_state_files():
    """Read the extensions' own persisted state, read-only, as external evidence.

    This is instrumentation, not interaction: it never writes to the worker's
    tree and cannot change either extension's behaviour.
    """
    for root in STATE_ROOTS:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.stat().st_size > 512_000:
                continue
            if path.suffix not in (".json", ".jsonl", ".md", ".state", ".txt"):
                continue
            try:
                text = path.read_text(errors="replace")[-8000:]
            except OSError:
                continue
            key = str(path)
            if state_seen.get(key) == text:
                continue
            state_seen[key] = text
            statuses = re.findall(r'"(?:status|state|phase|outcome)"\s*:\s*"([^"]{1,60})"', text)
            append(SAMPLES, {"t": round(MONO() - T0, 3), "kind": "state", "path": key,
                             "statuses": statuses[-8:], "tail": text[-1200:]})
            check_status_text(text, f"state:{path.name}")


# ------------------------------------------------------------------ monitors
git_state = {"first_change": None, "changed_files": []}
stop = threading.Event()
outstanding = {}


def poll_git():
    try:
        out = subprocess.run(["git", "-C", str(WORK), "status", "--porcelain=v1", "-uall"],
                             capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return
    meaningful = []
    for line in out.splitlines():
        path = line[3:].strip()
        if not path:
            continue
        if path.startswith((".pi/", ".pi-glla/", "results/", ".git/")) or "/results/" in path:
            continue
        meaningful.append(line)
    if meaningful:
        if not git_state["first_change"]:
            git_state["first_change"] = now()
            mark("first_code_modification", {"files": meaningful[:10]})
        git_state["changed_files"] = meaningful


def tree_snapshot():
    try:
        out = subprocess.run(["ps", "-eo", "pid,ppid,rss,time,comm,args", "--no-headers"],
                             capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return {"children": [], "rss_kb": None}
    kids = []
    for line in out.splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        pid, ppid, rss, ctime, comm, args = parts
        if ppid == str(proc.pid) or "auditor" in args or "goal-worker" in args:
            kids.append({"pid": pid, "rss_kb": int(rss), "cpu": ctime, "args": args[:300]})
    total = 0
    try:
        with open(f"/proc/{proc.pid}/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    total = int(line.split()[1])
    except OSError:
        pass
    return {"children": kids, "rss_kb": total}


def poll_relay():
    """Read the relay's request log (read-only mount) for model/audit activity."""
    global relay_pos, last_activity, last_substantive
    try:
        data = RELAY_LOG.read_text()
    except OSError:
        return
    lines = data.splitlines()
    for line in lines[relay_pos:]:
        relay_pos += 1
        try:
            rec = json.loads(line)
        except Exception:
            continue
        append(EVENTS, {"dir": "relay", **now(), "record": rec})
        last_activity = MONO()
        if rec.get("audit"):
            key = rec.get("id")
            if key not in audit_seen:
                audit_seen.add(key)
                counters["audit_requests"] += 1
                if counters["audit_requests"] == 1:
                    mark("first_audit_request", {"id": key})
                last_substantive = MONO()
                append(EVENTS, {"dir": "harness", **now(), "kind": "audit_request", "id": key})
            if rec.get("status") not in (None, 200) or rec.get("error"):
                counters["audit_failures"] += 1
                append(EVENTS, {"dir": "harness", **now(), "kind": "audit_failure", "id": key,
                                "status": rec.get("status"), "error": rec.get("error")})
        if rec.get("duration") is not None:
            counters["audit_completions"] += 1 if rec.get("audit") else 0


# --------------------------------------------------------------- main event loop
prompt_id = "prompt-1"
clar_rounds = 0
last_assistant_text = ""
last_settle_at = None
nudges = 0
resubmits = 0
prompt = CFG["goal_prefix"] + CFG["task"]
mark("goal_submitted", {"prompt_sha256": CFG.get("task_sha256"), "chars": len(prompt)})
send({"id": prompt_id, "type": "prompt", "message": prompt})

last_poll = 0.0
status_polled_at = 0.0
hard_deadline = MONO() + LIMIT_S
current_run_started = MONO()
goal_terminal_seen = 0
exit_reason = None
turn_open = False

while True:
    if MONO() > hard_deadline:
        exit_reason = "wall_clock_limit"
        break
    tok = milestones.get("tokens") or {}
    if (tok.get("input", 0) + tok.get("output", 0)) > 4_000_000:
        exit_reason = "token_budget_exceeded"
        break
    if proc.poll() is not None:
        exit_reason = "pi_exited"
        break

    got, record = next_record(0.5)
    if not got:
        record = None
    elif record is None:
        if proc.poll() is not None:
            exit_reason = "pi_exited"
            break
        time.sleep(0.05)
        continue
    if record is not None:
        append(EVENTS, {"dir": "pi", **now(), "record": record})
    rtype = (record or {}).get("type")

    if record is None:
        pass
    elif rtype == "response":
        rid = record.get("id")
        if rid:
            responses[rid] = record
            ev = response_waiters.pop(rid, None)
            if ev:
                ev.set()
        if record.get("command") == "prompt" and record.get("success") and not turn_open:
            turn_open = True
            current_run_started = MONO()
            mark("run_started")

    elif rtype == "extension_ui_request":
        handle_ui(record)

    elif rtype == "message_end":
        msg = record.get("message") or {}
        role = msg.get("role")
        usage = record.get("usage") or {}
        if usage:
            milestones["tokens"] = milestones.get("tokens", {"input": 0, "output": 0, "cacheRead": 0, "cost": 0})
            for k in ("input", "output", "cacheRead"):
                milestones["tokens"][k] = milestones["tokens"].get(k, 0) + int(usage.get(k) or 0)
            cost = (usage.get("cost") or {}).get("total") or 0
            milestones["tokens"]["cost"] = round(milestones["tokens"].get("cost", 0) + cost, 6)
        if role == "assistant":
            counters["turns"] += 1
            text = "".join(c.get("text", "") for c in (msg.get("content") or []) if isinstance(c, dict))
            if text:
                last_assistant_text = text
                last_substantive = MONO()
                if CLAIM_WORDS.search(text) and git_state["first_change"]:
                    counters["completion_claims"] += 1
                    claims.append({"t": round(MONO() - T0, 3), "text": text[-800:]})
                    if "first_completion_claim" not in milestones:
                        mark("first_completion_claim", {"excerpt": text[-800:]})
                if DONE_WORDS.search(text) and "first_done_language" not in milestones:
                    mark("first_done_language", {"excerpt": text[-500:]})

    elif rtype == "tool_execution_start":
        counters["tool_calls"] += 1
        name = record.get("toolName")
        args = record.get("args") or {}
        blob = json.dumps(args)[:4000]
        if name == "bash" and TEST_CMD.search(str(args.get("command", ""))):
            counters["test_runs"] += 1
            if "first_test_run" not in milestones:
                mark("first_test_run", {"command": str(args.get("command"))[:400]})
            outstanding[record.get("toolCallId")] = ("test", MONO())
        last_substantive = MONO()

    elif rtype == "tool_execution_end":
        tid = record.get("toolCallId")
        kind = outstanding.pop(tid, (None, None))
        if kind[0] == "test" and not record.get("isError"):
            counters["test_runs_ok"] += 1
            if "first_successful_test_run" not in milestones:
                mark("first_successful_test_run", {"durationMs": record.get("durationMs")})
        last_substantive = MONO()

    elif rtype == "agent_end":
        counters.setdefault("agent_end_events", 0)
        counters["agent_end_events"] += 1

    elif rtype == "agent_settled":
        turn_open = False
        last_settle_at = MONO()
        mark("agent_settled")
        milestones["settled_count"] = milestones.get("settled_count", 0) + 1

    elif rtype == "compaction_start":
        counters["compactions"] += 1

    elif rtype in ("auto_retry_start", "summarization_retry_scheduled"):
        counters["retries"] += 1

    # periodic housekeeping, at most every 2s of loop time
    if MONO() - last_poll >= 2.0:
        last_poll = MONO()
        poll_git()
        poll_relay()
        poll_state_files()

    # Interview handling: both extensions conduct a guided goal dialogue. When
    # the session settles before the goal is confirmed, answer the agent's
    # questions with the same scripted clarification a user would send. This is
    # identical for both competitors and every exchange is recorded.
    if (not turn_open and last_settle_at and "goal_confirmed" not in milestones
            and resubmits < 2 and MONO() - last_settle_at > 5.0
            and re.search(r"interrupted|session replacement|re-run the drafting|discarded", last_assistant_text or "", re.I)):
        resubmits += 1
        counters["draft_resubmits"] = resubmits
        mark(f"draft_resubmit_{resubmits}", {"excerpt": (last_assistant_text or "")[-300:]})
        send({"id": f"resubmit-{resubmits}", "type": "prompt", "message": prompt})
        last_settle_at = MONO() + 10**6

    if (not turn_open and last_settle_at and MONO() - last_settle_at > 3.0
            and MONO() - last_settle_at < 600 and "goal_confirmed" not in milestones
            ):
        idle_after_settle = MONO() - last_settle_at
        if clar_rounds < 4 and re.search(r"[?]", last_assistant_text or "") and idle_after_settle > 4.0:
            clar_rounds += 1
            milestones.setdefault("clarification_rounds", 0)
            milestones["clarification_rounds"] = clar_rounds
            mark(f"clarification_round_{clar_rounds}", {"idle_after_settle": round(idle_after_settle, 1)})
            send({"id": f"clar-{clar_rounds}", "type": "prompt", "message": CLARIFY})
            last_settle_at = MONO() + 10**6  # do not re-nudge for the same settle
        elif nudges < 2 and idle_after_settle > 90.0:
            nudges += 1
            counters["manual_interventions"] = counters.get("manual_interventions", 0) + 1
            mark(f"proceed_nudge_{nudges}", {"idle_after_settle": round(idle_after_settle, 1)})
            send({"id": f"nudge-{nudges}", "type": "prompt",
                  "message": "Confirm the goal as proposed and begin implementation now."})
            last_settle_at = MONO() + 10**6

    # Terminal settlement: a completion signal in the extension's own state or
    # dashboard that stays true for two consecutive housekeeping ticks, and the
    # run has been idle for a while, ends the trial. Otherwise the wall clock
    # limit does.
    if terminal_evidence and MONO() - last_substantive > 25.0:
        recent = [e for e in terminal_evidence if MONO() - T0 - e["t"] < 120]
        if recent:
            goal_terminal_seen += 1
            if goal_terminal_seen >= 2:
                exit_reason = "extension_state_terminal"
                break

    # status polling: only while idle, read-only command, identical cadence
    if (STATUS_POLL_S > 0 and not turn_open and MONO() - last_poll >= 2.0
            and MONO() - status_polled_at >= STATUS_POLL_S and counters["status_polls"] < 120):
        status_polled_at = MONO()
        counters["status_polls"] += 1
        send({"id": f"status-{counters['status_polls']}", "type": "prompt", "message": CFG["status_command"]})
        append(EVENTS, {"dir": "harness", **now(), "kind": "status_poll"})
        time.sleep(1.0)

        # Drain any status output that arrived during the poll.
        deadline = MONO() + 5
        polled = []
        while MONO() < deadline:
            if proc.poll() is not None:
                break
            got2, rec = next_record(0.2)
            if got2 and rec is not None:
                append(EVENTS, {"dir": "pi", **now(), "record": rec})
                if rec.get("type") == "extension_ui_request":
                    handle_ui(rec)
                elif rec.get("type") == "message_end":
                    text = "".join(c.get("text", "") for c in ((rec.get("message") or {}).get("content") or [])
                                   if isinstance(c, dict))
                    if text:
                        polled.append(text)
                elif rec.get("type") == "response" and rec.get("id", "").startswith("status-"):
                    pass
        blob = "\n".join(polled)[-4000:]
        if blob:
            status_log.append({"t": round(MONO() - T0, 3), "text": blob})
            if DONE_WORDS.search(blob):
                if "first_status_complete" not in milestones:
                    mark("first_status_complete", {"text": blob[-1500:]})
                goal_terminal_seen += 1
            else:
                goal_terminal_seen = 0
            if goal_terminal_seen >= 2:
                exit_reason = "extension_state_terminal"
                break

        # sample the process tree, relay position, and activity
        snap = tree_snapshot()
        append(SAMPLES, {"t": round(MONO() - T0, 3), "rss_kb": snap["rss_kb"], "children": snap["children"],
                         "idle_s": round(MONO() - last_substantive, 1)})
        if snap["children"] and "first_auditor_child" not in milestones:
            mark("first_auditor_child", {"children": snap["children"][:3]})

# ------------------------------------------------------------------- shutdown
mark("run_stopped", {"reason": exit_reason})
try:
    send({"id": "final-stats", "type": "get_session_stats"})
    time.sleep(0.5)
    send({"id": "final-state", "type": "get_state"})
    time.sleep(0.5)
except Exception:
    pass
try:
    proc.stdin.close()
except Exception:
    pass
try:
    proc.wait(timeout=15)
except subprocess.TimeoutExpired:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

poll_git()
poll_relay()
snap = tree_snapshot()

final = {
    "name": NAME,
    "extension": CFG["extension"],
    "trial": CFG.get("trial", "s0"),
    "exit_reason": exit_reason,
    "duration_seconds": round(MONO() - T0, 3),
    "pi_exit_code": proc.returncode,
    "milestones": milestones,
    "counters": counters,
    "claims": claims,
    "status_log": status_log,
    "git": git_state,
    "last_rss_kb": snap["rss_kb"],
    "surviving_children": snap["children"],
    "task_sha256": CFG.get("task_sha256"),
    "prompt_sha256": __import__("hashlib").sha256(prompt.encode()).hexdigest(),
    "finished_wall": time.time(),
}
MILESTONES.write_text(json.dumps(milestones, indent=1))
FINAL.write_text(json.dumps(final, indent=1))
append(EVENTS, {"dir": "harness", **now(), "kind": "final", "final": final})
print(json.dumps({"exit_reason": exit_reason, "duration": final["duration_seconds"]}))
