# ClarifyReview

A pull request reviewer that detects when a diff's intent is ambiguous and asks the
author a targeted question **before** generating review comments, instead of
guessing in a single pass.

BCSE497J Project I — Yashika Gupta (23BCE0225), Pratyaksh Gupta (23BCE0316).
Guide: Prof. Arivoli A.

---

## Status

| | |
|---|---|
| **Built and tested** | All four pipeline stages · four detector designs · Gemini and Anthropic backends · GitHub bot · experiment log · full Study A harness · verified-mutant pipeline · Study B page · labelling, judge-agreement and oracle-audit tooling · uncertainty-threshold sweep · paper generator · 130 offline tests |
| **Run** | Pilot (v1 manipulation, Sept 2026) · v2 ablation on SWE-bench Verified with execution-verified mutants · detector comparison |
| **Needs people** | The 300-PR labelling pass (two annotators) · human validation of the LLM judge · the Study B developer sessions |

Every number in the paper is produced by `paper/collect.py` from the experiment
databases; nothing is typed in by hand.

---

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
```

Get a free Gemini key at <https://aistudio.google.com/apikey>, then:

```bash
cp .env.example .env    # fill in GEMINI_API_KEY
```

Check what your key can actually reach before running anything expensive:

```bash
clarifyreview models
```

Optional extras: `.[bench]` for SWE-bench loading, `.[embed]` for better detector-(a)
embeddings, `.[polyglot]` for non-Python tree-sitter grammars.

### Providers

Gemini is the default; Anthropic still works. Nothing above `llm/` knows which is
active — detectors, pipeline and experiment harness call only `LLM.structured()`
and `LLM.text()`, so switching provider changes no research code:

```bash
CLARIFYREVIEW_PROVIDER=anthropic clarifyreview models
```

Two differences matter:

**Sampling.** Gemini accepts `temperature` on every model, so detector (a1) runs
on the *same* model that writes the reviews. That is a better instrument than the
Anthropic path allows, where `temperature` is rejected on Opus 5 / Sonnet 5 and
the sampler has to drop to a weaker tier — there, dispersion partly reflects the
weaker model rather than the reviewer.

**Model availability moves.** The defaults were chosen by probing a real free-tier
key, not from documentation: the entire `gemini-2.5-*` family is closed to new keys
(it still appears in `models.list()`, but returns 404 on use), and the pro tier
exhausts its free quota immediately. Run `clarifyreview models` and probe before
trusting any default. Never put a `-latest` alias in `MODELS` — the review model
must stay fixed for the whole ablation, and an alias can change under a running
study; a test asserts this.

**Cost.** The free Gemini tier bills nothing, so `PRICING` lists Gemini models at
zero. That is correct for a free key and wrong for a paid one: put the published
rates in `config.PRICING` before quoting any cost figure in the paper, because
`experiments/analyze.py` reads straight from that table.

## Try it without an API key

Stages 1 and 2 are entirely offline. This is the worked example from the proposal:

```bash
clarifyreview detect --diff examples/ambiguous.diff --commit-msg "fix" --features
```

```
decision : ASK
score    : 0.889  (threshold 0.50)
why      : rules fired: deletion_heavy, generic_commit_msg, no_linked_issue,
           no_test_alongside, public_api_touched, removes_guard, sensitive_code
