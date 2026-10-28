# Automated Code-Evaluation Platform with Self-Healing CI/CD

> **Clean-room re-implementation: read this first.** This repository
> was built from scratch to demonstrate the *concepts* in a resume
> bullet (an LLM code-evaluation platform, an auto-detecting input
> dispatcher, CI failure recovery, Docker slimming, and test
> filtering). It is **not** the original production code, it does not
> reproduce any production system, and it makes no claim about any
> company's metrics, team, or incidents. Every claim in this README
> is only what this repository's own tests prove, and the test counts
> below are the counts this repo actually achieves.


Separately, CI failures are not all alike, so this project does not
treat them alike: a small classifier names six failure modes *defined
by this repository*, a bounded healer retries only known modes
within a persisted per-run budget, and unknown failures are left
visibly unretried instead of being retried into silence. Around both
pieces sit the honest engineering habits: a slim container, and
function-level test filtering that never replaces the full suite.

## Architecture

```mermaid
flowchart LR
    Sub[Submission\n(any shape)] --> Disp[Dispatcher\n detect + normalise]
    Disp --> Eval[Evaluator\n subprocess + timeout]
    Eval --> Result[Structured result\n pass/fail/timeout/error]
    CI[Failed CI run] --> Class[Classifier\n 6 repo-defined modes]
    Class --> Heal[Healer\n budget + audit JSONL]
    Heal --> GH[GitHub API\n rerun failed jobs]
    Diff[Changed functions] --> Filter[Test filter\n mapped targets]
    Filter --> Note[Fast feedback only\n full suite still runs in CI]
```

## How to run

Requirements: Python 3.12, standard library only, nothing to install.

```bash
# Full test suite (70 tests, see below)
python3 -m unittest discover -s tests -v

# Dispatcher + evaluator demo, one file per input shape (9/9 pass)
python3 examples/run_demo.py

# Evaluator demo in a REPL-style snippet
python3 - << 'EOF'
from evaluator.dispatcher import dispatch
outcomes = dispatch("two-sum", '{"inputs": [[2, 7, 11, 15], 9], "expected": [0, 1]}')
print([(o.passed, o.actual) for o in outcomes])  # [(True, [0, 1])]
EOF

# Healer dry-run demo (no GitHub calls, no budget consumed).
# Exit code 2 is intentional here: the demo file contains one UNKNOWN
# failure, and the healer stops visibly on it instead of succeeding.
python3 -m ci_healer.cli --repo owner/repo --run-id 42 --dry-run \
    --jobs-file examples/healer_demo_jobs.json \
    --state /tmp/healer-demo-state.json --audit /tmp/healer-demo-audit.jsonl

# Test filtering demo (fast local feedback only)
python3 scripts/select_tests.py --changed evaluator/dispatcher.py:dispatch
python3 scripts/select_tests.py --full   # full suite, always available
```

The dispatcher itself is 344 lines (`wc -l evaluator/dispatcher.py`),
inside its 320-345 target. It supports JSON object, JSON list,
JSONL, CSV, `key=value` pairs, and plain lines, in that precedence
order. In every shape, `input` means one argument and `inputs` means
a list of arguments; supplying both is ambiguous and rejected.

## The six failure modes (defined by this repository)

These are this repo's own design, checked by `tests/test_healer.py`.
They are not any company's failure modes.

| Mode | Detection signals (this repo) | Bounded recovery action |
|---|---|---|
| Runner disk quota / no space left | `No space left on device`, `disk quota exceeded`, `ENOSPC` | Prune Docker images/caches, then rerun failed jobs |
| Transient dependency-install network failure | `Temporary failure in name resolution`, `Could not fetch`, `Failed to fetch` | Rerun failed jobs (no code change) |
| Docker pull rate-limit / timeout | `toomanyrequests`, rate-limit on pull, pull timeout | Wait for backoff, then rerun failed jobs |
| Runner lost communication | `Lost communication with the server`, or job conclusion `cancelled` | Rerun failed jobs on a fresh runner |
| Cache corruption / restore failure | `Cache restore failed`, cache checksum mismatch | Clear the cache key, then rerun failed jobs |
| Dependent-service startup timeout | `Timed out waiting for service … to be ready`, health-check timeout | Increase service startup wait, then rerun failed jobs |

