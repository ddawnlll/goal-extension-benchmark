# GLLA vs pi-goal-x — Isolated End-to-End Benchmark

> **Framing note.** The extensions compared here are **Pi** extensions. Every run
> used **Pi-Bolt 1.0.8**, a compiled fork of Pi 1.4.0, as the pinned, isolated
> runtime; "Pi-Bolt" in these records always names that runtime, never the agent
> the extensions are written for. Measurements below are unchanged.

**Trial:** `s0` (paired, sequential, same hardware, same day)
**Benchmark root:** `$BENCH_ROOT` (created outside every existing project)
**Task SHA-256:** `d911abf544abd173aa191ef2c8cf761034fed795cd32e12f7456dd7452a252e9` (`results/shared-task.md`)
**Verdict summary:** both extensions reached `VERIFIED_COMPLETE`; **pi-goal-x is the better trade-off for unattended autonomous coding**, **GLLA produced the more defensive implementation** and the only audit that rejected work.

---

## 0. What was actually run, and what was not

| Item | Status |
|---|---|
| Paired normal-completion trial (S0) | **Run, complete** (GLLA then pi-goal-x, same host, matched limits) |
| Fault-injection scenarios S1 (slow auditor), S2 (auditor crash), S3 (repeated audit failure), S4 (misleading task progress) | **Not run.** The injection point exists (`/logs/control.json` on each relay: `slow`, `fail`, `abort`, with an `audit` matcher) and is documented, but it was not exercised. They are reported as untested, not as "passed". |
| Organic transient-failure observation | GLLA hit 20 upstream connection resets and still completed without a manual retry; pi-goal-x hit none. This is the only real recovery evidence in this trial. |
| Additional paired repetitions | **Not run.** One pair only, so every difference below has n=1. |

Nothing in the operator's existing Pi installation, Pi-Bolt checkout, sessions, extensions or model server was modified. All containers, volumes, networks, agent directories and workspaces were created for this benchmark.

---

## 1. Isolation and fairness as executed

| Control | Implementation |
|---|---|
| OS boundary | Docker 27.3.1 on Colima profile `benchmark` (isolated aarch64 VM, 6 CPU, 8 GiB), not the user's default profile |
| Worker | `goalbench/base:1`; **read-only root filesystem**, `--tmpfs /tmp`, non-root uid 1000, `--cap-drop ALL` (only `CHOWN/SETUID/SETGID/DAC_OVERRIDE/FOWNER` retained by the entrypoint before privileges are dropped), `--security-opt no-new-privileges`, `--cpus 2`, `--memory 4g`, `--memory-swap 4g`, `--pids-limit 512` |
| Filesystem | one named volume per competitor (`gb-glla-home`, `gb-goal-x-home`), fresh per trial; the Pi-Bolt runtime is a read-only release copy; the runner and the frozen tests are read-only mounts. No host home, no host `~/.pi`, no other competitor's volume |
| Network | one `--internal` network per competitor; the only reachable peer is that competitor's model relay. No external egress, no DNS beyond container names |
| Credential | the upstream model key lives only in the relay container; worker containers hold a dummy key and never see the real one |
| Writes out | repositories have **no git remotes**; `GIT_TERMINAL_PROMPT=0`, `GIT_ASKPASS=/bin/false`; no deploy/publish tools installed |
| Runtime parity | identical Pi-Bolt `bolt-v1.0.8` linux-arm64 release (`sha256 f5304867…`), identical base image, identical Node 22.21.1, identical models.json, `--thinking high`, same task bytes, same UI policy, auditing enabled for both |
| Resource ordering | sequential, GLLA first then pi-goal-x; no concurrency between competitors |

**One dependency correction was required and applied to both:** GLLA's detached auditor is a Node script (`scripts/goal-auditor-worker.mjs`), and the first attempt failed with `Executable not found in $PATH: "node"`. Node 22.21.1 was added to the shared base image so both competitors run in an identical runtime. That first attempt was discarded as an invalid run, not scored.

