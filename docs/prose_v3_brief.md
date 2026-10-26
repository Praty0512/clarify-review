# Prose brief for docs/prose_v3.json

You write **only** `docs/prose_v3.json`: one string per placeholder id, nothing else.
The builders (`paper/build_paper.js`, `docs/build_report.py`, `docs/build_deck.py`) fail
if any placeholder is empty. Check your work with `python docs/prose_tool.py check`.

## How numbers work

* Never type a digit. Every number comes from a token written `{key.path:fmt}`, which
  the builders replace from `paper/numbers.json`. The lint rejects any digit outside a
  token, except in labels such as `Table III`, `Fig. 6`, `Figure 7.4`, `Section V-G`,
  `Section 7.9`, `Chapter 7`.
* Use only the tokens listed under each id (the lint checks this). The list shows the
  value each token has today, so you can write sentences that are true.
* Formats: `pct` (0.6667 -> 67%), `f2` (two decimals), `int`, `k` (thousands separator),
  `word` (7 -> seven, 0 to 20), `ci` ([a, b] -> "a to b", two decimals), none for text.
  A float needs a format. `gap_points` and similar `derived.*` values are integers.
* Braces in the "Framing notes" (for example {n_new_rows}) are shorthand for the tokens in the table below them.
* A token resolves only to a number or a name that exists in `numbers.json`; if you need a
  number that is not listed, say so rather than writing it.

## Honesty rules (from the plan)

1. A null result is reported **with a bound**: "not significant", never "trend toward".
2. AI judges give **AI-vs-AI agreement**, never "validation". Human validation of the
   judge has not been done; say so wherever the judge is discussed.
3. The v3 agent-judge choice was made **after seeing agreement** with the local judge: disclose
   it as a post hoc choice.
4. Every not-done item is stated as not done (human judge validation, real-PR labelling,
   live GitHub deployment, the 300-PR classifier training, Study B).
5. v2 and v3 are **never pooled**. v3 is a separate study with a different reviewer, a different
   question/oracle model and different rows.
6. "Gemini" names only the v2 reviewer (gemini-3.5-flash-lite) and the web-app judge. The v2 API
   judge is **gemma-4-31b-it**.
7. The bot has **not yet been run against live GitHub**; it was exercised end to end on a local
   server (offline tests).
8. Voice: IEEE, terse, British spelling (behaviour, analyse, recognise), no em dashes, no
   exclamation, no marketing. Match the existing text around each placeholder.

## Numbering of things you may refer to

Paper: Table I (v2 outcomes), II (detectors), III (v3 outcomes), IV (judge pairs); Fig. 3 (v2
results), 4 (funnel), 5 (detectors), 6 (v3 results), 7 (judge kappa heatmap); sections V-F
(local replication) and V-G (judge calibration); IV-F (v3 design).
Report: Table 7.4 (v3 outcomes), 7.5 (judge pairs); Figure 7.4 (v3 results), 7.5 (v3 funnel),
7.6 (judge kappa heatmap), 7.7 (G under each judge); Sections 7.8 (local replication), 7.9
(judge calibration), 7.10 (threats), 5.2.7 (v3 design), 5.1.5 (bot). Note: the plan numbered
the new sections 7.9 to 7.11; the builder numbers them contiguously (7.8 to 7.10) because 7.8
was the old threats section.
Deck: slide 14 is the new "Experiments and Results (3/3)" slide with Fig. v3 results and the
judge heatmap.

## Placeholders

Index: paper: 16; report: 23; deck: 5; total 44.


---

## Paper

### `paper.abstract.v3`

* **Appears in:** paper, Abstract (single block, after the v2 sentences, before "We release the system...")
* **Kind / target length:** 2-3 sentences; 45-65 words
* **Framing notes:** The v3 replication: reviewer {v3_setup.reviewer_model_name}, {n} instances, intent recovery floor / treatment / ceiling (pct), G with its 95% CI, p. State it as a null result with a bound. End with a sentence that re-scoring with a second judge preserved the verdict but not the magnitude (v2 G moved from the API judge's value to the agent judge's value). Do not pool v2 and v3.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{v3_setup.reviewer_model_name}` | qwen3:4b-instruct-2507-q4_K_M |
  | `{v3_local.complete_triples:int}` | 96 |
  | `{v3_local.tests.intent_all.floor:pct}` | 67% |
  | `{v3_local.tests.intent_all.treatment:pct}` | 70% |
  | `{v3_local.tests.intent_all.ceiling:pct}` | 100% |
  | `{v3_local.tests.intent_all.gap_recovery:f2}` | 0.09 |
  | `{v3_local.tests.intent_all.gap_ci:ci}` | -0.22 to 0.33 |
  | `{v3_local.tests.intent_all.mcnemar_p:f2}` | 0.66 |

### `paper.intro.contrib5`

* **Appears in:** paper, I. Introduction, contribution 5) (the list item text after "5) ")
* **Kind / target length:** one clause ending in a full stop; 25-40 words
* **Framing notes:** A judge-calibration analysis across three AI judges and a second-model replication. The list items 1-4 are fixed in code and read "1) ClarifyReview, a four-stage reviewer...;"; keep this item as a noun phrase of the same shape, ending with a full stop. Say it is AI-vs-AI, not human validation.
* **Allowed tokens:** none (no number may appear)

### `paper.sys.extraction`

* **Appears in:** paper, III. ClarifyReview, Stage 1 sentence
* **Kind / target length:** clause (no leading capital, no trailing full stop); 15-30 words
* **Replaces this existing text:** "with the Python abstract syntax tree"
* **Framing notes:** Replaces the clause "with the Python abstract syntax tree" in: "Stage 1 parses the diff and resolves changed lines to changed symbols <CLAUSE>, assembling a bounded context in a deterministic order and fingerprinting it." Say: Python through its AST; JavaScript, TypeScript/TSX, Java, C, C++ and Rust through tree-sitter grammars; Python behaviour byte-identical to before.
* **Allowed tokens:** none (no number may appear)

### `paper.sys.backends`

* **Appears in:** paper, III. ClarifyReview, closing paragraph (after the sentence ending "automated tests.")
* **Kind / target length:** 1-2 sentences; 25-40 words
* **Framing notes:** Three provider backends behind one interface: Gemini, Anthropic and local Ollama. The Ollama backend runs a model on the user's own machine with no network and no cost. Keep to what exists; do not claim the Anthropic backend was used in the studies.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{derived.tests_passed:int}` | 445 |
  | `{derived.tests_skipped:int}` | 1 |
  | `{test_files:int}` | 28 |

### `paper.sys.bot`

* **Appears in:** paper, III. ClarifyReview, closing paragraph (follows paper.sys.backends)
* **Kind / target length:** 1-2 sentences; 30-50 words
* **Framing notes:** Bot robustness: parked runs persist in SQLite across restarts, a timeout sweep, handling of rate limits, signed-webhook verification. Must state that it has been exercised end to end on a local server, NOT yet against live GitHub.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{derived.tests_passed:int}` | 445 |
  | `{derived.tests_skipped:int}` | 1 |
  | `{test_files:int}` | 28 |

### `paper.method.v3_design`

* **Appears in:** paper, IV-F. Second-model replication (v3) (heading is fixed in code)
* **Kind / target length:** one paragraph; 110-150 words
* **Framing notes:** Design of v3: {v3_design.rows} rows = the v2 set plus {n_new_rows} new rows; all {mutants_used} verified mutants (both arms) and golden-only rows from other repositories ({golden_only_repos} repos). Reviewer {reviewer_model_name} through Ollama, heuristic detector at tau = {threshold}, {runs_failed} failed runs, {wall_minutes} minutes on a laptop GPU. Question and oracle model {question_oracle_model} (not recorded per DB row; logged in the oracle log). Same conditions as v2. v3 is NEVER pooled with v2. Mention the judge is chosen in V-G, not here.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{v3_setup.reviewer_model_name}` | qwen3:4b-instruct-2507-q4_K_M |
  | `{v3_setup.reviewer_model}` | qwen3:4b-instruct-2507-q4_K_M@0edcdef34593 |
  | `{v3_setup.backend}` | ollama |
  | `{v3_setup.detector}` | heuristic |
  | `{v3_setup.threshold:f2}` | 0.50 |
  | `{v3_setup.runs:int}` | 288 |
  | `{v3_setup.runs_failed:int}` | 0 |
  | `{v3_setup.wall_minutes:int}` | 52 |
  | `{v3_setup.question_oracle_model}` | llama3.2:3b |
  | `{v3_setup.question_oracle.n_logged:int}` | 11 |
  | `{v3_design.rows:int}` | 96 |
  | `{v3_design.v2_rows:int}` | 36 |
  | `{v3_design.n_new_rows:int}` | 60 |
  | `{v3_design.mutants_used:int}` | 32 |
  | `{v3_design.mutants_verified_total:int}` | 32 |
  | `{v3_design.golden_only_rows:int}` | 32 |
  | `{v3_design.golden_only_repos:int}` | 7 |
  | `{mutants.attempted:int}` | 75 |
  | `{mutants.by_status.verified:int}` | 32 |

