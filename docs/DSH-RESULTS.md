# DeepSeek Harness native goal: executed results

This page records what the DSH competitor actually did. It is a **DSH-only**
result: the Pi competitors were not run to a terminal state in the fixed
300-second smoke limit, so nothing here ranks DSH against GLLA or pi-goal-x.
Read [methodology](METHODOLOGY.md) first; the limitations below are part of the
result, not a footnote.

## What was executed

Two independent trials of the real `@deepseek-ai/dsh@0.2.1-rc.5` native goal
stack (`goal`, `tool-goal`, `command-goal`, `goal-round-driver`), pinned by
`harness/dsh/package-lock.json`, driving the same task file, baseline and model
as the historical Pi runs.

| | `dsh-only-1` | `dsh-only-2` |
|---|---|---|
| Outcome | `goal_complete`, valid | `goal_complete`, valid |
| Native goal phase | `complete`, `activation: disarmed` | `complete`, `activation: disarmed` |
| Autonomous rounds | 1 | 1 |
| Goal-relative elapsed | 319.4 s | 412.9 s |
| Total run wall clock (incl. warm-up) | 446.5 s | 421.5 s |
| Model requests | 53, 0 failed | 60, 0 failed |
| Input / output tokens | 64.1k / 29.5k | 47.0k / 25.5k |
| Cached prompt tokens | 3.06M | 2.58M |
| Nominal cost | $0.073 | $0.060 |
| Externally verified at | 216.7 s | 143.9 s |
| Independent frozen suite | 10 passed, 0 failed | 10 passed, 0 failed |
| Independent adversarial suite | 6 passed, 0 failed | 6 passed, 0 failed |
| Independent CLI parity suite | 1 passed, **1 failed** | 1 passed, **1 failed** |
| Out-of-scope edits | `.github/workflows/ci.yml` | `.github/workflows/ci.yml` |
| Auditor | `not_applicable` | `not_applicable` |

Both runs changed the same four file paths and modified no benchmark datasets.

The CLI parity failure is the same test in both runs:
`test_help_output_byte_identical` fails because the candidate changed the text
printed by `bench/report.py --help`. The escaping change itself passed the
frozen and adversarial suites; the help text is a user-visible interface change
the task did not request. Both runs also edited the CI workflow, which the task's
"no unrelated refactoring" constraint did not ask for. These are reported, not
waived: `independent_tests_pass` is `false` for both runs.

## Deterministic lifecycle checks

`harness/tests/run_dsh_fixture.sh` drives the real pinned DSH packages against a
local OpenAI-compatible fixture (explicitly not a model benchmark) and asserts the
persisted native state. Re-run for this PR: `complete` reached `goal_complete`
after 2 rounds with exit 0; `cap` reached `goal_blocked` after 2 rounds with
blocker code `round-limit`; `blocked` reached `goal_blocked` after 3 rounds with
`model-reported`. The two blocked cases exit non-zero and are therefore recorded
as invalid runs by design.

## Wire-level evidence

Every recorded request in both runs used `deepseek-v4.1-flash` with
`reasoning_effort: "low"`, through the isolated relay, with `stream_options.
include_usage: true`. The task hash `d911abf5…a252e9` matches
`results/shared-task.md` byte-for-byte in both run metas.

Two request shapes are present, and they must not be compared as if identical:

* one in-session warm-up request per run, with zero tools and
  `max_completion_tokens: 4096`;
* all goal-round requests, with the DSH tool schema.

The Pi competitors warm up in a separate process before the timed worker, so the
warm-up accounting is not symmetric between harnesses. Warm-up time is inside the
"total run wall clock" column and outside the "goal-relative" column.

## Isolation evidence

Both workers: 2 CPUs, 6 GiB memory and memory+swap, `pids=512`, read-only rootfs,
`cap-drop ALL`, `no-new-privileges`, UID 1000, and a per-worker internal network
whose only peers are the worker and its relay. The checked-in seccomp profile
(`harness/docker/worker-seccomp.json`, SHA-256 `511ac3c8…979795`) is applied to
all competitors in new runs; it is deliberately weaker than Docker's default, as
described in the methodology, and it is what lets DSH's Bubblewrap
`workspace-write` shell start at all.