**One instrumentation correction was required and applied mid-trial:** the relay originally sent `Connection: close` upstream and forwarded synchronously; the local model proxy resets streams whose consumer stalls. This produced 20 failed/retried model requests during GLLA's run. The relay was fixed (decoupled reader, no forced close) before pi-goal-x started. **Consequence: GLLA's wall clock is inflated by retries that pi-goal-x did not experience.** This is disclosed everywhere it matters and is the main confound in this trial.

---

## 2. Baseline validation (task not already solved)

`bench/report.py` at `fd4530c` inserts titles, subtitles, panel names, build labels, plugin names, step names, formatted values, ratio notes and the `aria-label` attribute directly into SVG strings. Reproduced on the pristine baseline:

```
chart('T<script>x</script>', ...)  →  <text …>T<script>x</script></text>
```

No escaping helper exists; there are no existing tests for `report.py`. The task is genuine and comparably bounded, so no replacement task was needed.

---

## 3. A. Side-by-side comparison

| Metric | GLLA | pi-goal-x |
|---|---:|---:|
| Goal understanding /20 | 18 | 17 |
| Implementation /35 | 35 | 34 |
| Tests and evidence /20 | 19 | 17 |
| Maintainability /10 | 8 | 9 |
| Completion accuracy /15 | 15 | 15 |
| **Total quality /100** | **95** | **92** |
| Goal setup time | 109.9 s | 32.9 s |
| Implementation time | 298.8 s | 290.1 s |
| Completion overhead | 547.3 s | 275.9 s |
| Total elapsed time | 956.0 s | 598.9 s |
| Input / output tokens | 198,523 / 97,141 | 120,549 / 29,258 |
| Cached input tokens | 7,144,192 | 1,811,968 |
| Nominal model cost (list prices) | $0.219 | $0.082 |
| Model requests (relay) | 87 | 23 |
| Failed model requests (infrastructure) | 20 | 0 |
| Audit attempts (model) | 1 | 1 |
| Audit rejections | 1 (deterministic pre-audit) | 0 |
| Independent tests passed | 10/10 frozen, 6/6 adversarial | 10/10 frozen, 6/6 adversarial |
| Files changed | 4 | 3 |
| Lines +/− | +402 / −17 | +255 / −15 |
| False completion? | no | no |
| Final classification | `VERIFIED_COMPLETE` | `VERIFIED_COMPLETE` |
| Reliability score /100 | 82 | 90 |

Provider-reported cost was zero (the local proxy bills against an allowance); the USD figures above are computed from list prices for `deepseek-v4.1-flash` ($0.30 / $1.20 / $0.006 per Mtok) and are marked nominal.

**Scoring evidence**

| Category | GLLA | pi-goal-x |
|---|---|---|
| Goal understanding & confirmation | 18/20 — investigated all SVG writers, enumerated every dynamic insertion site (`chart`, `hero`, `long_hero`, plugin columns, `step_name`, `aria-label`), and **reproduced** the vulnerability with `xml.etree` before proposing. Cost: 3 approvals and a mid-flow contract replacement (its own pre-audit could not execute the stored contract). | 17/20 — reproduced the task verbatim with derived acceptance criteria (12/12 requirement groups, no deviation), confirmed in 33 s with the auditor explicitly enabled. Less investigative evidence in the proposal. |
| Implementation | 35/35 — `xml_text`/`xml_attr` (saxutils `escape`/`quoteattr`), replacement of code points XML 1.0 cannot carry, escaping at every insertion point. | 34/35 — one `esc()` helper applied at every insertion point, quotes escaped in text nodes too. No invalid-XML-character handling (not required by the task). |
| Tests & evidence | 19/20 — 359-line stdlib suite (ordinary, adversarial, Unicode, no-double-escaping, XML-parser validation, published datasets), wired into CI; 29 test commands run. | 17/20 — 211-line suite, 9 focused tests incl. `aria-label`, injection, ordinary output, XML parsing; 21 test commands run; not wired into CI. |
| Scope & maintainability | 8/10 — also edits `.github/workflows/ci.yml` (outside the stated surface, defensible but collateral); two helpers plus a regex. | 9/10 — one 6-line helper, three files, no collateral edits. |
| Completion accuracy | 15/15 — no claim without evidence; claims match the diff. | 15/15 — completion request backed by tests; final audit report cites files. |