### `paper.results.v3_lead`

* **Appears in:** paper, V-F. Replication on a local reviewer, first paragraph (precedes Table III)
* **Kind / target length:** 2-3 sentences; 40-70 words
* **Framing notes:** Introduce Table III (same rows as Table I, but v3, scored by the Claude agent judge {v3_local.judge_label}). Say the judge choice is explained in Section V-G and was made after seeing agreement; v3 is reported separately from v2.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{v3_setup.reviewer_model_name}` | qwen3:4b-instruct-2507-q4_K_M |
  | `{v3_setup.reviewer_model}` | qwen3:4b-instruct-2507-q4_K_M@0edcdef34593 |
  | `{v3_setup.backend}` | ollama |
  | `{v3_local.tests.intent_all.n:int}` | 96 |
  | `{v3_local.judge_label}` | claude-sonnet-agent |
  | `{v3_local.judge_model}` | claude-sonnet-subagent |

### `paper.results.v3_effect`

* **Appears in:** paper, V-F. after Table III and Fig. 6
* **Kind / target length:** one paragraph; 100-150 words
* **Framing notes:** (a) A null result WITH A BOUND: G and its CI; the upper bound rules out clarification recovering more than about a third of the gap at this n (use the upper CI limit). Say 'not significant', never 'trend toward'. (b) Ceiling vs floor shows stripping costs {derived.v3_local.intent_all.gap_points} points of intent recovery, so the manipulation works. Mention n and p.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{v3_local.tests.intent_all.n:int}` | 96 |
  | `{v3_local.tests.intent_all.floor:pct}` | 67% |
  | `{v3_local.tests.intent_all.treatment:pct}` | 70% |
  | `{v3_local.tests.intent_all.ceiling:pct}` | 100% |
  | `{v3_local.tests.intent_all.gap_recovery:f2}` | 0.09 |
  | `{v3_local.tests.intent_all.gap_ci:ci}` | -0.22 to 0.33 |
  | `{v3_local.tests.intent_all.mcnemar_p:f2}` | 0.66 |
  | `{v3_local.tests.intent_all.discordant_treatment_better:int}` | 12 |
  | `{v3_local.tests.intent_all.discordant_floor_better:int}` | 9 |
  | `{derived.v3_local.intent_all.floor_k:int}` | 64 |
  | `{derived.v3_local.intent_all.treatment_k:int}` | 67 |
  | `{derived.v3_local.intent_all.ceiling_k:int}` | 96 |
  | `{derived.v3_local.intent_all.gap_points:int}` | 33 |
  | `{derived.v3_local.intent_all.treatment_points:int}` | 3 |
  | `{derived.v3_local.intent_all.discordant_total:int}` | 21 |
  | `{v3_local.complete_triples:int}` | 96 |
  | `{v3_local.runs_ok:int}` | 288 |
  | `{v3_local.judged:int}` | 288 |
  | `{v3_local.tests.intent_golden.n:int}` | 64 |
  | `{v3_local.tests.intent_golden.floor:pct}` | 69% |
  | `{v3_local.tests.intent_golden.treatment:pct}` | 69% |
  | `{v3_local.tests.intent_golden.ceiling:pct}` | 100% |
  | `{v3_local.tests.intent_golden.gap_recovery:f2}` | 0.00 |
  | `{v3_local.tests.intent_golden.mcnemar_p:f2}` | 1.00 |
  | `{v3_local.tests.intent_mutant.n:int}` | 32 |
  | `{v3_local.tests.intent_mutant.floor:pct}` | 63% |
  | `{v3_local.tests.intent_mutant.treatment:pct}` | 72% |
  | `{v3_local.tests.intent_mutant.ceiling:pct}` | 100% |
  | `{v3_local.tests.intent_mutant.gap_recovery:f2}` | 0.25 |
  | `{v3_local.tests.intent_mutant.mcnemar_p:f2}` | 0.51 |

### `paper.results.v3_funnel`

* **Appears in:** paper, V-F. second paragraph
* **Kind / target length:** one paragraph; 100-150 words
* **Framing notes:** (c) The detector asked on {treatment_asks} of {treatment_n} treatment reviews; the funnel floor_misses -> detector_asked -> author_answered -> treatment_recovered shows detector recall is the limit (same finding as v2). (d) Discordant pairs go BOTH ways: clarification helped on some instances and hurt on others (give both counts).
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{v3_local.funnel.floor_misses:int}` | 32 |
  | `{v3_local.funnel.ceiling_also_missed:int}` | 0 |
  | `{v3_local.funnel.detector_asked:int}` | 8 |
  | `{v3_local.funnel.author_answered:int}` | 7 |
  | `{v3_local.funnel.treatment_recovered:int}` | 3 |
  | `{v3_local.funnel.asked_total:int}` | 17 |
  | `{v3_local.funnel.answered_total:int}` | 15 |
  | `{v3_local.treatment_asks:int}` | 17 |
  | `{v3_local.treatment_n:int}` | 96 |
  | `{v3_local.treatment_answered:int}` | 17 |
  | `{derived.v3_asked_on_understood:int}` | 9 |
  | `{derived.v3_detector_missed:int}` | 24 |
  | `{v3_local.tests.intent_all.discordant_treatment_better:int}` | 12 |
  | `{v3_local.tests.intent_all.discordant_floor_better:int}` | 9 |

### `paper.results.v3_defects`

* **Appears in:** paper, V-F. third paragraph
* **Kind / target length:** one paragraph; 80-120 words
* **Framing notes:** (e) Defect detection is near the floor even with full context (give k of n for floor, treatment, ceiling): a 4B reviewer limits defect detection, as the larger v2 reviewer did. (f) False alarms over the golden rows (k of n for each condition); too few to separate conditions. No effect claim on defects.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{v3_local.tests.defect_mutant.n:int}` | 32 |
  | `{v3_local.tests.defect_mutant.floor:pct}` | 3% |
  | `{v3_local.tests.defect_mutant.treatment:pct}` | 6% |
  | `{v3_local.tests.defect_mutant.ceiling:pct}` | 9% |
  | `{v3_local.tests.defect_mutant.mcnemar_p:f2}` | 1.00 |
  | `{derived.v3_local.defect_mutant.floor_k:int}` | 1 |
  | `{derived.v3_local.defect_mutant.treatment_k:int}` | 2 |
  | `{derived.v3_local.defect_mutant.ceiling_k:int}` | 3 |
  | `{v3_local.tests.false_alarm_golden.n:int}` | 64 |
  | `{v3_local.tests.false_alarm_golden.floor:pct}` | 2% |
  | `{v3_local.tests.false_alarm_golden.treatment:pct}` | 5% |
  | `{v3_local.tests.false_alarm_golden.ceiling:pct}` | 5% |
  | `{v3_local.tests.false_alarm_golden.mcnemar_p:f2}` | 0.50 |
  | `{derived.v3_local.false_alarm_golden.floor_k:int}` | 1 |
  | `{derived.v3_local.false_alarm_golden.treatment_k:int}` | 3 |
  | `{derived.v3_local.false_alarm_golden.ceiling_k:int}` | 3 |
  | `{v3_setup.reviewer_model_name}` | qwen3:4b-instruct-2507-q4_K_M |

### `paper.results.judges_lead`

