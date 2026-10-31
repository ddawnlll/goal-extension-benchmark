# Replication: GLLA vs pi-goal-x (clean controlled run)

> **Framing note.** The extensions compared here are **Pi** extensions. Every run
> used **Pi-Bolt 1.0.8**, a compiled fork of Pi 1.4.0, as the pinned, isolated
> runtime; "Pi-Bolt" in these records always names that runtime, never the agent
> the extensions are written for. Measurements below are unchanged.

**Supersedes nothing.** The exploratory trial `s0` and its `FINAL_REPORT.md` are preserved unchanged; they remain the exploratory evidence. This report covers a new, controlled replication run on the same pinned infrastructure.

**Primary answer.** Yes — the gap persisted after removing the relay confounder. With a stable relay, no host sleep, and four valid runs, pi-goal-x is consistently faster at producing an independently verified completion: median **363.9 s** vs **660.5 s** (1.8×), and it wins both pairs in both execution orders. It also uses roughly one third of the tokens and cost.

**Secondary answer.** GLLA's extra contract and audit machinery produced **one real, independently confirmable improvement** (in `r2` it found and fixed a CLI regression that pi-goal-x shipped undetected in `r1`), but it also produced one 188 s contract-bookkeeping detour that found no code defect, and no improvement in the 16-test acceptance outcome: all four implementations pass every frozen and adversarial test.

---

## 1. Did the Mac sleep during the first experiment? (required check before running)

Evidence from `pmset -g log` (local time, UTC+3), cross-checked against the benchmark's own wall-clock timestamps:

```
2026-10-31 14:02:49  Wake   Wake from Deep Idle ... lid ...            <- last wake before the experiment
2026-10-31 16:02:01  Sleep  Entering DarkWake state due to 'Clamshell Sleep':TCPKeepAlive=active Using AC 1229 secs
2026-10-31 16:02:01  Notification  Display is turned off
2026-10-31 16:22:30  Wake   DarkWake to FullWake ... DriverReason:lid  <- lid reopened
```

Exploratory run windows (UTC → local):
- GLLA `s0`: 12:41:53Z → 12:58:20Z = **15:41:53 → 15:58:20 local** — no sleep event.
- pi-goal-x `s0`: 12:58:20Z → 13:08:38Z = **15:58:20 → 16:08:38 local** — **overlapped** the clamshell sleep from 16:02:01.

So the operator's suspicion was correct in kind but inverted in attribution: the sleep hit **pi-goal-x's run**, not GLLA's. A `caffeinate -dimsu` assertion had been active for 27 h but does not prevent clamshell sleep.

Corroborating evidence inside the affected run: the relay request timestamps for pi-goal-x show a **112 s gap** (t≈137 s → t≈250 s, i.e. 13:00:37Z → 13:02:29Z) straddling the 13:02:01Z sleep onset, and the machine remained in DarkWake (display off, CPU throttled) until 13:22:30Z, which is 14 minutes *after* the run ended.

**Uncertainty.** The system was in DarkWake, not full suspend: the guest kept making progress (its last request is stamped 13:07:22Z, five minutes into the dark-wake window), so the run completed. The magnitude of the slowdown is therefore **not** quantifiable from the logs — only that a sleep transition and a 112 s request gap coincide. I treat `s0`'s pi-goal-x timing as confounded and unusable for speed comparison, which is why the replication was necessary. Directionally, the confound penalised pi-goal-x, i.e. it would have *understated* pi-goal-x's advantage, not manufactured it.

---

## 2. Relay preflight (before any timed run)

`results/replication-preflight.json`. Per competitor, on its own internal network with its own relay container — the exact timing topology:

| | requests | failed | median latency | max latency | relay-side failures | `reasoning_effort` seen upstream |
|---|---:|---:|---:|---:|---:|---|
| GLLA instance | 12 | 0 | 1.379 s | 6.209 s | 0 | `low` |
| pi-goal-x instance | 12 | 0 | 1.200 s | 6.258 s | 0 | `low` |

**Verdict: STABLE.** No relay code changes were made after this point. The relay image digest for all four runs is `sha256:b9376fbc…`.

---

## 3. Harness changes, and the trials that had to be discarded

All four scored runs use: Pi-Bolt `bolt-v1.0.8` (`f5304867…`), baseline `fd4530c`, task hash `d911abf5…`, GLLA `0.39.54` (`b1c36dc`), pi-goal-x `0.34.1` (`b0fc15e`), `deepseek-v4.1-flash`, **thinking level `low`** (operator instruction; constant across arms; the exploratory run used `high`), auditing enabled for both, scripted UI policy unchanged, identical container constraints.

