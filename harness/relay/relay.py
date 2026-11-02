#!/usr/bin/env python3
"""Benchmark model relay.

Sits between one isolated worker container and the operator's local model
server. It does three things the benchmark needs and nothing else:

  1. Injects the real upstream credential, so no worker container ever holds it.
  2. Logs one JSONL record per upstream request (timing, model, size, audit
     markers, status) for instrumentation and latency measurements.
  3. Supports controlled fault injection for the recovery scenarios, driven by
     control.json (slow, fail, abort), confined to the relay boundary. No
     competitor source code is modified.

The relay forwards only to the configured upstream; it is not a general proxy.
"""
import http.client
import json
import os
import re
import sys
import queue
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

UPSTREAM_HOST = os.environ.get("UPSTREAM_HOST", "host.lima.internal")
UPSTREAM_PORT = int(os.environ.get("UPSTREAM_PORT", "9091"))
UPSTREAM_SCHEME = os.environ.get("UPSTREAM_SCHEME", "http")
UPSTREAM_PREFIX = os.environ.get("UPSTREAM_PREFIX", "").rstrip("/")
UPSTREAM_MODELS_PATH = os.environ.get("UPSTREAM_MODELS_PATH", "")
UPSTREAM_SESSION = os.environ.get("UPSTREAM_SESSION", "")
if UPSTREAM_SCHEME not in ("http", "https"):
    raise ValueError("UPSTREAM_SCHEME must be http or https")
UPSTREAM_KEY = os.environ["LOCAL_LLM_KEY"]
LOG = Path(os.environ.get("RELAY_LOG", "/logs/relay.jsonl"))
CONTROL = Path(os.environ.get("RELAY_CONTROL", "/logs/control.json"))
ALLOWED_PREFIXES = ("/v1/chat/completions", "/v1/responses", "/v1/messages", "/v1/models", "/v1/props")

# Prompt markers that identify an independent completion-audit request from
# either extension. Deliberately broad, and applied identically to both.
AUDIT_MARKERS = re.compile(
    rb"completion auditor|read-only completion auditor|audit(?:or)? prompt|"
    rb"You are (?:a|the) (?:read-only )?(?:completion )?auditor|goal auditor",
    re.IGNORECASE,
)

_lock = threading.Lock()
_seq = 0


def log(record):
    global _seq
    with _lock:
        _seq += 1
        record["seq"] = _seq
        try:
            with LOG.open("a") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass


def control():
    try:
        return json.loads(CONTROL.read_text())
    except Exception:
        return {"mode": "normal"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send_json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.forward(b"")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.forward(self.rfile.read(length))

    def forward(self, body):
        started = time.monotonic()
        path = self.path
        if not path.startswith(ALLOWED_PREFIXES):
            self._send_json(403, {"error": {"message": "path not allowed by benchmark relay"}})
            return

        ctrl = control()
        mode = ctrl.get("mode", "normal")
        match = ctrl.get("match")
        is_audit = bool(AUDIT_MARKERS.search(body))
        applies = mode != "normal" and (not match or (match == "audit") == is_audit)
        req_id = str(uuid.uuid4())[:8]
        body_sha = __import__("hashlib").sha256(body).hexdigest()[:16] if body else None
        rec = {
            "id": req_id,
            "body_sha": body_sha,
            "t_mono": started,
            "t_wall": time.time(),
            "path": path,
            "bytes": len(body),
            "audit": is_audit,
            "model": None,
            "mode": mode if applies else "normal",
        }
        if body:
            try:
                parsed = json.loads(body)
                rec["model"] = parsed.get("model")
                rec["stream"] = bool(parsed.get("stream"))
                rec["messages"] = len(parsed.get("messages") or [])
                rec["tools"] = len(parsed.get("tools") or [])
                rec["max_tokens"] = parsed.get("max_tokens")
                rec["reasoning_effort"] = parsed.get("reasoning_effort")
                sha256 = __import__("hashlib").sha256
                systems = [m for m in parsed.get("messages", []) if m.get("role") in ("system", "developer")]
                rec["system_messages"] = len(systems)
                rec["system_sha256"] = sha256(json.dumps(systems, sort_keys=True).encode()).hexdigest()
                rec["tools_sha256"] = sha256(json.dumps(parsed.get("tools", []), sort_keys=True).encode()).hexdigest()
            except Exception:
                pass

        if body:
            try:
                parsed = json.loads(body)
                rec["keys"] = sorted(parsed.keys())
                rec["request_shape"] = {
                    k: parsed[k] for k in ("max_tokens", "max_completion_tokens", "temperature",
                                           "top_p", "parallel_tool_calls", "store")
                    if isinstance(parsed.get(k), (int, float, bool))
                }
                if isinstance(parsed.get("stream_options"), dict):
                    rec["request_shape"]["include_usage"] = parsed["stream_options"].get("include_usage") is True
                if isinstance(parsed.get("response_format"), dict):
                    kind = parsed["response_format"].get("type")
                    if kind in ("text", "json_object", "json_schema"):
                        rec["request_shape"]["response_format_type"] = kind
                if parsed.get("tool_choice") in ("auto", "none", "required"):
                    rec["request_shape"]["tool_choice"] = parsed["tool_choice"]
            except Exception:
                pass
        if applies and mode == "slow":
            time.sleep(float(ctrl.get("delay_ms", 30000)) / 1000.0)
        if applies and mode == "fail":
            # Transient provider error, the shape an upstream 5xx/overload takes.
            rec["status"] = 503
            rec["duration"] = time.monotonic() - started
            log(rec)
            self._send_json(503, {"error": {"message": "benchmark injected transient 503", "type": "server_error"}})
            return
        if applies and mode == "abort":
            rec["status"] = -1
            rec["duration"] = time.monotonic() - started
            log(rec)
            try:
                self.close_connection = True
                self.connection.close()
            except OSError:
                pass
            return

        headers = {
            "Content-Type": self.headers.get("Content-Type", "application/json"),
            "Authorization": f"Bearer {UPSTREAM_KEY}",
            "Accept": self.headers.get("Accept", "*/*"),

        }
        if UPSTREAM_SESSION:
            headers["x-opencode-session"] = UPSTREAM_SESSION
        # Upstream flakiness is environment noise, not a competitor behaviour.
        # Retry once before any byte has been forwarded downstream, and record it.
        resp = None
        for attempt in (1, 2):
            connection = http.client.HTTPSConnection if UPSTREAM_SCHEME == "https" else http.client.HTTPConnection
            conn = connection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=600)
            try:
                upstream_path = UPSTREAM_MODELS_PATH if path == "/v1/models" and UPSTREAM_MODELS_PATH else UPSTREAM_PREFIX + path
                conn.request(self.command, upstream_path, body=body or None, headers=headers)
                resp = conn.getresponse()
                if attempt == 2:
                    rec["upstream_retry"] = True
                break
            except (ConnectionResetError, http.client.HTTPException, OSError):
                rec["upstream_retries"] = rec.get("upstream_retries", 0) + 1
                try:
                    conn.close()
                except Exception:
                    pass
                if attempt == 2:
                    raise
                time.sleep(1.0)
        phase = "response_headers"
        try:
            rec["status"] = resp.status
            ctype = resp.getheader("Content-Type", "application/json")
            self.send_response(resp.status)
            self.send_header("Content-Type", ctype)
            # Refuse to buffer: streaming responses go out as they arrive.
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            phase = "stream"
            usage = None
            pending = b""
            forwarded = 0
            completed = False
            if "text/event-stream" in ctype:
                # Drain upstream continuously on a reader thread so a slow
                # downstream consumer can never apply backpressure to the
                # upstream connection (the local proxy resets a stream whose
                # consumer stalls). Order is preserved; memory is bounded.
                chunks = queue.Queue(maxsize=2048)
                reader_error = []

                def drain():
                    try:
                        while True:
                            c = resp.read1(65536)
                            if not c:
                                break
                            chunks.put(c)
                    except Exception as exc:  # surfaced on the consumer side
                        reader_error.append(exc)
                    finally:
                        chunks.put(None)

                threading.Thread(target=drain, daemon=True).start()
                while True:
                    try:
                        chunk = chunks.get(timeout=900)
                    except queue.Empty:
                        raise TimeoutError("upstream stream produced nothing for 900s")
                    if chunk is None:
                        if reader_error and not completed:
                            raise reader_error[0]
                        break
                    phase = "stream_write"
                    try:
                        self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        rec["client_abort"] = True
                        rec["phase"] = "stream_write"
                        rec["forwarded_bytes"] = forwarded
                        rec["duration"] = time.monotonic() - started
                        log(rec)
                        return
                    phase = "stream_read"
                    forwarded += len(chunk)
                    pending += chunk
                    lines = pending.split(b"\n")
                    pending = lines.pop()[-65536:]
                    for line in lines:
                        if line.startswith(b"data: ") and b'"usage"' in line:
                            try:
                                u = json.loads(line[6:]).get("usage")
                                if isinstance(u, dict):
                                    usage = u
                            except (ValueError, AttributeError):
                                pass
                    if b'[DONE]' in chunk or b'"finish_reason":"stop"' in chunk or b'"finish_reason":"tool_calls"' in chunk:
                        completed = True
            else:
                phase = "read_body"
                data = resp.read()
                phase = "body_write"
                self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
                if b'"usage"' in data:
                    try:
                        usage = json.loads(data).get("usage")
                    except (ValueError, AttributeError):
                        pass
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            rec["duration"] = time.monotonic() - started
            rec["forwarded_bytes"] = forwarded
            if isinstance(usage, dict):
                rec["usage"] = {k: usage[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens") if isinstance(usage.get(k), (int, float))}
                for group, field in (("prompt_tokens_details", "cached_tokens"), ("completion_tokens_details", "reasoning_tokens")):
                    details = usage.get(group)
                    if isinstance(details, dict) and isinstance(details.get(field), (int, float)):
                        rec["usage"][group] = {field: details[field]}
            log(rec)
        except Exception as exc:  # upstream/protocol failure: surface it, log it
            rec["status"] = -2
            rec["phase"] = phase
            try:
                with (LOG.parent / "failed-requests.jsonl").open("a") as fh:
                    fh.write(json.dumps({"seq": rec["seq"], "request_shape": rec.get("request_shape"),
                                         "keys": rec.get("keys"), "error": rec.get("error"),
                                         "phase": phase, "audit": is_audit,
                                         "bytes": len(body), "body_sha": body_sha}) + "\n")
            except OSError:
                pass
            rec["error"] = f"{type(exc).__name__}: {exc}"
            rec["duration"] = time.monotonic() - started
            log(rec)
            try:
                self._send_json(502, {"error": {"message": f"benchmark relay upstream error: {type(exc).__name__}"}})
            except OSError:
                pass
        finally:
            try:
                conn.close()
            except Exception:
                pass


def main():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", 9091), Handler)
    server.daemon_threads = True
    print(f"relay listening on 0.0.0.0:9091 -> {UPSTREAM_HOST}:{UPSTREAM_PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    sys.exit(main())