* **Appears in:** paper, V-G. Judge calibration, first paragraph (precedes Table IV)
* **Kind / target length:** 2-3 sentences; 50-80 words
* **Framing notes:** Three AI judges scored the v2 reviews: the API judge {judges.models.api_v2}, Claude Sonnet agents, and the Gemini web app on a stratified sample of {gemini_sample.n} runs (stratified by condition and variant). Table IV gives % agreement / kappa / n. All of this is AI-vs-AI agreement; none of it is validation against human scorers.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{judges.models.api_v2}` | gemma-4-31b-it |
  | `{judges.models.agent}` | claude-sonnet-subagent |
  | `{judges.models.gemini_web}` | Gemini 4 Argon (web app) |
  | `{judges.models.api_v3}` | llama3.2:3b |
  | `{judges.gemini_sample.n:int}` | 30 |
  | `{judges.v2_three_way_intent.all_agree:int}` | 25 |
  | `{judges.v2_three_way_intent.n:int}` | 30 |

### `paper.results.judges_v2`

* **Appears in:** paper, V-G. after Table IV and Fig. 7
* **Kind / target length:** one paragraph; 120-170 words
* **Framing notes:** v2: the API judge agrees with the agent judge near-perfectly on defects and false alarms, moderately/fairly on intent (give kappa and % for intent). Three-way intent agreement {all_agree} of {n}. Re-scoring v2 with the agent judge: intent floor/treatment/ceiling and G with CI and p; the verdict (not significant) holds, the size of G does not (compare with the API judge's G).
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{judges.v2_pairs.api_vs_agent.intent_recovered.kappa:f2}` | 0.40 |
  | `{judges.v2_pairs.api_vs_agent.intent_recovered.percent_agreement:pct}` | 89% |
  | `{judges.v2_pairs.api_vs_agent.intent_recovered.n:int}` | 108 |
  | `{judges.v2_pairs.api_vs_agent.intent_recovered.reading}` | fair |
  | `{judges.v2_pairs.api_vs_agent.defect_caught.kappa:f2}` | 0.88 |
  | `{judges.v2_pairs.api_vs_agent.defect_caught.percent_agreement:pct}` | 99% |
  | `{judges.v2_pairs.api_vs_agent.defect_caught.n:int}` | 108 |
  | `{judges.v2_pairs.api_vs_agent.defect_caught.reading}` | almost perfect |
  | `{judges.v2_pairs.api_vs_agent.false_alarm.kappa:f2}` | 1.00 |
  | `{judges.v2_pairs.api_vs_agent.false_alarm.percent_agreement:pct}` | 100% |
  | `{judges.v2_pairs.api_vs_agent.false_alarm.n:int}` | 108 |
  | `{judges.v2_pairs.api_vs_agent.false_alarm.reading}` | almost perfect |
  | `{judges.v2_pairs.gemini_vs_agent.intent_recovered.kappa:f2}` | 0.62 |
  | `{judges.v2_pairs.gemini_vs_agent.intent_recovered.percent_agreement:pct}` | 90% |
  | `{judges.v2_pairs.gemini_vs_agent.intent_recovered.n:int}` | 30 |
  | `{judges.v2_pairs.gemini_vs_agent.intent_recovered.reading}` | substantial |
  | `{judges.v2_pairs.gemini_vs_agent.defect_caught.kappa:f2}` | 1.00 |
  | `{judges.v2_pairs.gemini_vs_agent.defect_caught.percent_agreement:pct}` | 100% |
  | `{judges.v2_pairs.gemini_vs_agent.defect_caught.n:int}` | 30 |
  | `{judges.v2_pairs.gemini_vs_agent.defect_caught.reading}` | almost perfect |
  | `{judges.v2_pairs.gemini_vs_agent.false_alarm.kappa:f2}` | 1.00 |
  | `{judges.v2_pairs.gemini_vs_agent.false_alarm.percent_agreement:pct}` | 100% |
  | `{judges.v2_pairs.gemini_vs_agent.false_alarm.n:int}` | 30 |
  | `{judges.v2_pairs.gemini_vs_agent.false_alarm.reading}` | almost perfect |
  | `{judges.v2_pairs.gemini_vs_api.intent_recovered.kappa:f2}` | 0.52 |
  | `{judges.v2_pairs.gemini_vs_api.intent_recovered.percent_agreement:pct}` | 87% |
  | `{judges.v2_pairs.gemini_vs_api.intent_recovered.n:int}` | 30 |
  | `{judges.v2_pairs.gemini_vs_api.intent_recovered.reading}` | moderate |
  | `{judges.v2_pairs.gemini_vs_api.defect_caught.kappa:f2}` | 0.65 |
  | `{judges.v2_pairs.gemini_vs_api.defect_caught.percent_agreement:pct}` | 97% |
  | `{judges.v2_pairs.gemini_vs_api.defect_caught.n:int}` | 30 |
  | `{judges.v2_pairs.gemini_vs_api.defect_caught.reading}` | substantial |
  | `{judges.v2_pairs.gemini_vs_api.false_alarm.kappa:f2}` | 1.00 |
  | `{judges.v2_pairs.gemini_vs_api.false_alarm.percent_agreement:pct}` | 100% |
  | `{judges.v2_pairs.gemini_vs_api.false_alarm.n:int}` | 30 |
  | `{judges.v2_pairs.gemini_vs_api.false_alarm.reading}` | almost perfect |
  | `{judges.v2_three_way_intent.all_agree:int}` | 25 |
  | `{judges.v2_three_way_intent.n:int}` | 30 |
  | `{v2_agent_judge.tests.intent_all.n:int}` | 36 |
  | `{v2_agent_judge.tests.intent_all.floor:pct}` | 86% |
  | `{v2_agent_judge.tests.intent_all.treatment:pct}` | 92% |
  | `{v2_agent_judge.tests.intent_all.ceiling:pct}` | 100% |
  | `{v2_agent_judge.tests.intent_all.gap_recovery:f2}` | 0.40 |
  | `{v2_agent_judge.tests.intent_all.gap_ci:ci}` | -0.75 to 1.00 |
  | `{v2_agent_judge.tests.intent_all.mcnemar_p:f2}` | 0.63 |
  | `{v2_agent_judge.tests.intent_all.discordant_treatment_better:int}` | 3 |
  | `{v2_agent_judge.tests.intent_all.discordant_floor_better:int}` | 1 |
  | `{derived.v2_agent_judge.intent_all.floor_k:int}` | 31 |
  | `{derived.v2_agent_judge.intent_all.treatment_k:int}` | 33 |
  | `{derived.v2_agent_judge.intent_all.ceiling_k:int}` | 36 |
  | `{v2.tests.intent_all.n:int}` | 36 |
  | `{v2.tests.intent_all.floor:pct}` | 81% |
  | `{v2.tests.intent_all.treatment:pct}` | 83% |
  | `{v2.tests.intent_all.ceiling:pct}` | 97% |
  | `{v2.tests.intent_all.gap_recovery:f2}` | 0.17 |
  | `{v2.tests.intent_all.gap_ci:ci}` | 0.00 to 0.50 |
  | `{v2.tests.intent_all.mcnemar_p:f2}` | 1.00 |
  | `{v2.complete_triples:int}` | 36 |
  | `{v2.judged:int}` | 108 |

### `paper.results.judges_v3`

* **Appears in:** paper, V-G. last paragraph
* **Kind / target length:** one paragraph; 130-190 words
* **Framing notes:** v3: the local judge {judges.models.api_v3} is unusable (give kappa for each metric versus the agent); it never flagged a false alarm (total {false_alarm_total}) and wrote 'no defect was injected' on {k} of {n} mutant rows. So the Claude agent judge is primary for v3 -- chosen AFTER seeing the agreement: disclose that it is a post hoc choice. State that the llama judge's own intent result is reference only. Close: all AI-vs-AI; human validation not done.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{judges.v3_pairs.llama_vs_agent.intent_recovered.kappa:f2}` | 0.20 |
  | `{judges.v3_pairs.llama_vs_agent.intent_recovered.percent_agreement:pct}` | 68% |
  | `{judges.v3_pairs.llama_vs_agent.intent_recovered.n:int}` | 288 |
  | `{judges.v3_pairs.llama_vs_agent.intent_recovered.reading}` | fair |
  | `{judges.v3_pairs.llama_vs_agent.defect_caught.kappa:f2}` | 0.06 |
  | `{judges.v3_pairs.llama_vs_agent.defect_caught.percent_agreement:pct}` | 93% |
  | `{judges.v3_pairs.llama_vs_agent.defect_caught.n:int}` | 288 |
  | `{judges.v3_pairs.llama_vs_agent.defect_caught.reading}` | slight |
  | `{judges.v3_pairs.llama_vs_agent.false_alarm.kappa:f2}` | 0.00 |
  | `{judges.v3_pairs.llama_vs_agent.false_alarm.percent_agreement:pct}` | 98% |
  | `{judges.v3_pairs.llama_vs_agent.false_alarm.n:int}` | 288 |
  | `{judges.v3_pairs.llama_vs_agent.false_alarm.reading}` | slight |
  | `{v3_local_llama_judge.false_alarm_total:int}` | 0 |
  | `{v3_local_llama_judge.no_defect_claim_mutant.k:int}` | 54 |
  | `{v3_local_llama_judge.no_defect_claim_mutant.n:int}` | 96 |
  | `{derived.llama_no_defect_claim_pct:int}` | 56 |
  | `{v3_local_llama_judge.judge_model}` | llama3.2:3b |
  | `{v3_local_llama_judge.tests.intent_all.floor:pct}` | 58% |
  | `{v3_local_llama_judge.tests.intent_all.treatment:pct}` | 63% |
  | `{v3_local_llama_judge.tests.intent_all.ceiling:pct}` | 83% |
  | `{v3_local_llama_judge.tests.intent_all.gap_recovery:f2}` | 0.17 |
  | `{v3_local_llama_judge.tests.intent_all.gap_ci:ci}` | -0.31 to 0.52 |
  | `{v3_local_llama_judge.tests.intent_all.mcnemar_p:f2}` | 0.56 |
  | `{v3_local.judge_label}` | claude-sonnet-agent |
  | `{v3_local.judge_model}` | claude-sonnet-subagent |