`harness/tests/test_sandbox.sh` confirms a write inside the workspace and a
denial outside it; `harness/tests/test_network.sh` confirms outbound HTTPS fails
from an internal worker network. Neither is a container-escape audit.

## Verification commands

```bash
export DOCKER_HOST=unix:///Users/hootie/.docker/run/docker.sock
export UPSTREAM_SCHEME=https UPSTREAM_HOST=opencode.ai UPSTREAM_PORT=443
export UPSTREAM_PREFIX=/inference/go/openai UPSTREAM_MODELS_PATH=/inference/go/v1/models

python3 harness/run_trial.py --trial <fresh-id> --order dsh --max-seconds 1800 --thinking low --memory 6g
python3 harness/replication.py evaluate <fresh-id> dsh
python3 harness/replication.py timeline <fresh-id> dsh
python3 harness/replication.py aggregate <fresh-id>,<second-id> dsh
```

`run_trial.py` refuses a trial ID that already has evidence, so these commands
never overwrite the committed runs. `replication.py evaluate` also refuses to
overwrite an existing evaluation; pass a fourth argument to write a fresh
outcome for an old trial.

## Committed artifacts

| File | SHA-256 |
|---|---|
| `results/dsh-dsh-only-1.patch` | `e60e2a38ca67e5210bb019c777f8363c6bf89496f461e1384fc5a47e45a66103` |
| `results/dsh-dsh-only-2.patch` | `1e2faf77bcb7a0e1439a5304d9c270140e12511c7e098907a7bdec122eef5f5c` |
| `results/dsh-dsh-only-1-runmeta.json` | `3a77fc4269faea35c961204255bed00ed6a39132cfc7d862103614b27866a2b7` |
| `results/dsh-dsh-only-2-runmeta.json` | `f2ff55a6d88ce5553a5cc16a5afd9e2ff26a5d0b1ebfb0200abac25ffd7512b0` |
| `results/replication-evaluation-dsh-only-1.json` | `53e35a839d764b57e73ecc17f5e77853e45a1c557ad986f23e6f255bdc47d04a` |
| `results/replication-evaluation-dsh-only-2.json` | `4d9960fb262e714ecfbbda4fd43769202da16cea1b070d0ed070caed07aea5f0` |
| `results/comparison-dsh-only-1-dsh-only-2.json` | `106137a0452755d39a12991d6144fa75214997e77384036d8516b0489598d9cd` |

## Limitations and unverified behavior

* **No three-way ranking.** Balanced ordering across three competitors exists in
  the harness and was exercised by the historical Pi runs, but no completed
  three-way campaign with DSH was executed.
* **Provider substitution.** New runs used OpenCode Go. The model identifier is
  the same; identical weights and serving behavior are not proven, so timings are
  not comparable with the historical local-endpoint `r1`/`r2` numbers.
* **Warm-up asymmetry, different prompts and tool schemas.** DSH is a different
  harness. Any timing difference is not attributable to the goal mechanism alone.
* **No DSH auditor.** DSH has no independent completion auditor, so
  `audit_verdicts` is `not_applicable`, not zero.
* **Objective normalization.** DSH stores the objective with surrounding
  whitespace trimmed, so the persisted objective omits the task file's final
  newline. The task bytes and hash are unchanged; the adapter checks equality
  after this native normalization and reports `objective_matches_normalized_task`.
* **Weaker seccomp filter.** All new runs permit nested unprivileged namespaces so
  Bubblewrap can start. The outer Docker boundary is unchanged, but the syscall
  filter is not Docker's default.
* **Single or paired trials.** Two valid runs are enough to show the lifecycle
  reproduces, not enough for a confidence interval.
* **`dsh-smoke05`, `cross-harness-r1` and `cross-harness-r2` are not results.**
  The first failed closed on the sandbox; the others hit the fixed 300-second
  limit with an active goal and are recorded as invalid.
* **Terminal state checks** cover the persisted goal state, the independent
  evaluator and the recorded wire metadata. They do not prove the model used the
  optimal approach.