Both candidates' ordinary-input SVGs are **byte-identical** to the pristine baseline (`OrdinaryOutputUnchanged` passed for both), no dataset was modified, and no test was weakened or deleted.

---

## 4. B. Completion overhead analysis

Both extensions spend nearly identical time *implementing* (≈290–299 s). They differ **after** the work is done.

**GLLA (409.0 s → 956.0 s, 547 s of overhead)**
1. `complete_goal` at 408.7 s → **deterministic pre-audit gate rejected** with `deterministic-pre-audit` because the stored verification contract was not mechanically executable (213.6 s spent reconciling this, ending in a human decision at 622.3 s: *"The stored verification contract cannot be executed by GLLA's mechanical pre-audit…"*, answered with the replacement contract).
2. Second `complete_goal` at 676.0 s → detached Node auditor worker → separate `pi --mode rpc` session → **277.1 s**, 2 rounds, 14.9 KB report → approved at ≈954 s.
3. Settlement 1.1 s after approval; `extension_state_terminal`.

Useful defect detection: **no code defect was found by the auditor**; the only rejection came from a bookkeeping gate and cost a human decision. That is real overhead without a measurable correctness gain in this trial.

**pi-goal-x (323.0 s → 598.9 s, 276 s of overhead)**
1. `update_goal {status: complete}` at 323.0 s → `completion_requested` 332.0 s → in-process auditor session → **249.1 s**, one round → `approved` at 581.0 s → `goal_completed` + `goal_archived` in the same tick.
2. Settlement 17.9 s after approval. Zero retries, zero rejections, zero human interventions.

`post_verification_delay` (final settlement − last code write): **GLLA 400.4 s**, **pi-goal-x 296.8 s**. In both cases the delay is dominated by the audit itself, not by repeated re-checking after acceptance.

---

## 5. C. Goal comprehension analysis

**What GLLA understood.** Its proposal was the most technically precise of the two: three SVG writers, nine dynamic text paths, the exact failing command, and a contract whose items were individually checkable. It correctly refused to add requirements that were not in the task (observed in the pilot smoke, where it argued that operator-added criteria did not exist in the task file). It asked one scripted clarification round and then two confirmations, one of which was an internal inconsistency of its own machinery (contract vs. pre-audit), not a task ambiguity.

**What pi-goal-x understood.** It reproduced the task's ten requirements and constraints verbatim as the goal objective, derived a task list (inventory → escape → tests → docs → validate), and confirmed once. It asked nothing beyond the auditor choice. Requirement coverage of the confirmed contract: **12/12** (GLLA 11/12).

**Questions asked and answers given (identical scripted policy for both).**

| | GLLA | pi-goal-x |
|---|---|---|
| Clarification rounds answered with the shared script | 1 | 0 |
| Confirmations granted | 3 (`Yes`, replacement contract, `Tweak goal?`) | 2 (auditor **enable**, confirm draft) |
| Approvals that materially changed the task | none | none |
| Human decisions that were strictly necessary | 1 (contract replacement) | 0 |

Neither extension narrowed, expanded or silently reinterpreted the shared task. The confirmation gate did its job in both.

---

## 6. D. Quality versus efficiency

| Derived metric | GLLA | pi-goal-x |
|---|---:|---:|
| Quality points per minute | 5.96 | 9.21 |
| Cost per verified completion (nominal) | $0.219 | $0.082 |
| Audit overhead as % of total elapsed | 29.0 % (277 s) | 41.6 % (249 s) |
| Time to first completion claim → verified acceptance | 547 s | 276 s |
| Redundant verification after acceptance | 1.1 s | 17.9 s |