### `paper.disc.replication`

* **Appears in:** paper, VI. Discussion, new final paragraph
* **Kind / target length:** one paragraph; 90-130 words
* **Framing notes:** Two reviewers and two judges give the same picture: no significant effect; recall-bound; defect detection limited by the reviewer; but the effect SIZE depends on which judge scores (v2: API judge G vs agent judge G). Keep it short and non-repetitive.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{v2.tests.intent_all.n:int}` | 36 |
  | `{v2.tests.intent_all.floor:pct}` | 81% |
  | `{v2.tests.intent_all.treatment:pct}` | 83% |
  | `{v2.tests.intent_all.ceiling:pct}` | 97% |
  | `{v2.tests.intent_all.gap_recovery:f2}` | 0.17 |
  | `{v2.tests.intent_all.gap_ci:ci}` | 0.00 to 0.50 |
  | `{v2.tests.intent_all.mcnemar_p:f2}` | 1.00 |
  | `{v2.complete_triples:int}` | 36 |
  | `{v2.judged:int}` | 108 |
  | `{v3_local.tests.intent_all.n:int}` | 96 |
  | `{v3_local.tests.intent_all.floor:pct}` | 67% |
  | `{v3_local.tests.intent_all.treatment:pct}` | 70% |
  | `{v3_local.tests.intent_all.ceiling:pct}` | 100% |
  | `{v3_local.tests.intent_all.gap_recovery:f2}` | 0.09 |
  | `{v3_local.tests.intent_all.gap_ci:ci}` | -0.22 to 0.33 |
  | `{v3_local.tests.intent_all.mcnemar_p:f2}` | 0.66 |
  | `{v3_local.tests.intent_all.discordant_treatment_better:int}` | 12 |
  | `{v3_local.tests.intent_all.discordant_floor_better:int}` | 9 |
  | `{v2_agent_judge.tests.intent_all.n:int}` | 36 |
  | `{v2_agent_judge.tests.intent_all.floor:pct}` | 86% |
  | `{v2_agent_judge.tests.intent_all.treatment:pct}` | 92% |
  | `{v2_agent_judge.tests.intent_all.ceiling:pct}` | 100% |
  | `{v2_agent_judge.tests.intent_all.gap_recovery:f2}` | 0.40 |
  | `{v2_agent_judge.tests.intent_all.gap_ci:ci}` | -0.75 to 1.00 |
  | `{v2_agent_judge.tests.intent_all.mcnemar_p:f2}` | 0.63 |

### `paper.threats.v3`

* **Appears in:** paper, VII. Threats to Validity, new paragraph after the first
* **Kind / target length:** one paragraph; 120-170 words
* **Framing notes:** Threats added by v3: samples are small in both studies; the v3 agent judge was chosen after seeing agreement with the local judge (post hoc); the v3 question/oracle model is small and its identity is not recorded per DB row (only in the oracle log); the {n_new_rows} new rows have no Gemini-reviewer run; the bot has not run against live GitHub. Each as a plain statement of limitation.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{v3_setup.reviewer_model_name}` | qwen3:4b-instruct-2507-q4_K_M |
  | `{v3_setup.reviewer_model}` | qwen3:4b-instruct-2507-q4_K_M@0edcdef34593 |
  | `{v3_design.n_new_rows:int}` | 60 |
  | `{v2.complete_triples:int}` | 36 |
  | `{v3_local.complete_triples:int}` | 96 |
  | `{v3_setup.question_oracle_model}` | llama3.2:3b |
  | `{realpr.n_prs:int}` | 356 |

### `paper.conclusion.v3`

* **Appears in:** paper, VIII. Conclusion, one sentence inserted before "Future work is ..."
* **Kind / target length:** 1-2 sentences; 35-60 words
* **Framing notes:** A second reviewer (a local 4B model) and a second judge reproduce the null result: G and its upper CI limit; effect size depends on the judge. No spin.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{v3_local.tests.intent_all.n:int}` | 96 |
  | `{v3_local.tests.intent_all.floor:pct}` | 67% |
  | `{v3_local.tests.intent_all.treatment:pct}` | 70% |
  | `{v3_local.tests.intent_all.ceiling:pct}` | 100% |
  | `{v3_local.tests.intent_all.gap_recovery:f2}` | 0.09 |
  | `{v3_local.tests.intent_all.gap_ci:ci}` | -0.22 to 0.33 |
  | `{v3_local.tests.intent_all.mcnemar_p:f2}` | 0.66 |


---

## Report

### `report.abstract.v3`

* **Appears in:** report, Abstract (final paragraph; the template caps the abstract at 500 words and one page and the existing text is already about 435 words)
* **Kind / target length:** one short paragraph; <= 60 (hard cap) words
* **Framing notes:** v3 replication on a local reviewer (null, G with CI), judge calibration across AI judges (effect size depends on the judge), multi-language support, Ollama backend, bot. List what is NOT done in a few words: human judge validation, real-PR labelling, live GitHub deployment. The total length is a hard constraint (one-page abstract); if it cannot fit in 60 words, say so rather than overrun.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{v3_setup.reviewer_model_name}` | qwen3:4b-instruct-2507-q4_K_M |
  | `{v3_local.tests.intent_all.floor:pct}` | 67% |
  | `{v3_local.tests.intent_all.treatment:pct}` | 70% |
  | `{v3_local.tests.intent_all.ceiling:pct}` | 100% |
  | `{v3_local.tests.intent_all.gap_recovery:f2}` | 0.09 |
  | `{v3_local.tests.intent_all.gap_ci:ci}` | -0.22 to 0.33 |

### `report.s1_3.scope`

* **Appears in:** report, 1.3 Scope of the Project, first paragraph
* **Kind / target length:** one paragraph; 80-120 words
* **Replaces this existing text:** "The project builds and evaluates a pull request reviewer that detects ambiguous intent and asks before commenting. The system targets Python repositories on GitHub, is delivered as a bot that responds to pull request webhooks, and is restricted to the four stages described in Chapter 4. Multi-language support, an editor extension and any interface beyond pull request comments are out of scope because none of them bears on the contribution."
* **Framing notes:** Replaces the stale text. Scope now: pull request reviewer that detects ambiguous intent and asks; Python plus JavaScript, TypeScript/TSX, Java, C, C++ and Rust (Python behaviour unchanged); GitHub bot responding to webhooks; the four stages of Chapter 4. Still out of scope: an editor extension and any interface beyond PR comments. Live deployment and human studies are pending, not out of scope.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{realpr.n_prs:int}` | 356 |

### `report.s1_3.eval_scope`

* **Appears in:** report, 1.3 Scope of the Project, last paragraph
* **Kind / target length:** one paragraph; 70-110 words
* **Replaces this existing text:** "The evaluation is scoped to what one student team can complete in a semester on free-tier model access: a two-by-three ablation over {v2 n} SWE-bench Verified instances with execution-verified defects, and the tooling for a paired developer study. A field deployment is not attempted, which is why the target technology readiness level is TRL 4."
* **Framing notes:** Evaluation scope: v2 (free-tier hosted models, {v2.complete_triples} instances) and v3 (local model through Ollama, {v3_design.rows} rows); the tooling for a paired developer study; a field deployment is not attempted, which is why the target is TRL 4.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{v2.complete_triples:int}` | 36 |
  | `{v3_design.rows:int}` | 96 |
  | `{v3_setup.reviewer_model_name}` | qwen3:4b-instruct-2507-q4_K_M |
  | `{v3_setup.wall_minutes:int}` | 52 |

