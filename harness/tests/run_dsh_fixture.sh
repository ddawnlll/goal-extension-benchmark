#!/bin/bash
# Deterministic lifecycle smoke using the actual pinned DSH packages, not an LLM benchmark.
set -euo pipefail
MODE="${1:?mode: complete, blocked or cap}"
TRIAL="${2:?fresh trial id}"
PORT="${3:-19991}"
case "$MODE" in
  complete) CAP=4; EXPECT=goal_complete; ROUNDS=2 ;;
  blocked) CAP=5; EXPECT=goal_blocked; ROUNDS=3 ;;
  cap) CAP=2; EXPECT=goal_blocked; ROUNDS=2 ;;
  *) echo "unknown mode: $MODE" >&2; exit 2 ;;
esac
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
KEY="$(mktemp)"
printf 'dummy-fixture-key' > "$KEY"
python3 harness/tests/fake_openai.py --port "$PORT" --mode "$MODE" &
SERVER=$!
trap 'kill "$SERVER" 2>/dev/null || true; rm -f "$KEY"' EXIT
export BENCH_RELAY_UPSTREAM_KEY_FILE="$KEY" UPSTREAM_SCHEME=http
export UPSTREAM_HOST=host.docker.internal UPSTREAM_PORT="$PORT" UPSTREAM_PREFIX= UPSTREAM_MODELS_PATH=
export DSH_GOAL_MAX_ROUNDS="$CAP"
python3 harness/run_trial.py --trial "$TRIAL" --order dsh --smoke --max-seconds 45
python3 - "$TRIAL" "$EXPECT" "$ROUNDS" "$MODE" <<'PY'
import json, pathlib, sys
trial, expected, rounds, mode = sys.argv[1:]
state = json.loads(pathlib.Path(f'results/dsh-{trial}-final-state.json').read_text())
meta = json.loads(pathlib.Path(f'results/dsh-{trial}-runmeta.json').read_text())
expected_invalid = [] if mode == 'complete' else ['container_exit_1']
assert meta['invalid_reasons'] == expected_invalid, meta
assert state['exit_reason'] == expected, state
assert state['native_goal']['roundsStarted'] == int(rounds), state
if mode == 'cap':
    assert state['native_goal']['blockedReason']['code'] == 'round-limit'
elif mode == 'blocked':
    assert state['native_goal']['blockedReason']['code'] == 'model-reported'
print('verified native lifecycle:', expected, 'rounds:', rounds)
PY
