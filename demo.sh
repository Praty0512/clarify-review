#!/usr/bin/env bash
# ClarifyReview — the demo, in the order it makes sense to a reviewer.
#
#   ./demo.sh          Stages 1 and 2 live, Stages 3 and 4 replayed from the
#                      study log. No API key, no network, no cost.
#   ./demo.sh --full   Adds Stages 3 and 4. Needs GEMINI_API_KEY.
set -u
CR="${CR:-.venv/bin/clarifyreview}"
FULL=0; [ "${1:-}" = "--full" ] && FULL=1

hr()  { printf '\n\033[1;34m%s\033[0m\n' "── $* ──────────────────────────────────────"; }
say() { printf '\033[2m%s\033[0m\n' "$*"; }
cmd() { printf '\033[1;33m$ %s\033[0m\n\n' "$*"; eval "$*"; }

hr "1. The problem: an ambiguous pull request"
say "A null check disappears. Commit message: \"fix\". No linked issue."
say "A single-pass reviewer must guess what this change was for."
printf '\n'; cat examples/ambiguous.diff

hr "2. Stage 1 — what the system understands about the diff"
say "Not 'lines 10-15 changed', but which SYMBOL changed. Note the stable"
say "fingerprint: ingestion is deterministic, which the ablation depends on."
cmd "$CR ingest --diff examples/ambiguous.diff --title 'fix login bug' --commit-msg 'fix' 2>&1 | head -20"

hr "3. Stage 2 — the contribution: ask, or proceed?"
cmd "$CR detect --diff examples/ambiguous.diff --commit-msg 'fix' --features"

hr "4. The other half: knowing when to stay quiet"
say "Same detector, a well-described PR with a regression test in the same diff."
say "A tool that asks on every PR is unusable, so this case matters as much."
printf '\n'; cat examples/clear.diff
cmd "$CR detect --diff examples/clear.diff --commit-msg 'Trim surrounding whitespace before slugifying so pasted CMS titles do not produce trailing dashes'"

if [ "$FULL" = "1" ]; then
  hr "5. Stages 3 and 4 — the full pipeline"
  say "Generates a clarifying question, then reviews. Needs GEMINI_API_KEY."
  cmd "$CR review --diff examples/ambiguous.diff --pr-id demo"
else
  hr "5. Stages 3 and 4 — a recorded run from the study, replayed offline"
  say "The same pull request reviewed three ways. Without its issue text the"
  say "reviewer misreads it; ClarifyReview asks, gets an answer, and matches the"
  say "full-context review. ('./demo.sh --full' runs Stages 3-4 live instead.)"
  cmd "$CR replay --db data/study_v2.db"
fi

hr "6. The evidence underneath"
cmd ".venv/bin/python -m pytest -q 2>&1 | tail -3"
printf '\n'