### `report.s3_2_2.economic`

* **Appears in:** report, 3.2.2 Economic Feasibility
* **Kind / target length:** one paragraph; 90-130 words
* **Replaces this existing text:** "The only recurring cost is model usage. The whole study ran on the Google Gemini free tier at zero monetary cost (Section 7.7). The binding constraint is a per-day request quota applied per model, which the design accommodates by assigning roles to different models, committing results per instance, and resuming after a reset. No hardware, licence or dataset was purchased; all libraries are open source."
* **Framing notes:** v2 ran on the Google Gemini free tier at zero monetary cost (Section 7.7) with a per-day request quota as the binding constraint (roles split across models, commits per instance, resume). v3 ran locally through Ollama at zero cost in {wall_minutes} minutes on a laptop GPU. No hardware, licence or dataset was purchased; libraries are open source. Not 'the whole study ran on Gemini'.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{v3_setup.wall_minutes:int}` | 52 |
  | `{v3_setup.reviewer_model_name}` | qwen3:4b-instruct-2507-q4_K_M |
  | `{v3_setup.backend}` | ollama |
  | `{v2_tokens.input:k}` | 187,121 |
  | `{v2_tokens.output:k}` | 9,138 |

### `report.s5_1_1.extraction`

* **Appears in:** report, 5.1.1 Ingestion (sentence 2)
* **Kind / target length:** one sentence; 35-60 words
* **Replaces this existing text:** "The semantic layer parses the post-change file with the Python AST and maps each changed line to its enclosing function, method or class, recording whether the signature changed."
* **Framing notes:** Replaces: "The semantic layer parses the post-change file with the Python AST and maps each changed line to its enclosing function, method or class, recording whether the signature changed." Keep that content but add: JavaScript, TypeScript/TSX, Java, C, C++ and Rust via tree-sitter grammars; Python path unchanged.
* **Allowed tokens:** none (no number may appear)

### `report.s5_1_4.ollama`

* **Appears in:** report, 5.1.4 LLM provider layer, closing sentence(s)
* **Kind / target length:** 1-2 sentences; 25-45 words
* **Framing notes:** The Ollama backend: a local model over HTTP, recording the model name and digest that actually served each call; no key, no network, no cost.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{v3_setup.backend}` | ollama |
  | `{v3_setup.reviewer_model_name}` | qwen3:4b-instruct-2507-q4_K_M |

### `report.s5_1_5.bot`

* **Appears in:** report, 5.1.5 GitHub bot (new subsection; heading fixed in code)
* **Kind / target length:** one paragraph; 90-130 words
* **Framing notes:** Robustness of the live bot: parked runs stored durably so a restart resumes them, a timeout sweep that publishes an unanswered review, rate-limit handling, signed-webhook verification, duplicate-delivery handling. State it was exercised end to end on a local server (offline tests) and NOT yet against live GitHub.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{derived.tests_passed:int}` | 445 |
  | `{derived.tests_skipped:int}` | 1 |
  | `{test_files:int}` | 28 |

### `report.s5_2_5.calibration`

* **Appears in:** report, 5.2.5 Simulated author and judge, new paragraph after the existing one
* **Kind / target length:** one paragraph; 100-140 words
* **Framing notes:** Method of the judge-calibration analysis: the same context and instructions are given to the API judge, Claude Sonnet agent judges and (on a stratified sample) the Gemini web app, blind to condition; agreement as % and Cohen's kappa per metric; the study is re-analysed under each judge. It is AI-vs-AI. Say nothing about results here.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{judges.models.api_v2}` | gemma-4-31b-it |
  | `{judges.models.agent}` | claude-sonnet-subagent |
  | `{judges.models.gemini_web}` | Gemini 4 Argon (web app) |
  | `{judges.models.api_v3}` | llama3.2:3b |
  | `{judges.gemini_sample.n:int}` | 30 |

### `report.s5_2_7.v3_design`

* **Appears in:** report, 5.2.7 Replication on a local reviewer (v3) (new subsection; heading fixed in code)
* **Kind / target length:** one paragraph; 110-150 words
* **Framing notes:** Same content as paper.method.v3_design: rows (v2 set plus new rows), all verified mutants and golden-only rows from other repositories, local reviewer via Ollama, heuristic detector at tau {threshold}, failed runs, minutes, question/oracle model. Never pooled with v2.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{v3_setup.reviewer_model_name}` | qwen3:4b-instruct-2507-q4_K_M |
  | `{v3_setup.reviewer_model}` | qwen3:4b-instruct-2507-q4_K_M@0edcdef34593 |
  | `{v3_setup.backend}` | ollama |
  | `{v3_setup.detector}` | heuristic |
  | `{v3_setup.threshold:f2}` | 0.50 |
  | `{v3_setup.runs:int}` | 288 |
  | `{v3_setup.runs_failed:int}` | 0 |
  | `{v3_setup.wall_minutes:int}` | 52 |
  | `{v3_setup.question_oracle_model}` | llama3.2:3b |
  | `{v3_setup.question_oracle.n_logged:int}` | 11 |
  | `{v3_design.rows:int}` | 96 |
  | `{v3_design.v2_rows:int}` | 36 |
  | `{v3_design.n_new_rows:int}` | 60 |
  | `{v3_design.mutants_used:int}` | 32 |
  | `{v3_design.mutants_verified_total:int}` | 32 |
  | `{v3_design.golden_only_rows:int}` | 32 |
  | `{v3_design.golden_only_repos:int}` | 7 |
  | `{mutants.attempted:int}` | 75 |
  | `{mutants.by_status.verified:int}` | 32 |

### `report.s6_3.status`

* **Appears in:** report, 6.3 Deployment as a GitHub bot, closing paragraph
* **Kind / target length:** one paragraph; 60-90 words
* **Framing notes:** What has and has not been shown: the bot, parked-run store and webhook path pass offline end-to-end tests on a local server; it has NOT been run against live GitHub. Mention the Windows demo script alongside demo.sh.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{derived.tests_passed:int}` | 445 |
  | `{derived.tests_skipped:int}` | 1 |
  | `{test_files:int}` | 28 |

### `report.s7_8.setup`