Anything else classifies as `UNKNOWN`, is never retried, is written
to the audit JSONL, and makes the CLI exit 2. Retry budget: at most
2 attempts per (run, signature) by default, configurable with
`--max-retries`, persisted in a JSON state file so rerunning the
healer does not reset it. Original logs are never deleted or
overwritten; the healer only reads them and writes its own state and
audit files.

## Docker slimming

The `Dockerfile` is a slim multi-stage `python:3.12-slim` image:
slim base in both stages, no pip installs at all (stdlib only, so no
pip cache exists to clean), only app source copied into the runtime
stage (`.dockerignore` excludes tests, `.git`, caches, and healer
state), and a non-root `appuser` at runtime. See
`docs/docker-slimming.md` for the fat-vs-slim comparison.

**Honest measurement caveat:** Docker is not installed in the
environment where this repository was built, so no image was built
and no size was measured here. `scripts/measure_image.py` says so
and exits cleanly instead of inventing a number. Run
`docker build -t code-evaluation-platform .` followed by
`python3 scripts/measure_image.py code-evaluation-platform` on a
machine with Docker to get a real measurement. This repo therefore
claims slimming *techniques*, not a measured gigabyte saving.

## Function-level test filtering: guardrail

`ci_healer/test_filter.py` and `scripts/select_tests.py` map changed
function names to test files via an explicit mapping plus name
matching against available test files. Two guardrails are built in:

1. An unknown changed function falls back to the **full suite**,
   never to an empty or silently reduced run.
2. Filtering is for fast local feedback only. The full suite still
   runs in CI (`.github/workflows/ci.yml` runs every test), and
   `--full` always selects everything.

## Security notes

- **Untrusted code needs real sandboxing.** A subprocess with a
  timeout is not a sandbox: code run through `evaluator.py` can
  still read files or use the network. This local runner is for
  trusted demo/test code only; production use needs a locked-down
  container with no network, a read-only filesystem, and resource
  limits.
- **Tokens are never logged or hardcoded.** The GitHub client reads
  `GITHUB_TOKEN` from the environment only, logs only method/path/
  status, and dry-run mode makes no mutating HTTP calls at all.
- **Unknown failures stay visible.** They are never retried, never
  deleted, and they fail the healer run loudly (exit 2).

## What this repo proves / does not prove

Proves (all checked by the test suite, run locally with
`python3 -m unittest discover -s tests -v`):

- **70 tests pass, 0 fail**: 36 in `tests/test_dispatcher.py`
  (every shape, precedence, ambiguity, and malformed case), 11 in
  `tests/test_evaluator.py` (reference solutions with independent
  expectations, timeout, exception capture, structured results),
  15 in `tests/test_healer.py` (all six modes, unknown never
  retried, budget persisted, dry-run side-effect-free, rate-limit
  backoff), and 8 in `tests/test_filter.py`.
- The dispatcher demo passes 9/9 cases across all six input shapes.
- The healer dry-run demo classifies, budgets, and audits exactly
  as documented, and stops visibly on the unknown failure.

Does **not** prove:

- Any production behaviour, incident, team process, or measured
  saving. None of those are in this repository, by design.
- Docker image sizes: Docker was absent here, so nothing was built
  or measured locally (see the caveat above).
- Live GitHub API behaviour: the client is tested with stubbed
  HTTP, not against the real API, and the demo uses a local jobs
  file. Live calls need `GITHUB_TOKEN` and a real run id.

## Layout

```text
evaluator/
  dispatcher.py          # auto-detecting dispatcher (344 lines)
  reference_solutions.py # two-sum, sorted squares, fibonacci, valid parentheses
  evaluator.py           # callable + subprocess candidate runner
ci_healer/
  classifier.py          # the six repo-defined failure modes
  github_client.py       # urllib GitHub API wrapper (env token, dry-run, backoff)
  healer.py / cli.py     # budget, state, audit JSONL, CLI
  test_filter.py         # function-level test selection
scripts/
  select_tests.py        # runnable test-filter CLI
  measure_image.py       # Docker size measurement (skips gracefully if absent)
examples/                # one demo submission per input shape + run_demo.py
tests/                   # unittest suites (no pytest needed)
.github/workflows/ci.yml # unittest + docker build on push/PR
docs/docker-slimming.md  # fat-vs-slim notes + measurement instructions
```
