#!/usr/bin/env python3
"""Preflight: prove the model relay is stable from both isolated workers.

Runs, per competitor, on that competitor's own internal network with its own
relay container (the exact topology used for timing):

  * 4 small non-streaming requests (connectivity + auth)
  * 4 streaming requests with a realistic tool schema and reasoning effort
  * 4 longer streaming requests

Records every latency and error. Exits non-zero if any request fails, because a
trial timed on an unstable relay is not a valid speed measurement.
"""
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = dict(os.environ, DOCKER_HOST=os.environ.get(
    "DOCKER_HOST", f"unix://{Path.home()}/.colima/default/docker.sock"))
IMAGE = "goalbench/base:1"
OUT = ROOT / "results" / "replication-preflight.json"
N = 4


def sh(cmd, **kw):
    return subprocess.run(cmd, text=True, capture_output=True, env=ENV, **kw)


def docker(*a, **kw):
    return sh(["docker", *a], **kw)


PREFLIGHT_PY = r'''
import json, time, urllib.request, sys, statistics
base, key = sys.argv[1], sys.argv[2]
tools = [{"type":"function","function":{"name":f"tool_{i}",
          "description":"A tool for inspecting a source tree. "*8,
          "parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}}
         for i in range(24)]
shapes = [
  ("small",   {"max_tokens": 24, "stream": False,
               "messages":[{"role":"user","content":"Reply with exactly: PREFLIGHT_OK"}]}),
  ("tools",   {"max_tokens": 200, "stream": True, "tools": tools, "reasoning_effort": "low",
               "messages":[{"role":"system","content":"You are a coding agent. "*120},
                           {"role":"user","content":"Call tool_3 with path=/tmp/x, then stop."}]}),
  ("long",    {"max_tokens": 700, "stream": True, "reasoning_effort": "low",
               "messages":[{"role":"user","content":"Write a 400-word explanation of XML escaping in SVG."}]}),
]
out = []
for i in range(4):
    for shape, extra in shapes:
        body = {"model": "deepseek-v4.1-flash", **extra}
        raw = json.dumps(body).encode()
        req = urllib.request.Request(base + "/chat/completions", data=raw,
                                     headers={"Content-Type": "application/json",
                                              "Authorization": "Bearer " + key})
        t0 = time.monotonic()
        rec = {"i": i, "shape": shape, "bytes": len(raw)}
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = r.read()
                rec["status"] = r.status
                rec["bytes_out"] = len(data)
                rec["ok"] = r.status == 200
        except Exception as exc:
            rec["ok"] = False
            rec["error"] = f"{type(exc).__name__}: {exc}"
        rec["latency_s"] = round(time.monotonic() - t0, 3)
        out.append(rec)
        print(json.dumps(rec), flush=True)
print("SUMMARY " + json.dumps({
    "n": len(out),
    "ok": sum(1 for r in out if r.get("ok")),
    "failed": sum(1 for r in out if not r.get("ok")),
    "median_latency_s": round(statistics.median(r["latency_s"] for r in out), 3),
    "max_latency_s": round(max(r["latency_s"] for r in out), 3),
}))
'''


def main():
    key = (ROOT / "harness" / ".secrets" / "local_api_key").read_text().strip()
    script = ROOT / "harness" / ".tmp" / "preflight_infer.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(PREFLIGHT_PY)
    report = {"started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "competitors": {}}
    ok_all = True
    for name in ("glla", "goal-x"):
        net, relay, relay_vol = f"gbnet-{name}", f"gb-relay-{name}", f"gb-{name}-relay"
        for c in (f"gb-worker-{name}", f"gb-verify-{name}", relay):
            docker("rm", "-f", c)
        docker("network", "rm", net)
        docker("network", "create", "--internal", net)
        docker("volume", "rm", "-f", relay_vol)
        docker("volume", "create", relay_vol)
        docker("run", "-d", "--name", relay, "--restart", "no", "--network", net,
               "--add-host", "host.lima.internal:host-gateway",
               "-e", "LOCAL_LLM_KEY=" + key, "-e", "RELAY_LOG=/logs/relay.jsonl",
               "-e", "RELAY_CONTROL=/logs/control.json", "-v", f"{relay_vol}:/logs",
               "goalbench/relay:1")
        docker("network", "connect", "bridge", relay)
        docker("run", "--rm", "--entrypoint", "/bin/sh", "-v", f"{relay_vol}:/logs",
               "goalbench/relay:1", "-c",
               "test -f /logs/relay.jsonl || : > /logs/relay.jsonl; "
               "echo '{\"mode\":\"normal\"}' > /logs/control.json; chmod 666 /logs/*")
        for _ in range(60):
            if docker("exec", relay, "python3", "-c",
                      "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:9091/v1/models',timeout=3).status)",
                      check=False).returncode == 0:
                break
            time.sleep(1)
        out = docker("run", "--rm", "--network", net,
                     "-v", f"{script}:/preflight.py:ro",
                     IMAGE, "python3", "/preflight.py",
                     f"http://{relay}:9091/v1", "benchmark-local-relay")
        lines = (out.stdout or "").splitlines()
        summary = next((json.loads(l[len("SUMMARY "):]) for l in lines if l.startswith("SUMMARY ")), {})
        records = [json.loads(l) for l in lines if l.startswith("{")]
        relay_log = docker("run", "--rm", "--entrypoint", "/bin/sh", "-v", f"{relay_vol}:/logs",
                           "goalbench/relay:1", "-c", "cat /logs/relay.jsonl")
        reqs = [json.loads(l) for l in (relay_log.stdout or "").splitlines() if l.strip()]
        relay_fail = sum(1 for r in reqs if r.get("status") not in (200, None))
        efforts = sorted({r.get("reasoning_effort") for r in reqs if r.get("reasoning_effort")})
        report["competitors"][name] = {
            "summary": summary, "records": records,
            "relay_requests": len(reqs), "relay_failures": relay_fail,
            "reasoning_effort_seen": efforts,
        }
        ok = summary.get("failed", 1) == 0 and relay_fail == 0
        ok_all = ok_all and ok
        print(f"{name}: {summary} relay_failures={relay_fail} efforts={efforts} -> {'STABLE' if ok else 'UNSTABLE'}")
        docker("stop", relay)
    report["stable"] = ok_all
    report["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    OUT.write_text(json.dumps(report, indent=1))
    print("PREFLIGHT", "STABLE" if ok_all else "UNSTABLE", "->", OUT)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