* **Appears in:** report, 7.8 Replication on a Local Reviewer (v3), first paragraph (precedes Table 7.4)
* **Kind / target length:** one paragraph; 100-140 words
* **Framing notes:** Set-up in report voice: local reviewer {reviewer_model_name} through Ollama on a laptop GPU, {runs} reviews, {runs_failed} failed, {wall_minutes} minutes, no monetary cost; the same three conditions; scored by the Claude agent judge (chosen after seeing agreement; see Section 7.9). Table 7.4 follows. Never pooled with v2.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{v3_setup.reviewer_model_name}` | qwen3:4b-instruct-2507-q4_K_M |
  | `{v3_setup.reviewer_model}` | qwen3:4b-instruct-2507-q4_K_M@0edcdef34593 |
  | `{v3_setup.backend}` | ollama |
  | `{v3_setup.detector}` | heuristic |
  | `{v3_setup.threshold:f2}` | 0.50 |
  | `{v3_setup.runs:int}` | 288 |
  | `{v3_setup.runs_failed:int}` | 0 |
  | `{v3_setup.wall_minutes:int}` | 52 |
  | `{v3_setup.question_oracle_model}` | llama3.2:3b |
  | `{v3_setup.question_oracle.n_logged:int}` | 11 |
  | `{v3_design.rows:int}` | 96 |
  | `{v3_design.v2_rows:int}` | 36 |
  | `{v3_design.n_new_rows:int}` | 60 |
  | `{v3_design.mutants_used:int}` | 32 |
  | `{v3_design.mutants_verified_total:int}` | 32 |
  | `{v3_design.golden_only_rows:int}` | 32 |
  | `{v3_design.golden_only_repos:int}` | 7 |
  | `{mutants.attempted:int}` | 75 |
  | `{mutants.by_status.verified:int}` | 32 |
  | `{v3_local.judge_label}` | claude-sonnet-agent |
  | `{v3_local.judge_model}` | claude-sonnet-subagent |
  | `{v3_local.judged:int}` | 288 |

### `report.s7_8.effect`

* **Appears in:** report, 7.8 after Figure 7.4
* **Kind / target length:** one paragraph; 110-160 words
* **Framing notes:** Same finding as paper.results.v3_effect: null WITH A BOUND (G, CI, upper limit about a third), 'not significant', stripping costs {gap_points} points so the manipulation works. Refer to Figure 7.4 and Table 7.4.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{v3_local.tests.intent_all.n:int}` | 96 |
  | `{v3_local.tests.intent_all.floor:pct}` | 67% |
  | `{v3_local.tests.intent_all.treatment:pct}` | 70% |
  | `{v3_local.tests.intent_all.ceiling:pct}` | 100% |
  | `{v3_local.tests.intent_all.gap_recovery:f2}` | 0.09 |
  | `{v3_local.tests.intent_all.gap_ci:ci}` | -0.22 to 0.33 |
  | `{v3_local.tests.intent_all.mcnemar_p:f2}` | 0.66 |
  | `{v3_local.tests.intent_all.discordant_treatment_better:int}` | 12 |
  | `{v3_local.tests.intent_all.discordant_floor_better:int}` | 9 |
  | `{derived.v3_local.intent_all.floor_k:int}` | 64 |
  | `{derived.v3_local.intent_all.treatment_k:int}` | 67 |
  | `{derived.v3_local.intent_all.ceiling_k:int}` | 96 |
  | `{derived.v3_local.intent_all.gap_points:int}` | 33 |
  | `{derived.v3_local.intent_all.treatment_points:int}` | 3 |
  | `{derived.v3_local.intent_all.discordant_total:int}` | 21 |
  | `{v3_local.complete_triples:int}` | 96 |
  | `{v3_local.runs_ok:int}` | 288 |
  | `{v3_local.judged:int}` | 288 |
  | `{v3_local.tests.intent_golden.n:int}` | 64 |
  | `{v3_local.tests.intent_golden.floor:pct}` | 69% |
  | `{v3_local.tests.intent_golden.treatment:pct}` | 69% |
  | `{v3_local.tests.intent_golden.ceiling:pct}` | 100% |
  | `{v3_local.tests.intent_golden.gap_recovery:f2}` | 0.00 |
  | `{v3_local.tests.intent_golden.mcnemar_p:f2}` | 1.00 |
  | `{v3_local.tests.intent_mutant.n:int}` | 32 |
  | `{v3_local.tests.intent_mutant.floor:pct}` | 63% |
  | `{v3_local.tests.intent_mutant.treatment:pct}` | 72% |
  | `{v3_local.tests.intent_mutant.ceiling:pct}` | 100% |
  | `{v3_local.tests.intent_mutant.gap_recovery:f2}` | 0.25 |
  | `{v3_local.tests.intent_mutant.mcnemar_p:f2}` | 0.51 |

### `report.s7_8.funnel`

* **Appears in:** report, 7.8 after Figure 7.5
* **Kind / target length:** one paragraph; 100-150 words
* **Framing notes:** Same finding as paper.results.v3_funnel: detector asked on {treatment_asks} of {treatment_n} reviews; funnel floor_misses -> detector_asked -> author_answered -> treatment_recovered; recall is the limit; discordant pairs in both directions. Refer to Figure 7.5.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{v3_local.funnel.floor_misses:int}` | 32 |
  | `{v3_local.funnel.ceiling_also_missed:int}` | 0 |
  | `{v3_local.funnel.detector_asked:int}` | 8 |
  | `{v3_local.funnel.author_answered:int}` | 7 |
  | `{v3_local.funnel.treatment_recovered:int}` | 3 |
  | `{v3_local.funnel.asked_total:int}` | 17 |
  | `{v3_local.funnel.answered_total:int}` | 15 |
  | `{v3_local.treatment_asks:int}` | 17 |
  | `{v3_local.treatment_n:int}` | 96 |
  | `{v3_local.treatment_answered:int}` | 17 |
  | `{derived.v3_asked_on_understood:int}` | 9 |
  | `{derived.v3_detector_missed:int}` | 24 |
  | `{v3_local.tests.intent_all.discordant_treatment_better:int}` | 12 |
  | `{v3_local.tests.intent_all.discordant_floor_better:int}` | 9 |

### `report.s7_8.defects`

* **Appears in:** report, 7.8 final paragraph
* **Kind / target length:** one paragraph; 80-120 words
* **Framing notes:** Same as paper.results.v3_defects: defects near the floor even with full context; 4B reviewer limits detection; false alarms over the golden rows.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{v3_local.tests.defect_mutant.n:int}` | 32 |
  | `{v3_local.tests.defect_mutant.floor:pct}` | 3% |
  | `{v3_local.tests.defect_mutant.treatment:pct}` | 6% |
  | `{v3_local.tests.defect_mutant.ceiling:pct}` | 9% |
  | `{v3_local.tests.defect_mutant.mcnemar_p:f2}` | 1.00 |
  | `{derived.v3_local.defect_mutant.floor_k:int}` | 1 |
  | `{derived.v3_local.defect_mutant.treatment_k:int}` | 2 |
  | `{derived.v3_local.defect_mutant.ceiling_k:int}` | 3 |
  | `{v3_local.tests.false_alarm_golden.n:int}` | 64 |
  | `{v3_local.tests.false_alarm_golden.floor:pct}` | 2% |
  | `{v3_local.tests.false_alarm_golden.treatment:pct}` | 5% |
  | `{v3_local.tests.false_alarm_golden.ceiling:pct}` | 5% |
  | `{v3_local.tests.false_alarm_golden.mcnemar_p:f2}` | 0.50 |
  | `{derived.v3_local.false_alarm_golden.floor_k:int}` | 1 |
  | `{derived.v3_local.false_alarm_golden.treatment_k:int}` | 3 |
  | `{derived.v3_local.false_alarm_golden.ceiling_k:int}` | 3 |

### `report.s7_9.lead`