Caveats: GLLA's numbers include 20 retried model requests caused by a relay defect (now fixed); pi-goal-x's single audit is shorter but had no failures to recover from, so its resilience is untested. Both runs had a sample size of one.

---

## 7. E. Verdict

1. **Better objective understanding:** GLLA, narrowly. It found and reproduced the actual vulnerability and enumerated every insertion path; pi-goal-x reproduced the contract faithfully but with less investigation.
2. **Better implementation:** tie on acceptance; GLLA by a point on defensive detail (invalid XML code points, attribute quoting via `quoteattr`). pi-goal-x's is smaller and equally correct for the stated requirements.
3. **More meaningful defects detected:** **neither auditor found a code defect.** GLLA's only rejection was its deterministic pre-audit rejecting its own contract format. No audit-driven repair improved correctness in this trial.
4. **Faster:** pi-goal-x (598.9 s vs 956.0 s), despite GLLA's infrastructure handicap this difference is larger than the retries can explain — GLLA spent 213 s on contract bookkeeping before its audit even started.
5. **Less redundant completion checking:** pi-goal-x. GLLA's post-claim window is 547 s, of which 214 s produced no verification activity at all.
6. **Fewer tokens / lower cost:** pi-goal-x, by a wide margin (≈1.7× fewer input, 3.3× fewer output tokens, 2.7× lower nominal cost).
7. **Best trade-off for autonomous coding:** **pi-goal-x** — same verified outcome at 63 % of the wall clock and 37 % of the cost.
8. **Preferred when completion correctness matters most:** **GLLA**, but only conditionally. Its contract format is stricter and its auditor is a genuinely independent process with a real evidence report, at the price of more human decisions and more wall time. Neither auditor demonstrated defect-finding in this run.
9. **Confidence:** **low (n = 1).** The direction of the efficiency result is consistent across every independent measure (time, tokens, requests, overhead), which makes it credible; the quality difference (95 vs 92) is inside noise. Do not treat the ranking as established.

---

## 8. F. Reliability and completion-lifecycle results (S0)

| Reliability metric | GLLA | pi-goal-x |
|---|---|---|
| Time to independently verified work | *not captured in-run* (see note) | *not captured in-run* (see note) |
| Time to supervisor settlement | 956.0 s | 598.9 s |
| Post-verification delay (settlement − last code write) | 400.4 s | 296.8 s |
| Longest auditor inactivity | 30.6 s (between audit turns) | 22.0 s |
| Audit timeouts / aborts | 0 / 0 | 0 / 0 |
| Automatic recovery success | yes (20 upstream resets, no operator retry) | not exercised (0 failures) |
| Redundant audit attempts | 0 (1 deterministic gate + 1 model audit) | 0 |
| Tokens spent after externally correct work | ≈90 k (audit session) | ≈29 k (whole run) |
| Manual interventions | 1 (contract replacement decision) | 0 |
| Misleading progress states | none observed | none observed |
| Final persisted goal state | `complete`, archived | `complete`, archived |
| **Reliability score /100** | **82** | **90** |

Note on `time_to_work_verified`: during both runs the external verifier used a frozen suite that contained **two evaluator-authoring defects** (an incorrect "no `&amp;amp;` anywhere in the file" rule, and a CLI test that used a build name absent from the dataset). The verifier therefore never reported a pass during either run. Both candidates were re-evaluated **after** the harness bugs were fixed, with the corrected suite applied identically; both passed 10/10 frozen and 6/6 adversarial. The per-sample timestamps are preserved in `results/*-s0-runmeta.json`, and this is reported as an instrumentation failure, not as a competitor failure.

**Forensic evidence for the audits (nothing hung):**

