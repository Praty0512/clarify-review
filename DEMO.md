# ClarifyReview: presenter notes

## Before you start

- [ ] Run from the project folder (the one containing `demo.ps1` and `demo.sh`).
- [ ] Windows, recommended live:
  `powershell -ExecutionPolicy Bypass -File .\demo.ps1 -Step`
  (pauses between sections; press Enter to advance)
- [ ] macOS/Linux: `./demo.sh --step`
- [ ] Offline by default: no API key, no network, no cost.
- [ ] `-Full` / `--full` runs stages 3-4 live with `GEMINI_API_KEY`. Free tier is about 20 requests/day and each live call takes roughly 10-40 s. Do not rely on it live. Without a key it falls back to replay.
- [ ] Do one dry run before presenting.
- [ ] Make the terminal font large.
- [ ] No venv yet? See "If something goes wrong."

## Walkthrough

### 1. The problem: an ambiguous pull request

**On screen:** the diff `examples/ambiguous.diff`. A null check (`if user.email is None: raise ...`) is removed from `validate_user`. Commit message is `fix`. No linked issue.

- A single-pass reviewer has to guess why the check was removed.
- Frame the question: should the tool ask the author, or just review?

### 2. Stage 1: what the system understands about the diff

**On screen:** `app/auth.py:10 function validate_user(user) [modified]` with stable fingerprint `38455c2a565b86bd`.

- It reports which symbol changed, not "lines 10-15 changed".
- The fingerprint is stable: ingestion is deterministic, and the ablation depends on that.

### 3. Stage 2: ask, or proceed?

**On screen:** `decision : ASK`, `score 0.889 (threshold 0.50)`. Rules fired: `deletion_heavy`, `generic_commit_msg`, `no_linked_issue`, `no_test_alongside`, `public_api_touched`, `removes_guard`, `sensitive_code`.

- Each rule is a visible, named reason, not a black-box verdict.
- The score is compared against a fixed threshold of 0.50.

### 4. The other half: knowing when to stay quiet

**On screen:** `examples/clear.diff` (a `slugify` change with a regression test in the same diff), then `decision : PROCEED`, `score 0.296`. Only `no_linked_issue` and `public_api_touched` fired.

- Selectivity is the point. A tool that asks on every PR is useless.
- Contrast the two results side by side: same detector, very different outcome.

### 5. Replay of sympy__sympy-12481 (accepted fix)

**On screen:** three review modes on the same PR.

- **FLOOR** (intent withheld, single pass): misread the intent as "tidy up ... removing duplicate checking". Judge: intent recovered = no.
- **TREATMENT**: `ASK 0.556`. Asked one targeted question at `permutations.py:900`. The simulated developer answered "allow non-disjoint cycles ... left-to-right order". Review then recovered intent = yes.
- **CEILING** (full context): intent recovered = yes.
- Point: asking recovered what the stripped context lost.
- This is one case where it worked. Do not present it as the average (see section 3 below).

### 6. The evidence underneath

**On screen:** `168 passed`, from the offline test suite.

- Runs with no key and no network.
- Tests cover the pipeline, so the demo is not the only check.

## If asked about results

Be direct. Use the v2 SWE-bench Verified ablation: 36 instances (24 correct fixes, 12 with execution-verified injected bugs), 108 runs.

- Intent recovered: floor 80.6%, ClarifyReview 83.3%, ceiling 97.2%.
- Gap recovery 0.17 (95% CI 0 to 0.5).
- McNemar p = 1.0. **Not statistically significant.**
- The heuristic detector asked on only 5.6% of runs, so the treatment rarely differed from the plain reviewer. This is the main limitation, along with the small sample (24 of 36 instances from sympy).
- The replay in section 5 is a case where it worked, not the average.
- Next steps:
  - Two-annotator labelling of 300 PRs to tune thresholds.
  - More verified mutants (32 verified, 12 used).
  - Human validation of the LLM judge.

## If something goes wrong

- **"No such file" / setup hint:** create the venv.
  `py -3.11 -m venv .venv`
  `.venv\Scripts\pip install -e ".[dev]"`
- **Garbled box characters:** use Windows Terminal. If it still looks off, it is cosmetic.
- **Scripts disabled:** use the `-ExecutionPolicy Bypass` form shown above.
- **Live mode slow or out of quota:** rerun without `-Full`.