```

A well-described PR with a test alongside it scores 0.296 and gets `PROCEED`. That
selectivity is the thing being evaluated — a detector that asks on every PR is as
useless as one that never asks.

## Commands

```bash
clarifyreview ingest  --repo owner/name --pr 42     # stage 1: the assembled context
clarifyreview detect  --repo owner/name --pr 42     # stage 2: ask or proceed
clarifyreview review  --repo owner/name --pr 42     # all four stages
clarifyreview serve                                  # the webhook receiver
```

Every command also accepts `--diff <file>` in place of `--repo/--pr`, so the whole
pipeline runs against a local diff with no GitHub access.

---

## Architecture

```
Stage 1  Ingestion        diff → hunks → changed symbols (stdlib ast) → context
Stage 2  Ambiguity        ask / proceed + score          ← the research component
Stage 3  Clarification    ≤2 targeted questions, then wait (or time out)
Stage 4  Review           structured findings + confidence + suggested fix
```

Three design decisions are load-bearing and worth knowing before reading the code:

**The plain reviewer is not a separate code path.** It is `NeverAskDetector`
plugged into the same `Pipeline`. If the baseline had its own function, the
ablation would compare two programs rather than one program with one stage
switched off. `tests/test_pipeline.py::test_conditions_differ_only_in_stage_2_and_3`
asserts this.

**Stage 3 is abstracted behind a `Responder`.** `GitHubResponder` posts a comment
and waits for a human; `OracleResponder` calls the bounded simulated developer in
Study A. Swapping them is the entire difference between production and the
benchmark, which is why the prototype and the experiment measure the same system.

**Reviews are structured data until the last step.** `ReviewOutput` is enforced at
the API boundary — `response_schema` on Gemini, `output_format` on Anthropic — and
`render.py` turns it into markdown only when a human needs to read it. Study A
scores findings mechanically.

### The three detectors

| | Design | Model (Gemini) | Inference cost |
|---|---|---|---|
| (c) `heuristic` | Hand-set rules over 15 features | none | free |
| (b) `classifier` | Logistic regression / GBT over the same features | none | free |
| (a1) `sampling` | N=8 intent hypotheses at temperature 1.0, dispersion + semantic entropy | `gemini-3.6-flash` | 8 calls |
| (a2) `perturbation` | Same, but K prompt framings at fixed settings | `gemini-3.6-flash` | 8 calls |

Detector (a) has two variants for a reason that is provider-specific. On Anthropic,
**`temperature` is rejected with a 400 on Opus 5, Sonnet 5 and the whole 4.6+
family**, so (a1) has to drop to `claude-haiku-4-5` — the one current tier that
still accepts sampling parameters — and (a2) exists as the workaround that keeps
the review model fixed and perturbs the prompt instead.
`AnthropicBackend._params` raises rather than silently dropping a temperature,
because a sampling detector that is secretly deterministic would produce a
meaningless dispersion score.

On Gemini that constraint does not apply: (a1) samples the review model directly,
which makes it the better instrument. (a2) remains worth running as a comparison —
prompt sensitivity and decoder noise are different things, and which one better
predicts genuine ambiguity is an open question the ablation can answer.

Both embed one-sentence *intent hypotheses* rather than whole reviews.

Embedding a full review measures prose style; embedding a single claim about intent
measures intent.

---

## Study A: the ablation

Two patch variants × three conditions, over SWE-bench Verified:

| | full context, plain | stripped, plain | stripped, ClarifyReview |
|---|---|---|---|
| **golden** (correct patch) | false-alarm ceiling | false-alarm floor | H1: asking cuts false alarms |
| **mutant** (injected defect) | detection ceiling | detection floor | H2: asking recovers detections |

Three things about this design are deliberate:

**Golden patches alone are half a confusion matrix.** A SWE-bench golden patch is
the accepted fix, so every defect reported on one is a false alarm and there are no
true positives to be precise about. `experiments/mutate.py` injects defects into the
golden patch and keeps only mutants that fail the repository's own `FAIL_TO_PASS`
tests, making "there is a bug here" execution-verified rather than a judgement call.

**Stripping touches intent and nothing else.** The floor and treatment conditions
see byte-identical diffs; `run_matrix` asserts this per instance and aborts rather
than producing an incomparable result.

**The oracle is deliberately ignorant.** It sees the withheld issue text and commit
message — never the diff, never the mutation, never whether a defect exists. Its
prompt forbids volunteering. Every exchange is logged verbatim and
`oracle.audit_sample` pulls a sample for the hand-check the paper reports. An oracle
that can see the code will helpfully point at the bug, and the result becomes
leakage rather than an effect.

```bash
python -m experiments.build_dataset --limit 100 --verify --checkouts data/checkouts
python -m experiments.run_matrix --instances data/instances.jsonl --dry-run   # free
python -m experiments.run_matrix --instances data/instances.jsonl --detector heuristic
python -m experiments.judge --db data/clarifyreview.db
python -m experiments.analyze --db data/clarifyreview.db
```

Always dry-run first. It validates the stripping and the diffs across the whole set
in seconds, and catches a leak that would otherwise surface after $50 of API calls.

### Statistics

- **Primary**: McNemar's exact test on the paired binary outcome (floor vs.
  treatment). The outcomes are paired per instance and binary, so a t-test would be
  wrong twice over.
- **Headline number**: gap recovery, `(treatment − floor) / (ceiling − floor)`, with
  a bootstrap CI. A value above 1.0 is suspicious rather than excellent — the most
  likely explanation is oracle leakage, not a system that beats full context.
- **Detector comparison**: precision, recall, F1 and **ask-rate**. Plot precision
  against ask-rate; a detector that asks on 90% of PRs is useless at any accuracy.
- **Study B**: Wilcoxon signed-rank plus matched-pairs rank-biserial effect size.
  At n≈15 the p-value alone says very little.

Thresholds are frozen on a dev split by `experiments/train_classifier.py
--sweep-thresholds` and committed to `data/thresholds.json`. Nothing tunes against
the ablation set; a detector still on `DEFAULT_THRESHOLDS` is identifiable in the
log as such.

---

## Layout

```
src/clarifyreview/
  types.py        PRContext, Decision, ReviewOutput — the shared data model
  pipeline.py     the four stages, wired; the three experimental conditions
  ingest/         diff parsing, ast symbol extraction, context budgeting
  detect/         features + the three detector designs
  clarify/        question generation, the ask/wait/timeout loop
  review/         structured generation, markdown rendering
  llm/            the one place this project talks to the API
  store/          the experiment log (plain sqlite3 — the schema is the method)
  gh/             REST client, webhook receiver