* GLLA: `audit-jobs/audit-mvwejgwu-…/progress.json` — `phase: complete`, `round: 2`, `elapsedMs: 277149`, 29,031-byte prompt, 14,947-byte report, worker pid recorded, exit clean. Verdict history: `2026-10-31T12:48:56.195Z disapproved (deterministic-pre-audit)` → `2026-10-31T12:58:01.060Z approved`.
* pi-goal-x: `goal_events.jsonl` — `completion_requested` 13:03:52.753Z → `audit_started` 13:03:52.754Z → `audit_result approved` 13:08:01.897Z → `goal_completed` and `goal_archived` 13:08:01.909Z. No `AbortController` cancellation, no provider error, no subprocess (the auditor is an in-process nested session).

Classification per the benchmark's vocabulary: both `NORMAL_VERIFIED_COMPLETION`.

---

## 9. G. Forensic record of failures observed

| Event | GLLA | pi-goal-x |
|---|---|---|
| Failed model requests | 20 of 87 (`stream_read`, `ConnectionResetError` from the local proxy) | 0 of 23 |
| Cancellation reason | upstream proxy reset during streaming | — |
| Effect | silent provider retries inside Pi; no operator action; no lost work | — |
| Root cause found | benchmark relay sent `Connection: close` upstream and forwarded synchronously, so a slow consumer stalled the upstream socket; fixed by decoupling the reader and removing the forced close | — |
| Leftover processes after settlement | none | none |
| Goal state after settlement | `complete` + archived | `complete` + archived |

Distinguishing the pi-goal-x failure classes the brief asks for: no user-triggered interruption, no `AbortController` cancellation, no provider/model error, no auditor subprocess (so no subprocess failure), no missing verdict, and no deadlock were observed. The one non-clean event in the whole trial was GLLA's dependency failure on `node` in the discarded first attempt (harness defect, corrected for both).

---

## 10. H. Final decision

1. **Less likely to appear stuck after useful work:** pi-goal-x (17.9 s from approved to archived; no bookkeeping detour).
2. **Handles an auditor crash more reliably:** **untested.** GLLA has more machinery for it (detached worker, job directory, retry schedule, 900 s backoff, orphan handling) and its process boundary is observable; pi-goal-x's auditor is in-process, so an auditor crash is a crash of the session itself. Neither was fault-injected, so no claim is made.
3. **Wastes fewer tokens on redundant completion verification:** pi-goal-x.
4. **Recovers without manual intervention:** GLLA demonstrated recovery from 20 transient provider failures with no operator action; pi-goal-x was not stressed. Undecided on evidence, slight edge to GLLA for having been tested by accident.
5. **Does extra auditing measurably improve correctness?** **Not in this trial.** Both passed every independent test; GLLA's extra 277 s audit produced a report but found no defect the tests would have caught, and its one rejection was a contract-format gate.
6. **Better for unattended autonomous coding:** **pi-goal-x** (fewest human decisions, fastest settlement, lowest cost, verified outcome).

**Separate awards**

| Award | Winner | Basis |
|---|---|---|
| Best implementation quality | GLLA (marginal) | 35 vs 34; invalid-char handling, `quoteattr`, full insertion-site coverage |
| Fastest verified completion | pi-goal-x | 598.9 s vs 956.0 s |
| Best completion reliability | pi-goal-x | 90 vs 82; 0 manual interventions, clean settle |
| Best unattended autonomy | pi-goal-x | same verified outcome at 63 % of wall clock and 37 % of cost |

**No overall winner is declared.** Quality is within noise (95 vs 92, n=1); the efficiency difference is consistent and large, but GLLA's run carried a disclosed infrastructure handicap and neither extension's auditor demonstrated defect-finding on this task.

---

## 11. Reproducibility