Three deviations were required, all disclosed:

1. **Memory limit 4 GiB → 6 GiB (both arms).** At 4 GiB, two GLLA containers were killed mid-audit at ~600 s with no final state and no stderr. A diagnostic GLLA run at 6 GiB completed with `ExitCode 0` and `OOMKilled=false` (836.7 s). The 4 GiB containers had already been removed before `docker inspect`, so OOM is the most probable cause but **not proven**. The 4 GiB kills are reported as a reliability observation, not as a speed measurement, and are archived under `results/invalid/`.
2. **Per-run artifact snapshot.** The exploratory collection read both trials from one volume and therefore duplicated the second run's data. Collection now snapshots the volume immediately after each run. The first replication attempt (paired runs at 4 GiB) was discarded for this reason and is archived under `results/invalid/collection-failure/`; it is not scored.
3. **Artifact naming.** New trials write `competitors/<name>/<trial>/` and `results/<name>-<trial>-*`; the `s0` tree is untouched.

Every scored run started from a freshly recreated volume, a fresh Pi session, empty goal state and an empty relay log. Verified per run from the collected trees (`sessions/`, `.pi-glla/`, `.pi/goals/` contain only that run).

---

## 4. The four runs, individually

All four were monitored every 20 s for host sleep/wake, Docker/Colima reachability and relay health. No sleep event, no Docker gap, no rate limiting and no stall occurred in any scored run.

| run | order | UTC start | UTC end | wall | exit | relay requests | relay failures | valid |
|---|---|---|---|---:|---|---:|---:|---|
| GLLA `r1` | 1st in pair 1 | 15:00:15Z | 15:11:54Z | 698.7 s | terminal | 49 | 0 | yes |
| pi-goal-x `r1` | 2nd in pair 1 | 15:13:18Z | 15:18:16Z | 297.7 s | terminal | 27 | 0 | yes |
| pi-goal-x `r2` | 1st in pair 2 | 15:22:30Z | 15:29:40Z | 430.0 s | terminal | 23 | 0 | yes |
| GLLA `r2` | 2nd in pair 2 | 15:30:37Z | 15:41:14Z | 622.2 s | terminal | 42 | 0 | yes |

### GLLA `r1` — 698.7 s
`/goal plan` → contract confirmed at 89.3 s (3 dialogs: confirm, a "Decision needed" replacement of an unrunnable verification-contract item, then "Tweak goal?"). Coding and self-testing until the completion claim at 323.5 s. Two **deterministic pre-audit** rejections at 341 s and 363 s (contract item 4 contained an unrunnable `python3 -c` fragment). Contract/rework reconciliation 363 s → 567 s (**188 s, no code defect found**). One model audit ran 534 s → 689 s (154.8 s, verdict `approved`). Settlement 10 s later, run total 698.7 s. 19 changed files, including golden SVG fixtures and a fixture copy of one results folder.

### pi-goal-x `r1` — 297.7 s
`/goal` → auditor explicitly enabled, contract confirmed at 50.7 s (2 dialogs). Coding and self-testing to `completion_requested` at 189.1 s. Single in-process audit 189 s → 270 s (80.8 s, `approved`). `goal_completed` + `goal_archived` immediately, settlement 28 s later. 3 changed files. **One compliance defect escaped its own checks:** it added 4 lines to the `report.py` module docstring, which is `argparse`'s `description`, so `--help` output changed (see §7).

### pi-goal-x `r2` — 430.0 s
Confirmed at 26.4 s (2 dialogs), completion request at 136.8 s, single audit 137 s → 402 s (**265.5 s**, `approved`), settlement 28 s later. 3 changed files. This time the docstring was left alone (documentation went only to `bench/README.md`), so CLI parity holds.

### GLLA `r2` — 622.2 s
Confirmed at 70.3 s (1 dialog only — no contract detour). Coding to the claim at 302.3 s. Model audit round 1 immediately 302 s → 412 s (109.6 s) → **`disapproved`** with a concrete, real defect: the escaping paragraph added to the module docstring changed `--help` output, contradicting contract item 6 ("preserve the CLI"). Repair 412 s → 453 s (41 s). Model audit round 2 453 s → 611 s (158.3 s) → `approved`. Settlement 9 s later. 3 changed files.

---

## 5. Aggregate comparison (two paired trials, n = 2 per arm)

