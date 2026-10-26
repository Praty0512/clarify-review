# Labelling real pull requests

The study's labelling sheet (`runs/labelling_sheet.csv`) is SWE-bench Verified shown
code-only: no description, no issue. That trains the classifier on what the detector
sees in the study. This document covers the other sheet: **real merged PRs from repos
you choose**, shown the way a reviewer sees a PR when it is opened (title,
description, linked issue, commit messages, diff), in Python, JavaScript, TypeScript,
Java, C, C++ and Rust. The two sheets are kept apart on purpose; nothing here touches
`runs/labelling_sheet.csv`, `runs/labelling/` or the study's model and thresholds.

## 1. Pick repos

Good repos are active, have human authors, merge PRs of 5-400 changed lines and have
PR descriptions of varying quality (a corpus where every PR is perfectly described has
no 1s to learn from). Aim for roughly 10 repos x 30 PRs. Put them in a file, one
`owner/name` per line (`#` comments allowed):

```
# repos.txt
pallets/flask
psf/requests
expressjs/express
vitejs/vite
google/gson
BurntSushi/ripgrep
curl/curl
nlohmann/json
```

Avoid repos whose PRs are mostly generated (dependency bumps, release bots).

## 2. Get a token

Create a fine-grained personal access token at GitHub > Settings > Developer settings.
Public repositories only, read-only: *Contents: read*, *Pull requests: read*,
*Metadata: read*. Put it in `.env` yourself:

```
GITHUB_TOKEN=github_pat_...
```

The tool never prints or stores it. Without a token it exits with a message.

## 3. Fetch the sheet

```
.venv\Scripts\python.exe -m experiments.fetch_prs --repos-file repos.txt ^
    --merged-since 2025-01-01 --merged-until 2026-06-30 ^
    --min-lines 5 --max-lines 400 --max-files 15 --per-repo 30 --n 300 ^
    --languages python javascript typescript java c cpp rust ^
    --exclude-authors dependabot renovate ^
    --exclude data/instances.v2.jsonl data/archive/instances.pilot.jsonl ^
    --seed 20261026 --cache-dir data/cache/realpr ^
    --out runs/realpr/labelling_sheet.csv
```

What it does, in stages, so expensive calls only happen for survivors:

1. **Search.** One `/search/issues` query per month window (the API caps a query at
   1000 results; a busier window is split in halves). Paced to 30 searches a minute.
2. **Metadata.** Candidates are taken in seeded random order; for each, the PR and its
   file list are fetched and filtered until `--per-repo` pass. Filters: bots (type
   `Bot`, `[bot]` suffix, or `--exclude-authors`), size, file count, language (the
   majority of changed non-test lines, by file extension), docs-only, and PRs already
   used by the study (SWE-bench ids such as `psf__requests-1234` map to
   `psf/requests#1234`). A summary of why PRs were rejected is printed.
3. **Full context**, only for the sampled PRs: the diff, commit messages and the linked
   issue (GraphQL `closingIssuesReferences`, falling back to "fixes #N" in the body;
   a link to another PR is ignored).

Everything is cached in `data/cache/realpr/<owner>__<name>/` (`search_*`, `meta_N`,
`full_N`; `data/cache/` is git-ignored). Re-running the same command makes zero API
calls. If you hit a rate limit it stops, says so, and a later identical run resumes
from the cache. Budget: about 2 calls per candidate looked at plus about 4 per sampled
PR, so 300 PRs is a few thousand calls, inside the 5000/hour authenticated limit.

Add more repos later without disturbing labels: `--append` only adds rows, never
reorders or edits existing ones. Without `--append`, the tool refuses to overwrite a
sheet that already holds any annotator, adjudicated or notes value.

Columns: `pr_id` (`owner/name#N`), `repo`, `number`, `url`, `view`, `title`, `body`,
`body_edited`, `issue_number`, `issue_title`, `issue_body`, `commit_messages` (JSON
list), `code_change` (raw diff, 30000 chars max), `diff_truncated`, `additions`,
`deletions`, `changed_files`, `languages`, `merged_at`, `annotator_1`, `annotator_2`,
`adjudicated`, `notes`.

## 4. Label

Same flow as the SWE-bench sheet, same tool; the codebook and the page switch
automatically because the sheet has a `view` column.

```
.venv\Scripts\python.exe -m experiments.label_tool split runs/realpr/labelling_sheet.csv --out-dir runs/realpr/labelling
.venv\Scripts\python.exe -m experiments.label_tool page --out-dir runs/realpr/labelling
```

Give each annotator their own `annotator_N.html` (or `.csv`). The page shows title,
description, linked issue and commit messages above the diff, all as plain text.
Progress is saved in the browser under `cr_label_full_N` (the code-only pages use
`cr_label_N`, so they never collide). Annotators must not open the PR on GitHub: the
review discussion there is exactly the clarification the bot is meant to replace.
Combine the returned files and adjudicate disagreements in the sheet, as for the
SWE-bench sheet (`label_tool combine`, `label_tool agree`).

## 5. Finish

```
.venv\Scripts\python.exe -m experiments.finish --labelling-set realpr --status
.venv\Scripts\python.exe -m experiments.finish --labelling-set realpr
```

`--labelling-set realpr` reads `runs/realpr/labelling_sheet.csv` and
`runs/realpr/labelling/`, takes diffs from the cache, and writes:

| output | path |
|---|---|
| labelled set | `data/labelled_prs.realpr.jsonl` |
| agreement | `runs/realpr/labelling_agreement.json` |
| classifier | `data/models/ambiguity_clf.realpr.joblib` |
| thresholds | `data/thresholds.realpr.json` |

The judge, Study B and paper steps are skipped. The default (`swebench`) behaviour of
`finish` is unchanged and the study's `ambiguity_clf.joblib` / `thresholds.json` are
never written by the real-PR run.

## 6. Use it in the bot

The classifier detector reads two settings (`src/clarifyreview/config.py`), set in
`.env` or the environment:

```
CLASSIFIER_PATH=data/models/ambiguity_clf.realpr.joblib
THRESHOLDS_PATH=data/thresholds.realpr.json
CLARIFYREVIEW_DETECTOR=classifier
```

Leave them unset to keep the study's frozen model and thresholds.

## Risks to keep in mind

- **Never merge full-context and code-only labels.** They answer different questions.
  Each row carries its `view`; `split` refuses a sheet that mixes views.
- **Merged-PR leakage.** The description you see is the final one. `body_edited` is 1
  when the author edited it after opening, so some of what annotators read may have been
  added in response to review. `--snapshot opened` (experimental) rebuilds the diff
  as of about an hour after the PR was opened using `/compare`; those rows get the view
  `full_context_opened`, which is also never merged with the others. The description
  text cannot be rewound.
- **Rate limits.** Search is 30 per minute; the core API is 5000 per hour.
- **Selection.** Repos you pick determine what "unclear" looks like; report them.
