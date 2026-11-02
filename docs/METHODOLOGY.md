# Methodology

## Cross-harness native-goal extension

The original Pi-only `s0`, `r1`, and `r2` measurements below remain historical.
The new DSH competitor is a **cross-harness native-goal comparison**, not an
isolated extension A/B: DSH has different system prompts, tools, scheduling and
no independent completion auditor (`not_applicable`, not zero). Its native
`goal`, `tool-goal`, `command-goal` and `goal-round-driver` run unmodified; a
thin adapter dispatches `/goal` through DSH's command registry and observes the
persisted goal. It does not simulate continuation or treat prose as completion.

All workers receive the same task file, baseline, model, low reasoning effort,
resource limits, isolated relay and independent evaluator. DSH's goal domain
trims surrounding whitespace when creating its objective; the stored objective
therefore omits the task file's final newline. The original task bytes and hash
are unchanged, and the adapter checks equality after this native normalization.
The difference must be disclosed rather than described as byte-identical goal
storage. The relay captures actual model and effort, request-shape fields,
system/tool hashes and usage without recording message bodies or credentials;
any missing or mismatched effort or model invalidates a run. Completion reported
by a harness is not the independent quality gate.

The adapter keeps DSH alive through native rounds until a persisted terminal
state or time limit; a timeout is invalid and is not proof of clean cancellation
or a terminal native state. Deterministic fixture tests exercise two rounds and
complete, model-reported blocked, and round-limit blocked. DSH uses a native
warm-up in the same session before goal dispatch; Pi warms up via its own CLI
before the timed worker. This timing asymmetry, different system/tool schemas,
provider implementation, and lack of a DSH auditor limit causal comparison.
The new runs may use OpenCode Go rather than the historical local endpoint;
the same model identifier does not prove identical weights or service behavior,
so do not compare their timing or cost directly with historical `r1`/`r2`.

The Docker Desktop Linux kernel used for development has no usable Landlock and
its default seccomp blocks nested user namespaces. DSH's workspace-write bash
therefore failed closed in the first run; that run is invalid for comparison.
For subsequent runs all workers use the same checked-in seccomp profile, based
on Moby's default with `clone`, `unshare`, `mount`, `umount2` and `pivot_root`
allowed so unprivileged bubblewrap can create its inner filesystem namespace.
The host sleep monitor relies on macOS `pmset`; it does not establish sleep
coverage on Linux. This is a **weaker syscall filter than Docker's default**, not an identical
security profile to historical runs. Non-root execution, no-new-privileges,
cap-drop, read-only root and the per-worker internal network remain in force.
Docker already supplies the PID namespace; the DSH image's bwrap wrapper omits
only its nested PID/proc setup because that mount is refused on Docker Desktop.
A filesystem probe confirmed writes inside the workspace and denial outside it;
this is not a comprehensive container escape audit. Use the same profile for
all three competitors and do not compare the first run's timings as controlled.

Use fresh trial IDs; the original charts and summary are not updated by these
runs. The maintained campaign executed here is **DSH-only** (see `results/`),
because the Pi competitors did not reach a terminal state inside the fixed
300-second smoke limit. Three-way order support exists in `run_trial.py` and
`replication.py`, but ordering/rotation controls are only exercised by the
historical Pi results, not by a completed three-way DSH campaign. Report a
DSH-only result as a DSH result, never as a three-way ranking. The two executed
trials and their independent pass/fail counts are in
[`docs/DSH-RESULTS.md`](DSH-RESULTS.md).

Two goal-management extensions for **Pi** were run on an identical coding task in
isolated containers. The runtime was **Pi-Bolt 1.0.8**, a compiled fork of Pi 1.4.0
that the extensions load into unchanged; Pi-Bolt is what makes the environment
pinned, isolated and fast, not what the extensions are written for. This document describes the design, the controls, the
instrumentation and the scoring, and states what the results can and cannot
support.

- Exploratory trial `s0`: one pair, `high` thinking level, 4 GiB memory, and two
  confounders found afterwards (a relay defect during the GLLA run, and a macOS
  clamshell sleep overlapping the pi-goal-x run).
- Controlled replication `r1`/`r2`: two pairs in alternating order, `low` thinking
  level, 6 GiB memory, a verified-stable relay, and no host sleep.

## 1. What is being compared

Only one variable is intended to differ: the goal-management extension.

| Held constant | Value |
|---|---|
| Agent | Pi 1.4.0 (the extensions are Pi extensions) |
| Runtime used | Pi-Bolt `bolt-v1.0.8`, linux-arm64, JIT off — a compiled fork of Pi 1.4.0 (SHA-256 `f5304867…`) |
| Runtime commit | `fd4530c9611f0cffc18aa226c985fcc2603d2577` of `opensec-git/Pi-Bolt`, branch `pi-bolt` |
| Coding model | `deepseek-v4.1-flash` through an OpenAI-compatible endpoint, one model for implementation and audit |
| Thinking level | `high` (s0) / `low` (r1, r2), identical for both extensions within a campaign |
| Task | `results/shared-task.md`, SHA-256 `d911abf5…`, identical bytes for both |
| Container | 2 CPU, 6 GiB, 512 pids, read-only root filesystem, non-root uid 1000, `cap-drop ALL` (five capabilities retained only by the entrypoint), `no-new-privileges` |
| Network | one internal Docker network per competitor; the only reachable peer is that competitor's relay |
| Starting state | fresh volume from the pinned commit, fresh session, empty goal state |