| Metric | GLLA | pi-goal-x |
|---|---|---|
| Total elapsed, s (runs) | 698.7, 622.2 | 297.7, 430.0 |
| **Median total, s** | **660.5** | **363.9** |
| Range, s | 622.2 – 698.7 | 297.7 – 430.0 |
| Pair 1 ratio (GLLA/goal-x) | 2.35× | — |
| Pair 2 ratio (GLLA/goal-x) | 1.45× | — |
| Drafting/confirmation, s | 89.3, 70.3 | 50.7, 26.4 |
| Coding + self-testing, s | 234.2, 232.0 | 138.4, 110.4 |
| Deterministic-contract reconciliation, s | 188.5, 0 | 0, 0 |
| Model audit time, s | 154.8, 267.9 | 80.8, 265.5 |
| Redundant auditing after acceptance, s | 0, 0 | 0, 0 |
| Post-approval settlement, s | 10, 9 | 28, 28 |
| Model requests | 49, 42 | 27, 23 |
| Relay failures | 0, 0 | 0, 0 |
| Input tokens | 169,217 / 172,182 | 93,128 / 65,917 |
| Output tokens | 61,168 / 62,682 | 19,745 / 14,179 |
| Cached input tokens | 7,052,416 / 3,518,336 | 1,065,600 / 660,608 |
| Nominal cost, USD (list prices) | 0.167 / 0.148 | 0.058 / 0.041 |
| Audit verdicts | 2 deterministic + 1 model (r1); 0 deterministic + 2 model (r2) | 1 model (r1); 1 model (r2) |
| Model audit rejections | 0 (r1), 1 (r2) | 0, 0 |
| Independent tests | 16/16, 16/16 | 16/16, 16/16 |
| CLI parity (`--help` byte-identical) | pass, pass | **fail**, pass |
| Changed files | 19, 3 | 3, 3 |
| Manual interventions | 0, 0 | 0, 0 |
| OOM kills | 0, 0 | 0, 0 |
| Final classification | `VERIFIED_COMPLETE`, `VERIFIED_COMPLETE` | `VERIFIED_COMPLETE`, `VERIFIED_COMPLETE` |

Token and cost medians: GLLA ≈ 170.7 k input / 61.9 k output / **$0.157**; pi-goal-x ≈ 79.5 k input / 17.0 k output / **$0.050** — about **3.1× cheaper**.

---

## 6. Phase decomposition (requirement 8)

Times in seconds; phases are mutually exclusive within a run.

| Phase | GLLA r1 | GLLA r2 | goal-x r1 | goal-x r2 |
|---|---:|---:|---:|---:|
| Drafting + confirmation | 89.3 | 70.3 | 50.7 | 26.4 |
| Coding + self-testing (to first claim) | 234.2 | 232.0 | 138.4 | 110.4 |
| Deterministic-contract reconciliation | 188.5 | 0 | 0 | 0 |
| Model audit (useful verification) | 154.8 | 267.9 | 80.8 | 265.5 |
| Repair after a rejected audit | (inside reconciliation above) | 41 | 0 | 0 |
| Redundant auditing after acceptance | 0 | 0 | 0 | 0 |
| Post-approval settlement | 10 | 9 | 28 | 28 |
| **Total** | **698.7** | **622.2** | **297.7** | **430.0** |

Phase sums exclude instance preparation and the warm-up session before Pi's process launch (2–22 s per run); the totals are the externally measured wall clock. Audit times are the extensions' own job/event durations.

Two observations:
- GLLA is slower in **both** phases that precede any audit: drafting (+40 s median) and coding/self-testing (+109 s median). Even with zero audit overhead, its median would be ~400 s vs pi-goal-x's ~200 s.
- Audit time is highly variable in both extensions (goal-x 81 s vs 266 s; GLLA 155 s vs 268 s) and is the dominant source of within-arm variance.

---

## 7. Independent evaluation (blind)

Each run's tree was copied to a container and tested by the same frozen suite (10 tests) plus the adversarial suite (6 tests). The evaluator saw trees labelled `C1`/`C2` (mapping recorded in `results/replication-evaluation-r*.json`); the mapping is disclosed only here.

| Run | Frozen | Adversarial | CLI parity (`--help`, tables) | Datasets modified | Out-of-scope files |
|---|---|---|---|---|---|
| GLLA r1 | 10/10 | 6/6 | pass | none | none (19 files, all under `bench/`, but heavy: golden SVGs + a copied results fixture) |
| GLLA r2 | 10/10 | 6/6 | pass | none | none |
| goal-x r1 | 10/10 | 6/6 | **fail** (`--help` gained 5 lines) | none | none |
| goal-x r2 | 10/10 | 6/6 | pass | none | none |

