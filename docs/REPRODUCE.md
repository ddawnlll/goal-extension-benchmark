# Reproduce the benchmark

Everything below runs on one machine with Docker. In the recorded runs one pair
(two sequential runs) took about 17 minutes of wall clock; both pairs plus setup
and evaluation fit in well under an hour, because GLLA dominates the wall clock.

## Requirements

- Linux or macOS on Apple silicon (the released Pi-Bolt binary used here is
  `linux-arm64`; a `linux-x64` release exists and the scripts take `PI_BOLT_RUNTIME`)
- Docker 24+ reachable through `DOCKER_HOST` (Docker Desktop, Colima, or a Linux
  daemon; the scripts default to Colima's `default` profile)
- Python 3.9+ on the host (standard library only)
- `git`, `curl`, `tar`, `xz`
- An OpenAI-compatible chat endpoint that supports tool calling, streaming and a
  reasoning-effort parameter. The runs used `deepseek-v4.1-flash` with a 1M-token
  context window at reasoning effort `low`. Any equivalent endpoint works; edit
  `harness/config/models.tmpl.json` to change model id, context window or prices.
- About 10 GB of disk: the Pi-Bolt release (~250 MB) plus per-run volumes.

## 1. Fetch the pinned inputs

```bash
git clone https://github.com/ddawnlll/goal-extension-benchmark
cd goal-extension-benchmark
bash harness/fetch_inputs.sh
```

`fetch_inputs.sh` clones Pi-Bolt at the pinned commit, clones both extensions at
their pinned commits, downloads the Pi-Bolt release and verifies its SHA-256,
checks the task hash, and writes the model credential from `$LOCAL_LLM_KEY` into
`harness/.secrets/` (git-ignored).

```bash
export LOCAL_LLM_KEY='...'          # your endpoint's key
bash harness/fetch_inputs.sh
export DOCKER_HOST=unix://$HOME/.colima/default/docker.sock
```

## 2. Point the workers at your endpoint

`harness/config/models.tmpl.json` is rendered per instance with the relay's
container hostname. The relay is the only process that sees your credential, and
the only destination it forwards to is `UPSTREAM_HOST`/`UPSTREAM_PORT`, taken
from the environment when the relay starts (defaults: `host.lima.internal:9091`,
the host as seen from a Colima VM).

If your endpoint is not on the Docker host at port 9091, set the relay's upstream
when starting it, or edit the defaults in `harness/run_trial.py::setup_networks`.

## 3. Preflight (do not skip)

```bash
python3 harness/preflight.py
```

This starts one relay per competitor and makes 12 inference calls from a worker
container in each: small, tool-calling and long-streaming shapes. It must print
`PREFLIGHT STABLE`. A trial timed on an unstable relay is not a valid speed
measurement.

## 4. Run the pairs

```bash
python3 harness/run_trial.py --trial r1 --order glla,goal-x --max-seconds 2700 --thinking low --memory 6g
python3 harness/run_trial.py --trial r2 --order goal-x,glla --max-seconds 2700 --thinking low --memory 6g
```

Each run recreates the instance volume, starts the relay and the worker, drives
Pi-Bolt over RPC, samples the frozen tests every 30 seconds from a separate
container, and snapshots the volume when the run ends. Use a fresh `--trial id`
to avoid overwriting the committed results.

The runner records, per run:

- `results/logs/<trial>/<ext>/events.jsonl.gz` — every RPC record with monotonic
  and UTC timestamps
- `results/logs/<trial>/<ext>/relay.jsonl.gz` — every model request
- `results/<ext>-<trial>-runmeta.json` — wall clock, sleep events, relay health,
  validity verdict
- `results/<ext>-<trial>.patch` — the candidate's diff from the pinned baseline

## 5. Evaluate and re-derive the charts

```bash
python3 harness/replication.py evaluate r1
python3 harness/replication.py evaluate r2
python3 harness/replication.py aggregate
python3 tools/derive_phases.py
python3 tools/make_charts.py            # rewrites assets/*.svg
python3 tools/make_charts.py --check    # must report "identical"
python3 tools/check_svg.py              # XML well-formedness of every chart
```

`tools/make_charts.py --check` fails if the committed charts differ from what the
committed data produces, which is the reproducibility claim made in the README.

## 6. Cost and time of a full re-run

At list prices for the pinned model, one pair costs well under one US dollar and
takes roughly 10–20 minutes of wall clock (two runs, sequential). The container
images are built on first use (`goalbench/base`, `goalbench/relay`,
`goalbench/eval`).

## Notes on isolation

- Each competitor has its own volume, internal Docker network and relay.
- Workers have no route to the internet, no git remotes, and a read-only root
  filesystem apart from their volume and `/tmp`.
- A host sleep, a Docker interruption, a relay failure rate above 10 % or a
  container OOM kill marks a run invalid. The harness keeps the diagnostics and
  reports the run as invalid rather than counting it.