experiments/      dataset, mutation, stripping, oracle, runner, judge, statistics
tests/            101 tests, no API key required
```

## Tests

```bash
.venv/bin/python -m pytest -q
```

All 101 run offline against stub SDK clients — no key, no network. The ones worth reading first are
`test_pipeline.py` (the conditions differ in exactly one thing),
`test_experiments.py` (stripping preserves the diff; mutants are valid diffs;
McNemar and gap recovery behave), and `test_llm_policy.py` (the temperature rule
that would otherwise surface as a 400 mid-run).

---

## The full workflow

Each step writes its output where the next step reads it. Steps marked *(API)*
spend provider quota; everything else is free.

```bash
# 1. Verified defects: golden must pass FAIL_TO_PASS, mutant must fail it
python -m experiments.verify_mutants --repo sympy/sympy --limit 75

# 2. The v2 study set: verified-mutant pairs plus difficulty-selected golden patches
python -m experiments.build_study_set --golden 12 --mutants 12

# 3. Validate the manipulation (free), then run the ablation (API, resumable)
python -m experiments.run_matrix --instances data/instances.v2.jsonl --dry-run
python -m experiments.run_matrix --instances data/instances.v2.jsonl \
    --db data/study_v2.db --strip-level prose --resume

# 4. Score with an independent judge, then analyse (API, then free)
python -m experiments.judge --db data/study_v2.db
python -m experiments.analyze --db data/study_v2.db

# 5. Compare detectors on constructed labels (heuristic free; uncertainty API)
python -m experiments.compare_detectors --detectors heuristic sampling perturbation

# 6. The paper, from the results
python -m paper.collect && node paper/build_paper.js
```

### Steps that need people

```bash
# Label 300 PRs (both of you, independently), then compute kappa and train detector (b)
python -m experiments.label_tool sheet --n 300
python -m experiments.label_tool agree runs/labelling_sheet.csv \
    --a annotator_1 --b annotator_2 --to-jsonl data/labelled_prs.jsonl
python -m experiments.train_classifier --labels data/labelled_prs.jsonl --sweep-thresholds

# Validate the judge against your own scoring
python -m experiments.judge --db data/study_v2.db --sample-for-humans 60
python -m experiments.label_tool agree runs/judge_validation_sample.csv \
    --a human_intent_recovered --b judge_intent_recovered

# Study B: build the page, send it out, merge what comes back, analyse
python -m study.build_study --db data/study_v2.db --n 16
python -m study.merge_responses responses/*.csv --out runs/study_b.csv
python -m experiments.analyze --study-b runs/study_b.csv
```

### Free-tier limits (measured 19 October 2026)

Google does not publish per-model free-tier limits; these were found by hitting them.

| Model | Finding |
|---|---|
| `gemini-3.6-flash` | 20 requests per day |
| `gemini-3.5-flash` | charged to `gemini-3.6-flash`'s quota — not a separate allowance |
| `gemini-3.7-flash`, `gemini-3.1-flash-lite` | persistently 503 (overloaded) |
| `gemini-3.5-flash-lite` | served as itself; used as the v2 reviewer |
| `gemma-4-31b-it` | served as itself; supports JSON schema but rejects any thinking config |

Every run records the model the provider says actually served it, so "one
reviewer for every condition" is verified rather than assumed.