The CLI-parity check is derived directly from the task's constraint "Preserve the existing command-line interface" and was written **after** the runs; it was applied identically to all four trees and to the pristine baseline (`--help` and Markdown tables byte-compared). It is the only test that separates the four implementations.

Per-run quality (same rubric as the exploratory report, applied to each run):

| Category | GLLA r1 | GLLA r2 | goal-x r1 | goal-x r2 |
|---|---:|---:|---:|---:|
| Goal understanding /20 | 17 (extra contract decision) | 19 | 18 | 18 |
| Implementation /35 | 35 | 35 | 33 (CLI help changed) | 35 |
| Tests & evidence /20 | 19 | 18 | 17 | 17 |
| Scope & maintainability /10 | 7 (19-file footprint) | 9 | 8 | 9 |
| Completion accuracy /15 | 15 | 15 | 13 (unverified CLI change) | 15 |
| **Total** | **93** | **96** | **89** | **94** |

Medians: GLLA **94.5**, pi-goal-x **91.5**. The difference is one post-hoc check on one run; it is not a stable quality separation.

---

## 8. Primary question: was the first speed gap an artefact?

**No — it persisted, and the replication is cleaner than the original.**

| | s0 (exploratory, confounded) | replication (2 pairs, valid) |
|---|---|---|
| GLLA | 956.0 s (20 relay resets) | 698.7, 622.2 s → median 660.5 s |
| pi-goal-x | 598.9 s (sleep overlap) | 297.7, 430.0 s → median 363.9 s |
| Ratio | 1.60× | **1.81×** |

- Zero relay failures in all four replication runs, so the confounder is gone.
- No host sleep in any replication run (verified every 20 s), so the other confounder is gone.
- The gap holds in **both execution orders**: GLLA-first pair → 2.35×; pi-goal-x-first pair → 1.45×. Order does not explain it.
- The gap also holds in **every phase independently**: drafting, coding, and post-claim completion.

**Verdict: pi-goal-x is genuinely faster at producing an independently verified completion under these conditions.** Confidence: moderate — consistent direction across 2 pairs, 4 runs, and every sub-phase, but n = 2 and within-arm variance is large (goal-x ranged 298–430 s).

---

## 9. Secondary question: does GLLA's extra overhead buy correctness?

**Yes, once, in a way the frozen tests could not see — and no, in the 16-test acceptance outcome.**

- All four implementations pass 10/10 frozen + 6/6 adversarial tests, with byte-identical SVGs for ordinary input and untouched datasets. On the acceptance suite the extensions are indistinguishable.
- In `r2`, GLLA's auditor **rejected** its own completion with a specific, verifiable defect: the new escaping paragraph was placed in the module docstring, which `argparse` uses as `description`, so `--help` output changed — a direct violation of "Preserve the existing command-line interface". GLLA repaired it in 41 s and the re-audit approved.
- pi-goal-x made **the same class of change in `r1`** (5 added `--help` lines) and its audit approved it. It did not make it in `r2`.
- GLLA's deterministic pre-audit, by contrast, cost 188 s in `r1` and found **no code defect** — it rejected its own verification contract for containing an unrunnable shell fragment, then asked the operator to replace it.

So: **one genuine defect caught in two GLLA runs, one genuine defect missed in two pi-goal-x runs.** That is real evidence that independent auditing improves correctness, but the effect is small, not deterministic, and costs 1.8× wall clock and ~3× tokens.

---

## 10. Completion reliability

| | GLLA r1 | GLLA r2 | goal-x r1 | goal-x r2 |
|---|---|---|---|---|
| Settlement | clean, 10 s after approval | clean, 9 s | clean, 28 s | clean, 28 s |
| Stalls / hangs | none | none | none | none |
| Longest gap without a model request | 62.9 s | 76.7 s | 42.0 s | 97.8 s |
| Recoveries needed | 0 (relay) / 1 contract repair | 1 audit repair | 0 | 0 |
| Manual interventions | 0 | 0 | 0 | 0 |
| Misleading progress | none | none | none | none |
| Persisted final state | complete + archived | complete + archived | complete + archived | complete + archived |

Both extensions settled promptly once approved (GLLA faster: 9–10 s vs 28 s). Neither showed redundant post-acceptance auditing. Neither stalled.

