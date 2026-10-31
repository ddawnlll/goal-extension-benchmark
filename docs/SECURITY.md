# Security and publication policy

This repository is a record of a benchmark. It is not a service, and it holds no
credentials. This document describes what is deliberately absent, how the
published artifacts were scrubbed, and how to re-check that.

## Not published

| Artifact | Why |
|---|---|
| `harness/.secrets/local_api_key` | the credential used to reach the model endpoint during the runs |
| `harness/runtime/` | the Pi-Bolt release binary (246 MB); pinned by release name and SHA-256 in `reports/` and `results/replication-config.json` |
| `competitors/_glla-src/`, `competitors/_goalx-src/` | the two extensions' source trees; pinned by commit and not redistributed |
| `competitors/*/workspace/` | the ~1.5 GB of per-run working trees; every change is reproduced exactly by the patches in `results/` |
| Docker images, volumes, networks | recreated by `harness/fetch_inputs.sh` and `harness/run_trial.py` |

## Scrubbing applied to the published records

- Absolute host paths were replaced with `$BENCH_ROOT` (the checkout) and `$HOME`.
- The operator's user name does not appear anywhere in the tree.
- Container-internal paths (`/home/agent/...`) are kept: they are part of the
  measured environment and contain no personal information.
- Logs are gzip-compressed but otherwise complete: the JSONL records are the
  same records the runs produced, with the same counts.
- The model endpoint credential was only ever held by the relay container; it is
  not present in any request or event record, because request headers were never
  logged.

## Verifying the published tree

```bash
python3 tools/check_publish.py
```

The script scans every tracked file (including gzip-compressed logs) for:

- the credential pattern used by the benchmark's relay,
- literal `/Users/` paths and the operator's name,
- `.secrets` references or files,
- common token shapes (`sk-...`, `ghp_...`, `AKIA...`) that are *not* inside the
  synthetic test fixtures of the upstream Pi-Bolt test suite.

It exits non-zero on any finding. The only permitted token-shaped strings are the
upstream fixtures `ghp_abcdefghij...` and `sk-ant-api03-abcdefgh...`, which are
listed explicitly in the script.

## Residual risk

- Event and session logs contain model output, tool output and file content from
  the public Pi-Bolt repository. They can include text that looks like code or
  configuration; none of it is a live credential.
- The benchmark container runs third-party code as a non-root user inside a
  disposable container. Nothing here implies the benchmarked extensions, or the
  model endpoint, are safe to run in production.

## Reporting

Open an issue for anything that looks like a leaked secret or personal datum. If
a credential is involved, do not paste it into the issue: describe the location
only, and it will be removed and the history rewritten if necessary.