## 2. Isolation

Each competitor gets its own container, volume, network and relay. The model
credential lives only in the relay; workers hold a dummy key. The relay forwards
to a single upstream URL and logs every request. Workers have no route to the
public internet, no git remotes, and no access to another competitor's volume.
The host's own Pi configuration is never mounted.

The auditors differ in architecture and that difference is the thing being
measured, not a fairness violation: GLLA runs its auditor as a detached Node
worker that spawns a separate `pi --mode rpc` session; pi-goal-x runs an
in-process nested session. Both call the same model with the same provider
configuration.

## 3. Driving the agents

Both extensions are driven the way a user drives them, over Pi's RPC protocol:

- GLLA is started with `/goal plan <task>`; pi-goal-x with `/goal <task>`. The
  text after the prefix is byte-identical.
- Extension dialogs (`select`, `confirm`, `input`, `editor`) are answered by one
  deterministic policy shared by both: enable the auditor when offered, confirm
  proposals, and answer clarification questions with a fixed text that restates
  the task's requirements without adding any.
- Every question and answer is recorded in `results/logs/*/<ext>/ui-script.json.gz`.
- Read-only status widgets are captured, never answered.

A run ends when the extension's own persisted state reaches a terminal goal
state, or at the wall-clock limit (45 minutes), whichever comes first. A run that
hits the limit is recorded as a limit, not as a completion.

## 4. Instrumentation

Timings come from three independent clocks:

1. **In-container monotonic clock** in the runner, which records every RPC
   record, tool call, milestone and phase boundary (`events.jsonl`).
2. **UTC wall clock** on every record, so sleep and suspension can be detected.
3. **External wall clock** on the host, around the whole run, plus a separate
   verifier container that re-runs the frozen acceptance tests against a snapshot
   of the workspace every 30 seconds.

A monitor polls `pmset -g log` every 20 seconds, Docker reachability, and the
relay's request log. A host sleep, a Docker interruption, a relay failure rate
above 10 %, or a container OOM kill marks the run **invalid**; invalid runs are
kept with their diagnostics and never counted as speed measurements.

## 5. Independent evaluation

The extensions' own auditors are not the judge. After each run, the candidate
tree is copied to a throwaway container and tested with a frozen suite that the
extensions never see:

- **10 acceptance tests**: escaping at every dynamic insertion point (text and
  attributes), Unicode, no double escaping, no injection, XML well-formedness,
  byte-identical SVG output for ordinary inputs, unchanged CLI.
- **6 adversarial tests**: CDATA terminators, entity-looking input, attribute
  breakout, whitespace, idempotency, every dynamic string in one document.
- **CLI parity** (replication only, added after the runs from the task's own
  "preserve the existing command-line interface" constraint): `--help` and the
  Markdown tables must be byte-identical to the pristine baseline.

Trees are copied in with anonymised labels and the mapping is recorded after
scoring.

## 6. Scoring

Quality is scored on 100 points: goal understanding 20, implementation 35, tests
and evidence 20, scope and maintainability 10, completion accuracy 15. Every
score in `reports/REPLICATION_REPORT.md` cites the artifact that supports it.
Reliability is scored separately (lifecycle reporting, recovery, redundant
verification, durable state, diagnostics and human intervention).

Speed is never folded into the quality score. The reports give both, separately,
with ranges.

## 7. Phase model

`tools/derive_phases.py` splits each run into mutually exclusive segments from
recorded timestamps only: drafting, coding and self-testing, contract
reconciliation (claim to first audit), the audit rounds themselves, rework
between audit rounds, and settlement. The segments sum to the run's wall clock;
any drift above one second is reported.

## 8. Threats to validity

- **n = 2 pairs.** Medians of two values. The direction is consistent across
  orders and phases, but the estimate is weak.
- **One host, one model, one language model version.** Results may not transfer.
- **Determinism.** The model was effectively deterministic: both extensions
  produced recognisably similar trajectories across runs, so the variance that
  remains is mostly audit duration.
- **Environment drift.** The exploratory campaign used 4 GiB and `high` thinking;
  the replication used 6 GiB and `low`. The two campaigns are therefore not
  directly comparable in absolute seconds, only in direction and proportion.
- **One post-hoc check.** The only quality difference between the two extensions
  in the replication comes from the CLI-parity check added after the runs. It is
  derived from the task text and applied blind, but it is still post-hoc.
- **Fault injection was not run.** The relay can inject slow, failing and
  aborted audit calls; those scenarios (S1–S4 in the exploratory report) were
  never executed, so no claim is made about auditor-crash behavior.