* **Appears in:** report, 7.9 Judge Calibration, first paragraph (precedes Table 7.5)
* **Kind / target length:** 2-3 sentences; 50-80 words
* **Framing notes:** Same content as paper.results.judges_lead. All AI-vs-AI; none is human validation.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{judges.models.api_v2}` | gemma-4-31b-it |
  | `{judges.models.agent}` | claude-sonnet-subagent |
  | `{judges.models.gemini_web}` | Gemini 4 Argon (web app) |
  | `{judges.models.api_v3}` | llama3.2:3b |
  | `{judges.gemini_sample.n:int}` | 30 |
  | `{judges.v2_three_way_intent.all_agree:int}` | 25 |
  | `{judges.v2_three_way_intent.n:int}` | 30 |

### `report.s7_9.v2`

* **Appears in:** report, 7.9 after Figure 7.6
* **Kind / target length:** one paragraph; 120-170 words
* **Framing notes:** Same content as paper.results.judges_v2.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{judges.v2_pairs.api_vs_agent.intent_recovered.kappa:f2}` | 0.40 |
  | `{judges.v2_pairs.api_vs_agent.intent_recovered.percent_agreement:pct}` | 89% |
  | `{judges.v2_pairs.api_vs_agent.intent_recovered.n:int}` | 108 |
  | `{judges.v2_pairs.api_vs_agent.intent_recovered.reading}` | fair |
  | `{judges.v2_pairs.api_vs_agent.defect_caught.kappa:f2}` | 0.88 |
  | `{judges.v2_pairs.api_vs_agent.defect_caught.percent_agreement:pct}` | 99% |
  | `{judges.v2_pairs.api_vs_agent.defect_caught.n:int}` | 108 |
  | `{judges.v2_pairs.api_vs_agent.defect_caught.reading}` | almost perfect |
  | `{judges.v2_pairs.api_vs_agent.false_alarm.kappa:f2}` | 1.00 |
  | `{judges.v2_pairs.api_vs_agent.false_alarm.percent_agreement:pct}` | 100% |
  | `{judges.v2_pairs.api_vs_agent.false_alarm.n:int}` | 108 |
  | `{judges.v2_pairs.api_vs_agent.false_alarm.reading}` | almost perfect |
  | `{judges.v2_pairs.gemini_vs_agent.intent_recovered.kappa:f2}` | 0.62 |
  | `{judges.v2_pairs.gemini_vs_agent.intent_recovered.percent_agreement:pct}` | 90% |
  | `{judges.v2_pairs.gemini_vs_agent.intent_recovered.n:int}` | 30 |
  | `{judges.v2_pairs.gemini_vs_agent.intent_recovered.reading}` | substantial |
  | `{judges.v2_pairs.gemini_vs_agent.defect_caught.kappa:f2}` | 1.00 |
  | `{judges.v2_pairs.gemini_vs_agent.defect_caught.percent_agreement:pct}` | 100% |
  | `{judges.v2_pairs.gemini_vs_agent.defect_caught.n:int}` | 30 |
  | `{judges.v2_pairs.gemini_vs_agent.defect_caught.reading}` | almost perfect |
  | `{judges.v2_pairs.gemini_vs_agent.false_alarm.kappa:f2}` | 1.00 |
  | `{judges.v2_pairs.gemini_vs_agent.false_alarm.percent_agreement:pct}` | 100% |
  | `{judges.v2_pairs.gemini_vs_agent.false_alarm.n:int}` | 30 |
  | `{judges.v2_pairs.gemini_vs_agent.false_alarm.reading}` | almost perfect |
  | `{judges.v2_pairs.gemini_vs_api.intent_recovered.kappa:f2}` | 0.52 |
  | `{judges.v2_pairs.gemini_vs_api.intent_recovered.percent_agreement:pct}` | 87% |
  | `{judges.v2_pairs.gemini_vs_api.intent_recovered.n:int}` | 30 |
  | `{judges.v2_pairs.gemini_vs_api.intent_recovered.reading}` | moderate |
  | `{judges.v2_pairs.gemini_vs_api.defect_caught.kappa:f2}` | 0.65 |
  | `{judges.v2_pairs.gemini_vs_api.defect_caught.percent_agreement:pct}` | 97% |
  | `{judges.v2_pairs.gemini_vs_api.defect_caught.n:int}` | 30 |
  | `{judges.v2_pairs.gemini_vs_api.defect_caught.reading}` | substantial |
  | `{judges.v2_pairs.gemini_vs_api.false_alarm.kappa:f2}` | 1.00 |
  | `{judges.v2_pairs.gemini_vs_api.false_alarm.percent_agreement:pct}` | 100% |
  | `{judges.v2_pairs.gemini_vs_api.false_alarm.n:int}` | 30 |
  | `{judges.v2_pairs.gemini_vs_api.false_alarm.reading}` | almost perfect |
  | `{judges.v2_three_way_intent.all_agree:int}` | 25 |
  | `{judges.v2_three_way_intent.n:int}` | 30 |
  | `{v2_agent_judge.tests.intent_all.n:int}` | 36 |
  | `{v2_agent_judge.tests.intent_all.floor:pct}` | 86% |
  | `{v2_agent_judge.tests.intent_all.treatment:pct}` | 92% |
  | `{v2_agent_judge.tests.intent_all.ceiling:pct}` | 100% |
  | `{v2_agent_judge.tests.intent_all.gap_recovery:f2}` | 0.40 |
  | `{v2_agent_judge.tests.intent_all.gap_ci:ci}` | -0.75 to 1.00 |
  | `{v2_agent_judge.tests.intent_all.mcnemar_p:f2}` | 0.63 |
  | `{v2_agent_judge.tests.intent_all.discordant_treatment_better:int}` | 3 |
  | `{v2_agent_judge.tests.intent_all.discordant_floor_better:int}` | 1 |
  | `{derived.v2_agent_judge.intent_all.floor_k:int}` | 31 |
  | `{derived.v2_agent_judge.intent_all.treatment_k:int}` | 33 |
  | `{derived.v2_agent_judge.intent_all.ceiling_k:int}` | 36 |
  | `{v2.tests.intent_all.n:int}` | 36 |
  | `{v2.tests.intent_all.floor:pct}` | 81% |
  | `{v2.tests.intent_all.treatment:pct}` | 83% |
  | `{v2.tests.intent_all.ceiling:pct}` | 97% |
  | `{v2.tests.intent_all.gap_recovery:f2}` | 0.17 |
  | `{v2.tests.intent_all.gap_ci:ci}` | 0.00 to 0.50 |
  | `{v2.tests.intent_all.mcnemar_p:f2}` | 1.00 |
  | `{v2.complete_triples:int}` | 36 |
  | `{v2.judged:int}` | 108 |

### `report.s7_9.v3`

* **Appears in:** report, 7.9 next paragraph
* **Kind / target length:** one paragraph; 130-190 words
* **Framing notes:** Same content as paper.results.judges_v3, including the post hoc disclosure.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{judges.v3_pairs.llama_vs_agent.intent_recovered.kappa:f2}` | 0.20 |
  | `{judges.v3_pairs.llama_vs_agent.intent_recovered.percent_agreement:pct}` | 68% |
  | `{judges.v3_pairs.llama_vs_agent.intent_recovered.n:int}` | 288 |
  | `{judges.v3_pairs.llama_vs_agent.intent_recovered.reading}` | fair |
  | `{judges.v3_pairs.llama_vs_agent.defect_caught.kappa:f2}` | 0.06 |
  | `{judges.v3_pairs.llama_vs_agent.defect_caught.percent_agreement:pct}` | 93% |
  | `{judges.v3_pairs.llama_vs_agent.defect_caught.n:int}` | 288 |
  | `{judges.v3_pairs.llama_vs_agent.defect_caught.reading}` | slight |
  | `{judges.v3_pairs.llama_vs_agent.false_alarm.kappa:f2}` | 0.00 |
  | `{judges.v3_pairs.llama_vs_agent.false_alarm.percent_agreement:pct}` | 98% |
  | `{judges.v3_pairs.llama_vs_agent.false_alarm.n:int}` | 288 |
  | `{judges.v3_pairs.llama_vs_agent.false_alarm.reading}` | slight |
  | `{v3_local_llama_judge.false_alarm_total:int}` | 0 |
  | `{v3_local_llama_judge.no_defect_claim_mutant.k:int}` | 54 |
  | `{v3_local_llama_judge.no_defect_claim_mutant.n:int}` | 96 |
  | `{derived.llama_no_defect_claim_pct:int}` | 56 |
  | `{v3_local_llama_judge.judge_model}` | llama3.2:3b |
  | `{v3_local_llama_judge.tests.intent_all.floor:pct}` | 58% |
  | `{v3_local_llama_judge.tests.intent_all.treatment:pct}` | 63% |
  | `{v3_local_llama_judge.tests.intent_all.ceiling:pct}` | 83% |
  | `{v3_local_llama_judge.tests.intent_all.gap_recovery:f2}` | 0.17 |
  | `{v3_local_llama_judge.tests.intent_all.gap_ci:ci}` | -0.31 to 0.52 |
  | `{v3_local_llama_judge.tests.intent_all.mcnemar_p:f2}` | 0.56 |
  | `{v3_local.judge_model}` | claude-sonnet-subagent |

### `report.s7_9.robust`

* **Appears in:** report, 7.9 after Figure 7.7
* **Kind / target length:** one paragraph; 80-120 words
* **Framing notes:** Figure 7.7 plots G with its 95% interval for v2/API judge, v2/agent judge, v3/agent judge and v3/local judge (hatched = unreliable judge). Point: the size of G depends on the judge but every interval reaches zero. Do not rank the judges by which gives the better G.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{v2.tests.intent_all.n:int}` | 36 |
  | `{v2.tests.intent_all.floor:pct}` | 81% |
  | `{v2.tests.intent_all.treatment:pct}` | 83% |
  | `{v2.tests.intent_all.ceiling:pct}` | 97% |
  | `{v2.tests.intent_all.gap_recovery:f2}` | 0.17 |
  | `{v2.tests.intent_all.gap_ci:ci}` | 0.00 to 0.50 |
  | `{v2.tests.intent_all.mcnemar_p:f2}` | 1.00 |
  | `{v2.complete_triples:int}` | 36 |
  | `{v2.judged:int}` | 108 |
  | `{v2_agent_judge.tests.intent_all.n:int}` | 36 |
  | `{v2_agent_judge.tests.intent_all.floor:pct}` | 86% |
  | `{v2_agent_judge.tests.intent_all.treatment:pct}` | 92% |
  | `{v2_agent_judge.tests.intent_all.ceiling:pct}` | 100% |
  | `{v2_agent_judge.tests.intent_all.gap_recovery:f2}` | 0.40 |
  | `{v2_agent_judge.tests.intent_all.gap_ci:ci}` | -0.75 to 1.00 |
  | `{v2_agent_judge.tests.intent_all.mcnemar_p:f2}` | 0.63 |
  | `{v2_agent_judge.tests.intent_all.discordant_treatment_better:int}` | 3 |
  | `{v2_agent_judge.tests.intent_all.discordant_floor_better:int}` | 1 |
  | `{derived.v2_agent_judge.intent_all.floor_k:int}` | 31 |
  | `{derived.v2_agent_judge.intent_all.treatment_k:int}` | 33 |
  | `{derived.v2_agent_judge.intent_all.ceiling_k:int}` | 36 |
  | `{v3_local.tests.intent_all.gap_recovery:f2}` | 0.09 |
  | `{v3_local.tests.intent_all.gap_ci:ci}` | -0.22 to 0.33 |
  | `{v3_local_llama_judge.tests.intent_all.gap_recovery:f2}` | 0.17 |
  | `{v3_local_llama_judge.tests.intent_all.gap_ci:ci}` | -0.31 to 0.52 |

