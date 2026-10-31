#!/usr/bin/env python3
"""Orchestrates one paired benchmark trial on the host.

For each competitor it:
  * recreates the instance volume from the pinned baseline,
  * starts an isolated internal Docker network with a logging model relay,
  * starts the worker container (read-only rootfs, non-root, cpu/mem capped,
    no route except the relay, only its own volume mounted),
  * runs the in-container runner, which drives Pi-Bolt over RPC,
  * independently re-verifies the workspace through a separate read-only
    verifier container, sampling every 30s,
  * on exit, collects logs, timings, process evidence and the diff.

No original Pi/Pi-Bolt installation, session or repository is touched.

Usage: run_trial.py --trial s0 --order glla,goal-x [--max-seconds 3600]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCKER = ["docker"]
ENV = dict(os.environ, DOCKER_HOST=os.environ.get(
    "DOCKER_HOST", f"unix://{Path.home()}/.colima/default/docker.sock"))
RUNTIME = Path(os.environ.get("PI_BOLT_RUNTIME", ROOT / "harness" / "runtime" / "current")).resolve()
IMAGE = "goalbench/base:1"
EVAL_IMAGE = "goalbench/eval:1"
SECRETS = ROOT / "harness" / ".secrets"
RESULTS = ROOT / "results"
TASK = ROOT / "results" / "shared-task.md"

EXT = {
    "glla": {"src": ROOT / "competitors" / "_glla-src", "goal_prefix": "/goal plan ", "status": "/goal status"},
    "goal-x": {"src": ROOT / "competitors" / "_goalx-src", "goal_prefix": "/goal ", "status": "/goal-status"},
}


def sh(cmd, check=True, capture=True, timeout=None):
    return subprocess.run(cmd, check=check, text=True, env=ENV,
                          capture_output=capture, timeout=timeout)


def docker(*args, **kw):
    return sh(DOCKER + list(args), **kw)


def volume(name):
    return f"gb-{name}-home"


def sleep_lines(limit=40):
    """Recent macOS sleep/wake transitions, as stable strings for diffing."""
    out = sh(["bash", "-lc", "pmset -g log 2>/dev/null | grep -E '^[0-9-]+ [0-9:]+ \\+[0-9]+ (Sleep |Wake )' | tail -%d" % limit],
             check=False)
    return [l for l in (out.stdout or "").splitlines() if l.strip()]


def docker_ok():
    return docker("info", "--format", "{{.ServerVersion}}", check=False).returncode == 0


def ensure_instance(name, max_seconds, trial, thinking, extra_env, task_override=None):
    cfg = EXT[name]
    sh([str(ROOT / "harness" / "setup_instance.sh"), name, str(cfg["src"])])
    task = task_override or TASK.read_text()
    run_dir = ROOT / "harness" / "run-seed" / name
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "task.md").write_text(task)
    sha = __import__("hashlib").sha256(task.encode()).hexdigest()
    config = {
        "name": name,
        "extension": {"glla": "pi-goal-list-loop-audit", "goal-x": "pi-goal-x"}[name],
        "trial": trial,
        "provider": "local",
        "model": "deepseek-v4.1-flash",
        "thinking": thinking,
        "goal_prefix": cfg["goal_prefix"],
        "status_command": cfg["status"],
        "task": task,
        "task_sha256": sha,
        "max_seconds": max_seconds,
        "status_poll_seconds": 0,
        "relay_log": "/var/log/relay/relay.jsonl",
        "env": {"PI_CODING_AGENT_DIR": "/home/agent/.pi/agent", "HOME": "/home/agent",
                "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/bin/false", **extra_env},
        "extra_args": ["--no-approve"],
    }
    (run_dir / "config.json").write_text(json.dumps(config, indent=1))
    docker("run", "--rm", "-v", f"{volume(name)}:/home/agent", "-v", f"{run_dir}:/src/run:ro",
           IMAGE, "bash", "-lc",
           "mkdir -p /home/agent/run && cp /src/run/* /home/agent/run/ && cp /src/run/task.md /home/agent/task.md && chmod 555 /home/agent/task.md")
    return sha


def setup_networks(name):
    net = f"gbnet-{name}"
    relay = f"gb-relay-{name}"
    for c in (f"gb-worker-{name}", f"gb-verify-{name}", relay):
        docker("rm", "-f", c, check=False)
    docker("network", "rm", net, check=False)
    docker("network", "create", "--internal", net, check=True)
    relay_vol = f"gb-{name}-relay"
    docker("volume", "rm", "-f", relay_vol, check=False)
    docker("volume", "create", relay_vol, check=True)
    key = (SECRETS / "local_api_key").read_text().strip()
    docker("run", "-d", "--name", relay, "--restart", "no",
           "--network", net,
           "--add-host", "host.lima.internal:host-gateway",
           "-e", "LOCAL_LLM_KEY=" + key,
           "-e", "RELAY_LOG=/logs/relay.jsonl",
           "-e", "RELAY_CONTROL=/logs/control.json",
           "-v", f"{relay_vol}:/logs",
           "goalbench/relay:1")
    # The relay also needs the default bridge for the single allowed upstream.
    docker("network", "connect", "bridge", relay)
    docker("run", "--rm", "--entrypoint", "/bin/sh", "-v", f"{relay_vol}:/logs", "goalbench/relay:1", "-c",
           "test -f /logs/relay.jsonl || : > /logs/relay.jsonl; test -f /logs/control.json || echo '{\"mode\":\"normal\"}' > /logs/control.json; chmod 666 /logs/*")
    return net, relay, relay_vol


def wait_relay(name, timeout=60):
    for _ in range(timeout):
        out = docker("exec", f"gb-relay-{name}", "python3", "-c",
                     "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:9091/v1/models',timeout=3).status)",
                     check=False)
        if out.returncode == 0:
            return True
        time.sleep(1)
    return False


def start_verifier(name, relay_vol):
    cname = f"gb-verify-{name}"
    docker("rm", "-f", cname, check=False)
    docker("run", "-d", "--name", cname, "--network", "none",
           "-v", f"{volume(name)}:/candidate-src:ro",
           "-v", f"{ROOT / 'evaluation' / 'frozen'}:/eval:ro",
           "-v", f"{ROOT / 'evaluation' / 'fixtures' / 'baseline-svgs'}:/fixture/baseline-svgs:ro",
           "-v", f"{ROOT / 'baseline' / 'pi-bolt' / 'bench' / 'results' / '2026-10-10-pi-bolt-0.7.3'}:/fixture/results:ro",
           "-e", "CANDIDATE_ROOT=/candidate",
           "-e", "FIXTURE_RESULTS=/fixture/results",
           "-e", "BASELINE_SVGS=/fixture/baseline-svgs",
           EVAL_IMAGE, "sleep", "infinity")
    return cname


VERIFY_CMD = (
    "set -e; rm -rf /candidate; mkdir -p /candidate; "
    "cp -r /candidate-src/work/bench /candidate/bench; "
    "[ -d /candidate-src/work/tests ] && cp -r /candidate-src/work/tests /candidate/tests || true; "
    "[ -d /candidate-src/work/bench/tests ] && cp -r /candidate-src/work/bench/tests /candidate/bench/tests || true; "
    "cd /candidate && python3 -m unittest -q /eval/test_report_svg.py.ChartEscaping /eval/test_report_svg.py.HeroEscaping 2>&1 | tail -5"
)


def verifier_pass(cname):
    """Fast, read-only external check: do the escaping requirements hold now?"""
    cmd = (
        "cd /tmp && rm -rf c && mkdir c && "
        "cp -r /candidate-src/work/bench c/bench && "
        "CANDIDATE_ROOT=/tmp/c python3 -m pytest -q /eval/test_report_svg.py "
        "-k 'not RegressionEvidence' 2>&1"
    )
    out = docker("exec", cname, "bash", "-lc", cmd + "; echo __RC=$?", check=False)
    text = (out.stdout or "") + (out.stderr or "")
    ok = "__RC=0" in text and " failed" not in text
    summary = [l for l in text.splitlines() if " passed" in l or " failed" in l or "error" in l.lower()]
    return ok, (summary[-1] if summary else text.strip()[-300:])


def warm_session(name, net):
    """Create the session with one trivial turn before the timed window.

    Both extensions behave differently on a *blank* startup than on a loaded
    session (GLLA in particular parks a blank startup behind a load barrier).
    Starting the measured run from a loaded session is identical for both
    competitors and is recorded as harness preparation, outside the timed
    window.
    """
    out = docker("run", "--rm", "--network", net,
                 "-v", f"{volume(name)}:/home/agent",
                 "-v", f"{RUNTIME}:/opt/pi-bolt:ro",
                 "-e", "PI_CODING_AGENT_DIR=/home/agent/.pi/agent",
                 "-e", "HOME=/home/agent",
                 "-w", "/home/agent/work",
                 IMAGE, "bash", "-lc",
                 "timeout 180 pi -p --provider local --model deepseek-v4.1-flash --thinking off "
                 "--name benchmark-warmup --no-approve "
                 "'Session initialisation check. Reply with OK and nothing else.' "
                 "2>&1 | tail -3", check=False)
    return out.stdout.strip()[-400:]


def launch_worker(name, net, relay_vol, trial, max_seconds, memory="6g"):
    cname = f"gb-worker-{name}"
    docker("rm", "-f", cname, check=False)
    cmd = [
        "run", "-d", "--name", cname,
        "--network", net,
        "--init",
        "--read-only",
        "--tmpfs", "/tmp:rw,exec,size=2g",
        "--cpus", "2", "--memory", memory, "--memory-swap", memory, "--pids-limit", "512",
        "--security-opt", "no-new-privileges",
        "--cap-drop", "ALL",
        "--cap-add", "CHOWN", "--cap-add", "SETUID", "--cap-add", "SETGID",
        "--cap-add", "DAC_OVERRIDE", "--cap-add", "FOWNER",
        "-v", f"{volume(name)}:/home/agent",
        "-v", f"{RUNTIME}:/opt/pi-bolt:ro",
        "-v", f"{relay_vol}:/var/log/relay:ro",
        "-v", f"{ROOT / 'harness' / 'runner'}:/opt/runner:ro",
        "-e", "PI_CODING_AGENT_DIR=/home/agent/.pi/agent",
        "-e", "HOME=/home/agent",
        "-w", "/home/agent/work",
        IMAGE, "python3", "/opt/runner/runner.py",
    ]
    docker(*cmd)
    return cname


def worker_alive(cname):
    out = docker("inspect", "-f", "{{.State.Running}}", cname, check=False)
    return out.stdout.strip() == "true"


def run_one(name, trial, max_seconds, thinking, extra_env, task_override=None, memory="6g"):
    print(f"\n=== {name} / {trial} ===", flush=True)
    started = time.time()
    sha = ensure_instance(name, max_seconds, trial, thinking, extra_env, task_override)
    net, relay, relay_vol = setup_networks(name)
    if not wait_relay(name):
        raise SystemExit(f"relay for {name} cannot reach the model endpoint")
    warm = warm_session(name, net)
    print(f"  warm-up session: {warm.splitlines()[-1] if warm else 'no output'}", flush=True)
    verifier = start_verifier(name, relay_vol)
    cname = launch_worker(name, net, relay_vol, trial, max_seconds, memory)

    verified_at = None
    verify_log = []
    sleep_events = []
    docker_gaps = []
    baseline_sleep = set(sleep_lines())
    last_poll = time.time()
    deadline = started + max_seconds + 300
    while worker_alive(cname) and time.time() < deadline:
        time.sleep(20)
        # host sleep/wake monitoring: a sleep that overlaps the run invalidates it
        for line in sleep_lines():
            if line not in baseline_sleep:
                baseline_sleep.add(line)
                sleep_events.append({"at": round(time.time() - started, 1),
                                     "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                     "line": line[:200]})
                print(f"  !! host sleep/wake during run: {line[:120]}", flush=True)
        # docker/colima interruption monitoring
        if not docker_ok():
            docker_gaps.append({"at": round(time.time() - started, 1),
                                "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            print("  !! docker daemon unreachable", flush=True)
        # periodic external verification
        if time.time() - last_poll >= 30:
            last_poll = time.time()
            if verified_at is None:
                ok, detail = verifier_pass(verifier)
                verify_log.append({"t": round(time.time() - started, 1), "ok": ok, "detail": detail})
                if ok:
                    verified_at = round(time.time() - started, 1)
                    print(f"  externally verified at {verified_at}s", flush=True)

    end = time.time()
    insp = docker("inspect", "-f", "{{.State.OOMKilled}} {{.State.ExitCode}} {{.State.Error}}", cname, check=False).stdout.strip()
    oom_killed = insp.split()[0] == "true" if insp else None
    exit_code = insp.split()[1] if len(insp.split()) > 1 else None
    logs = docker("logs", cname, check=False).stdout
    (RESULTS / f"{name}-{trial}-container.log").write_text(logs or "")
    tmp = RESULTS / f"{name}-{trial}-final-state.json"
    docker("cp", f"{cname}:/home/agent/logs/final-state.json", str(tmp), check=False)
    final = tmp.read_text() if tmp.exists() else ""
    docker("rm", "-f", cname, check=False)
    docker("rm", "-f", verifier, check=False)

    # Relay health for this run, from the relay's own request log.
    relay_log = docker("run", "--rm", "--user", "0", "--entrypoint", "/bin/sh",
                       "-v", f"{relay_vol}:/logs", "goalbench/relay:1", "-c",
                       "cat /logs/relay.jsonl", check=False).stdout or ""
    reqs = []
    for line in relay_log.splitlines():
        try:
            reqs.append(json.loads(line))
        except Exception:
            pass
    chat = [r for r in reqs if r.get("path", "").endswith("chat/completions")]
    failed = [r for r in chat if r.get("status") not in (200, None)]
    failure_rate = (len(failed) / len(chat)) if chat else None
    final_state = {}
    try:
        final_state = json.loads((RESULTS / f"{name}-{trial}-final-state.json").read_text())
    except Exception:
        pass

    invalid = []
    if sleep_events:
        invalid.append("host_sleep_overlap")
    if docker_gaps:
        invalid.append("docker_daemon_interruption")
    if failure_rate is not None and failure_rate > 0.10:
        invalid.append(f"relay_failure_rate_{failure_rate:.0%}")
    if oom_killed:
        invalid.append("container_oom_killed")
    if final_state.get("exit_reason") in ("wall_clock_limit", "token_budget_exceeded"):
        invalid.append(f"limit_{final_state.get('exit_reason')}")

    meta = {
        "name": name, "trial": trial, "baseline_sha": sha, "warmup": warm,
        "started_wall": started, "ended_wall": end,
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
        "ended_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(end)),
        "wall_seconds": round(end - started, 1),
        "externally_verified_at_s": verified_at, "verifier_samples": verify_log,
        "sleep_events": sleep_events, "docker_gaps": docker_gaps,
        "relay": {"requests": len(chat), "failed": len(failed),
                  "failure_rate": failure_rate},
        "exit_reason": final_state.get("exit_reason"),
        "oom_killed": oom_killed, "container_exit_code": exit_code, "memory_limit": memory,
        "invalid_reasons": invalid,
        "valid": not invalid,
    }
    (RESULTS / f"{name}-{trial}-runmeta.json").write_text(json.dumps(meta, indent=1))
    # Snapshot the instance volume now: the next run recreates it in place.
    snap = sh([sys.executable, str(ROOT / "harness" / "replication.py"), "collect-one", name, trial])
    if snap.returncode != 0:
        print(f"  !! artifact collection failed for {name} {trial}: {snap.stderr[-300:]}", flush=True)
        meta["invalid_reasons"] = list(meta.get("invalid_reasons", [])) + ["artifact_collection_failed"]
        meta["valid"] = False
        (RESULTS / f"{name}-{trial}-runmeta.json").write_text(json.dumps(meta, indent=1))
    print(f"  wall {meta['wall_seconds']}s; final-state present: {bool(final)}", flush=True)
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trial", default="s0")
    ap.add_argument("--order", default="glla,goal-x")
    ap.add_argument("--max-seconds", type=float, default=3600)
    ap.add_argument("--thinking", default="low")
    ap.add_argument("--memory", default="6g")
    ap.add_argument("--only", default=None)
    ap.add_argument("--smoke", action="store_true", help="plumbing check with a trivial task")
    a = ap.parse_args()
    RESULTS.mkdir(exist_ok=True)
    meta = {"trial": a.trial, "order": a.order, "runs": []}
    for name in a.order.split(","):
        if a.only and name != a.only:
            continue
        override = ("Reply with the single word OK. Do not use any tools. Then finish the goal."
                    if a.smoke else None)
        m = run_one(name, a.trial, min(a.max_seconds, 300) if a.smoke else a.max_seconds,
                    a.thinking, {}, override, a.memory)
        meta["runs"].append(m)
    path = RESULTS / f"trial-{a.trial}-runmeta.json"
    path.write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