```text
results/
  benchmark-config.json          pins: Pi-Bolt SHA/release/hash, both extension SHAs+versions, model, images, limits
  shared-task.md / .sha256       the exact task bytes and hash
  glla-events.jsonl              full RPC + relay + harness event stream, monotonic timestamps
  goal-x-events.jsonl
  glla-metrics.json              derived timings, tokens, counters, audit facts, classification
  goal-x-metrics.json
  glla.patch / goal-x.patch      canonical diffs from the pinned baseline
  independent-evaluation.json    anonymized (C1/C2) independent test results, scope and contract coverage
  glla-s0-frozen-tests.log       raw evaluator output
  goal-x-s0-frozen-tests.log
  glla-s0-runmeta.json           external verifier samples, wall clock, warm-up
  goal-x-s0-runmeta.json
  comparison.csv                 the table in §3
  FINAL_REPORT.md                this report
competitors/<name>/
  logs/        runner events, relay log, final state, stderr, UI dialogue (ui-script.json), samples
  sessions/    Pi session transcripts (authoritative token usage)
  agent-config/ models.json + settings.json actually used
  extensions/  the pinned extension package as installed
  workspace/   the modified tree (no .git) for forensics
```

Re-run:

```bash
export DOCKER_HOST=unix://$HOME/.colima/default/docker.sock
harness/setup_instance.sh glla    competitors/_glla-src
harness/setup_instance.sh goal-x  competitors/_goalx-src
python3 harness/run_trial.py --trial s0 --order glla,goal-x --max-seconds 2700
python3 harness/collect.py glla s0 && python3 harness/collect.py goal-x s0
python3 harness/evaluate.py s0 && python3 harness/timeline.py && python3 harness/summarize.py s0
```

To exercise a fault scenario, write `/logs/control.json` in that competitor's relay volume:

```json
{"mode":"abort","match":"audit"}       // one controlled auditor interruption
{"mode":"fail","match":"audit"}        // transient 503 on audit calls
{"mode":"slow","delay_ms":45000,"match":"audit"}
{"mode":"normal"}                      // restore
```

---

## 12. Integrity of protected originals

| Original | Evidence |
|---|---|
| Pi-Bolt baseline checkout `baseline/pi-bolt` | `git status --porcelain` empty; HEAD `fd4530c9611f0cffc18aa226c985fcc2603d2577` (branch `pi-bolt`) at the end of the trial |
| Extension sources `competitors/_glla-src`, `_goalx-src` | untouched clones; HEADs `b1c36dc…` (0.39.54) and `b0fc15e…` (0.34.1) |
| Existing Pi installation `~/.pi` | never mounted, copied or referenced; every container used `/home/agent/.pi/agent` inside its own volume |
| Local model server `127.0.0.1:9091` | read-only use; not restarted or reconfigured; only `/v1/models` and `/v1/chat/completions` were called |
| Git remotes / pushes | none: remotes removed in every worker copy; no push, PR or deploy was performed |

---

## 13. Disclosed limitations

1. **n = 1 per competitor.** No repetition, no order swapping.
2. **Infrastructure asymmetry:** GLLA's run suffered 20 upstream resets (relay defect, fixed before pi-goal-x). This inflates GLLA's time and token counts; the implementation-phase durations are nevertheless nearly identical (298.8 s vs 290.1 s).
3. **Evaluator defects found post-run** (two frozen assertions, one adversarial assertion) were fixed and both candidates re-graded with the corrected suite; the in-run external verifier therefore has no valid `time_to_work_verified` samples.
4. **Audit-request counting by prompt marker** was over-broad (drafting prompts mention the auditor); audit counts in this report come from the extensions' own persisted audit records, not from the marker.
5. **Cost is nominal**, computed from list prices; the proxy reported $0 (allowance billing).
6. **Fault scenarios S1–S4 untested.** Reliability conclusions are therefore about normal completion and one real transient-failure episode, not about injected auditor failures.
7. **Shared model for implementation and audit.** Both extensions used `deepseek-v4.1-flash` for both roles (only one model was configured, deliberately, so neither side could be advantaged by a stronger auditor).