### `report.s7_10.post_hoc`

* **Appears in:** report, 7.10 Threats to Validity, bullet
* **Kind / target length:** one bullet (a full sentence, no leading bullet); 25-45 words
* **Framing notes:** The v3 agent judge was chosen after seeing agreement between judges (post hoc), because the local judge was unusable.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{v3_local.judge_model}` | claude-sonnet-subagent |

### `report.s7_10.oracle`

* **Appears in:** report, 7.10 Threats to Validity, bullet
* **Kind / target length:** one bullet; 25-45 words
* **Framing notes:** The v3 question and oracle model is small and its identity is not recorded per database row; it is recorded only in the oracle log.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{v3_setup.question_oracle_model}` | llama3.2:3b |
  | `{v3_setup.question_oracle.n_logged:int}` | 11 |

### `report.s7_10.new_rows`

* **Appears in:** report, 7.10 Threats to Validity, bullet
* **Kind / target length:** one bullet; 20-40 words
* **Framing notes:** The {n_new_rows} rows added in v3 have no run by the original (Gemini) reviewer, so the two studies differ in reviewer and judge as well as in rows.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{v3_design.n_new_rows:int}` | 60 |

### `report.s7_10.bot`

* **Appears in:** report, 7.10 Threats to Validity, bullet
* **Kind / target length:** one bullet; 20-40 words
* **Framing notes:** The bot has been exercised end to end on a local server and has not been run against live GitHub.
* **Allowed tokens:** none (no number may appear)

### `report.conclusion.v3`

* **Appears in:** report, 8. Conclusion, new paragraph after the findings paragraph
* **Kind / target length:** one paragraph; 90-130 words
* **Framing notes:** The v3 replication on a local reviewer and the judge calibration: null result with a bound, effect size depends on the judge, v2 and v3 never pooled; what remains not done (human judge validation, labelling of the {n_prs} real PRs, live deployment) stated as not done.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{v3_local.tests.intent_all.n:int}` | 96 |
  | `{v3_local.tests.intent_all.floor:pct}` | 67% |
  | `{v3_local.tests.intent_all.treatment:pct}` | 70% |
  | `{v3_local.tests.intent_all.ceiling:pct}` | 100% |
  | `{v3_local.tests.intent_all.gap_recovery:f2}` | 0.09 |
  | `{v3_local.tests.intent_all.gap_ci:ci}` | -0.22 to 0.33 |
  | `{v3_local.tests.intent_all.mcnemar_p:f2}` | 0.66 |
  | `{judges.v2_three_way_intent.all_agree:int}` | 25 |
  | `{judges.v2_three_way_intent.n:int}` | 30 |
  | `{realpr.n_prs:int}` | 356 |
  | `{realpr.n_repos:int}` | 16 |


---

## Deck

### `deck.abstract.v3`

* **Appears in:** deck, Slide 4 (Abstract), end of the Result bullet
* **Kind / target length:** one clause or sentence; 15-25 words
* **Framing notes:** Append: replicated on a {reviewer_model_name} local reviewer, G with its upper CI limit; null. Must fit one bullet line or two.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{v3_setup.reviewer_model_name}` | qwen3:4b-instruct-2507-q4_K_M |
  | `{v3_local.tests.intent_all.gap_recovery:f2}` | 0.09 |
  | `{v3_local.tests.intent_all.gap_ci:ci}` | -0.22 to 0.33 |

### `deck.v3.replication`

* **Appears in:** deck, Slide 14 (Experiments and Results 3/3), bullet 1
* **Kind / target length:** one bullet; 20-35 words
* **Framing notes:** Replication on a local 4B reviewer: intent floor -> treatment -> ceiling (pct), G, CI, p. Null with a bound.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{v3_setup.reviewer_model_name}` | qwen3:4b-instruct-2507-q4_K_M |
  | `{v3_local.tests.intent_all.n:int}` | 96 |
  | `{v3_local.tests.intent_all.floor:pct}` | 67% |
  | `{v3_local.tests.intent_all.treatment:pct}` | 70% |
  | `{v3_local.tests.intent_all.ceiling:pct}` | 100% |
  | `{v3_local.tests.intent_all.gap_recovery:f2}` | 0.09 |
  | `{v3_local.tests.intent_all.gap_ci:ci}` | -0.22 to 0.33 |
  | `{v3_local.tests.intent_all.mcnemar_p:f2}` | 0.66 |

### `deck.v3.judges`

* **Appears in:** deck, Slide 14, bullet 2
* **Kind / target length:** one bullet; 20-35 words
* **Framing notes:** Judge check: AI judges agree on defects and false alarms, only moderately on intent; the local judge is unusable so the Claude agent judge is primary for v3 (post hoc). AI-vs-AI; not human validation.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{judges.v2_pairs.api_vs_agent.intent_recovered.kappa:f2}` | 0.40 |
  | `{judges.v2_pairs.api_vs_agent.intent_recovered.percent_agreement:pct}` | 89% |
  | `{judges.v2_pairs.api_vs_agent.intent_recovered.n:int}` | 108 |
  | `{judges.v2_pairs.api_vs_agent.intent_recovered.reading}` | fair |
  | `{judges.v3_pairs.llama_vs_agent.intent_recovered.kappa:f2}` | 0.20 |
  | `{judges.v3_pairs.llama_vs_agent.intent_recovered.percent_agreement:pct}` | 68% |
  | `{judges.v3_pairs.llama_vs_agent.intent_recovered.n:int}` | 288 |
  | `{judges.v3_pairs.llama_vs_agent.intent_recovered.reading}` | fair |
  | `{judges.v2_three_way_intent.all_agree:int}` | 25 |
  | `{judges.v2_three_way_intent.n:int}` | 30 |
  | `{judges.models.api_v3}` | llama3.2:3b |

### `deck.v3.limits`

* **Appears in:** deck, Slide 14, bullet 3
* **Kind / target length:** one bullet; 20-35 words
* **Framing notes:** Same verdict under a different judge, a different magnitude: v2 G under the agent judge; recall remains the limit (asked/answered/recovered).
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{v3_local.funnel.floor_misses:int}` | 32 |
  | `{v3_local.funnel.ceiling_also_missed:int}` | 0 |
  | `{v3_local.funnel.detector_asked:int}` | 8 |
  | `{v3_local.funnel.author_answered:int}` | 7 |
  | `{v3_local.funnel.treatment_recovered:int}` | 3 |
  | `{v2_agent_judge.tests.intent_all.n:int}` | 36 |
  | `{v2_agent_judge.tests.intent_all.floor:pct}` | 86% |
  | `{v2_agent_judge.tests.intent_all.treatment:pct}` | 92% |
  | `{v2_agent_judge.tests.intent_all.ceiling:pct}` | 100% |
  | `{v2_agent_judge.tests.intent_all.gap_recovery:f2}` | 0.40 |
  | `{v2_agent_judge.tests.intent_all.gap_ci:ci}` | -0.75 to 1.00 |

### `deck.conclusion.v3`

* **Appears in:** deck, Slide 16 (Conclusion), new Found bullet (after the text "Found: ")
* **Kind / target length:** one sentence; 15-30 words
* **Framing notes:** Replicated on a 4B local model: null result, G with upper CI limit.
* **Allowed tokens (current value):**

  | token | value now |
  |---|---|
  | `{v3_setup.reviewer_model_name}` | qwen3:4b-instruct-2507-q4_K_M |
  | `{v3_local.tests.intent_all.gap_recovery:f2}` | 0.09 |
  | `{v3_local.tests.intent_all.gap_ci:ci}` | -0.22 to 0.33 |