**One reliability finding about the environment, not the extensions:** at the exploratory 4 GiB limit, GLLA's detached auditor was killed twice (silent container death, no final state, no stderr); pi-goal-x never approached that limit in any run. Whether this is an auditor-memory issue in GLLA or simply a heavy Node+Pi subprocess cannot be separated without per-process accounting, which the 4 GiB containers did not leave behind. At 6 GiB both settled cleanly in all four runs.

---

## 11. Uncertainty and threats to validity

1. **n = 2 per arm.** Medians of two values; ranges overlap nothing, but the estimate of the true median is weak. The direction is consistent across pairs, orders and phases.
2. **Single host, single model.** One machine, one model (`deepseek-v4.1-flash`), thinking `low`. Results may not transfer to other models or reasoning levels.
3. **Memory limit changed to 6 GiB** for both arms after 4 GiB kills. This is a deviation from the exploratory configuration; it is symmetric, but it means the absolute times are not directly comparable to `s0` (which also differs in thinking level).
4. **Deterministic model.** Goal text is identical, so trajectories are highly reproducible; two runs of one extension produced very different *audit* durations but similar coding paths. That reduces variance in coding and increases the relative weight of audit variance.
5. **The CLI-parity test is post-hoc.** It was written after observing the audit reports, though derived from the task text and applied blind to all four trees. Without it, all four runs would score identically on quality.
6. **DarkWake impact on `s0` is unquantified** (§1). I discarded that run's speed data rather than adjusting it.
7. **Fault-injection scenarios S1–S4 remain untested.** The relay supports them; they were not run because the operator asked for clean replication of normal completion.

---

## 12. Integrity and artifacts

| Original | Status |
|---|---|
| `results/FINAL_REPORT.md`, `results/*s0*`, `results/glla.patch`, `results/goal-x.patch` | untouched; `s0` remains the exploratory record |
| `baseline/pi-bolt` | `git status` clean, HEAD `fd4530c9611f0cffc18aa226c985fcc2603d2577` |
| `competitors/_glla-src`, `_goalx-src` | untouched pinned clones (`b1c36dc`, `b0fc15e`) |
| Host `~/.pi`, model server | never mounted or modified; server only received `/v1/models` and `/v1/chat/completions` |
| Pushes/PRs/deploys | none; worker repos have no remotes |

New artifacts:

```
results/
  replication-config.json            pins for the replication (incl. deviations)
  replication-preflight.json         24 preflight requests, per-instance latency/errors
  replication-comparison.csv         the table in §5
  replication-summary.json           medians/ranges per arm
  replication-timelines.json         per-run phases, tokens, audit records
  replication-evaluation-r1.json     blind evaluation, pair 1
  replication-evaluation-r2.json     blind evaluation, pair 2
  glla-r1.patch, glla-r2.patch, goal-x-r1.patch, goal-x-r2.patch
  {glla,goal-x}-{r1,r2}-{frozen,adversarial}-tests.log
  diagnostics/                       the 6 GiB GLLA diagnostic run and its evidence
  invalid/                           discarded trials with their diagnostics
competitors/<name>/<trial>/          logs, sessions, agent-config, extensions, workspace
```

Re-run:

```bash
export DOCKER_HOST=unix://$HOME/.colima/default/docker.sock
python3 harness/preflight.py                       # must print STABLE
python3 harness/run_trial.py --trial r1 --order glla,goal-x --max-seconds 2700 --thinking low --memory 6g
python3 harness/run_trial.py --trial r2 --order goal-x,glla --max-seconds 2700 --thinking low --memory 6g
python3 harness/replication.py evaluate r1 && python3 harness/replication.py evaluate r2
python3 harness/replication.py aggregate
```

---

## 13. Bottom line

- **Faster to verified completion: pi-goal-x**, by a factor of 1.8 (median 364 s vs 661 s), in both orders, at ~3× lower token cost, with no reliability penalty observed.
- **Thoroughness: GLLA**, by a narrow and non-deterministic margin — its independent auditor caught one real CLI regression that pi-goal-x shipped in one of two runs; its deterministic contract gate also cost 188 s in one run without finding any defect.
- **Both** reached `VERIFIED_COMPLETE` in all four runs, with no stalls, no manual interventions, and 16/16 independent tests passing.
- **Not declared:** an overall winner. The speed result is consistent and survives the confounder fix; the quality difference rests on a single post-hoc check and n = 2 pairs.
