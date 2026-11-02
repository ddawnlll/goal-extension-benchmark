# Reproduce the benchmark

## Cross-harness DSH runs (new trial IDs only)

The historical results below are retained, not overwritten. After fetching inputs,
provide the relay key privately in `harness/.secrets/local_api_key` (mode 600).
Do not put it in a worker environment or commit it. Build all images before
isolating workers; DSH installs the exact lockfile at image build time:

```bash
docker build -t goalbench/base:1 -f harness/docker/Dockerfile.base harness/docker
docker build -t goalbench/eval:1 -f harness/docker/Dockerfile.eval harness/docker
docker build -t goalbench/relay:1 harness/relay
docker build -t goalbench/dsh:1 harness/dsh
python3 -m unittest discover -s harness/tests -v
bash harness/tests/test_sandbox.sh
bash harness/tests/test_network.sh
```

For the OpenCode Go endpoint used in the new runs, configure the relay only:

```bash
export UPSTREAM_SCHEME=https UPSTREAM_HOST=opencode.ai UPSTREAM_PORT=443
export UPSTREAM_PREFIX=/inference/go/openai UPSTREAM_MODELS_PATH=/inference/go/v1/models
```

For a local compatible endpoint, omit those overrides. Set `DOCKER_HOST` to the
running daemon. Do not use the examples' IDs if they already exist. To reproduce
the deterministic native lifecycle checks (the local fixture is *not* a model
benchmark; it uses a dummy relay credential):

```bash
bash harness/tests/run_dsh_fixture.sh complete my-fixture-complete 19991
bash harness/tests/run_dsh_fixture.sh blocked my-fixture-blocked 19992
bash harness/tests/run_dsh_fixture.sh cap my-fixture-cap 19993
```

For a DSH-only run, use `--order dsh` (this is the campaign recorded in
[`docs/DSH-RESULTS.md`](DSH-RESULTS.md)):

```bash
python3 harness/run_trial.py --trial my-dsh-1 --order dsh --max-seconds 1800 --thinking low --memory 6g
```

For a controlled comparison rotate the order and keep time and resource limits
identical. The following are **commands to run**, not claims of results:

```bash
python3 harness/run_trial.py --trial my-r1 --order glla,goal-x,dsh --max-seconds 2700 --thinking low --memory 6g
python3 harness/run_trial.py --trial my-r2 --order goal-x,dsh,glla --max-seconds 2700 --thinking low --memory 6g
python3 harness/run_trial.py --trial my-r3 --order dsh,glla,goal-x --max-seconds 2700 --thinking low --memory 6g
python3 harness/replication.py evaluate my-r1 glla,goal-x,dsh
python3 harness/replication.py timeline my-r1 glla,goal-x,dsh
python3 harness/replication.py aggregate my-r1,my-r2,my-r3 glla,goal-x,dsh
# Re-evaluate a historical patch without overwriting its recorded evidence:
python3 harness/replication.py evaluate r1 glla,goal-x my-r1-recheck
```

For historical trials, evaluation reconstructs a candidate from the pinned
baseline and committed patch if its collected workspace is unavailable. The
optional fourth argument selects fresh output names; use it for old IDs.

The DSH profile currently supports `low` only. `--smoke` uses a different,
trivial objective and is not a benchmark score. Runs that time out, crash,
fail native lifecycle validation, or send the wrong model/effort are invalid;
independently passing the frozen, adversarial and CLI-parity suites is separate.
The worker seccomp profile intentionally permits nested unprivileged namespaces;
read the security limitation in `docs/METHODOLOGY.md` before using it. The relay
preflight covers all three network paths, not DSH's native lifecycle;
run it with a fresh `--id` before a campaign. See `docs/METHODOLOGY.md` for
prompt, warm-up and whitespace limits.

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
python3 harness/preflight.py --id my-preflight
```

This starts one relay per competitor and makes 12 inference calls from a worker
container in each: small, tool-calling and long-streaming shapes. It must print
`PREFLIGHT STABLE`. A trial timed on an unstable relay is not a valid speed
measurement.

## 4. Run the pairs

```bash
python3 harness/run_trial.py --trial my-r1 --order glla,goal-x --max-seconds 2700 --thinking low --memory 6g
python3 harness/run_trial.py --trial my-r2 --order goal-x,glla --max-seconds 2700 --thinking low --memory 6g
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
python3 harness/replication.py evaluate my-r1
python3 harness/replication.py evaluate my-r2
python3 harness/replication.py aggregate my-r1,my-r2 glla,goal-x
python3 tools/make_charts.py --check    # check historical charts without rewriting them
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
