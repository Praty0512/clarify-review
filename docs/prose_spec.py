"""Every prose placeholder in the Review 3 deliverables: where it sits, which
numbers it may quote, how long it should be, and what it has to say.

This file is the single source for docs/prose_v3.json (ids) and for
docs/prose_v3_brief.md (the writer's brief). `python docs/prose_tool.py sync`
and `brief` regenerate them; `check` verifies that the ids used by the builders,
this spec and the JSON all agree.

A token is "<key.path>:<format>" and is written {key.path:format} in the prose.
"""

from __future__ import annotations

# ----------------------------------------------------------------- token groups


def _t(study: str, test: str, *fields: str) -> list[str]:
    fm = {"floor": "pct", "treatment": "pct", "ceiling": "pct", "gap_recovery": "f2",
          "gap_ci": "ci", "mcnemar_p": "f2", "n": "int",
          "discordant_treatment_better": "int", "discordant_floor_better": "int"}
    return [f"{study}.tests.{test}.{f}:{fm[f]}" for f in fields]


def _k(study: str, test: str, *fields: str) -> list[str]:
    return [f"derived.{study}.{test}.{f}:int" for f in fields]


V3_INTENT = (_t("v3_local", "intent_all", "n", "floor", "treatment", "ceiling", "gap_recovery",
                "gap_ci", "mcnemar_p", "discordant_treatment_better", "discordant_floor_better")
             + _k("v3_local", "intent_all", "floor_k", "treatment_k", "ceiling_k", "gap_points",
                  "treatment_points", "discordant_total")
             + ["v3_local.complete_triples:int", "v3_local.runs_ok:int", "v3_local.judged:int"])
V3_INTENT_SPLIT = (_t("v3_local", "intent_golden", "n", "floor", "treatment", "ceiling",
                      "gap_recovery", "mcnemar_p")
                   + _t("v3_local", "intent_mutant", "n", "floor", "treatment", "ceiling",
                        "gap_recovery", "mcnemar_p"))
V3_FUNNEL = [f"v3_local.funnel.{k}:int" for k in (
    "floor_misses", "ceiling_also_missed", "detector_asked", "author_answered",
    "treatment_recovered", "asked_total", "answered_total")] + [
    "v3_local.treatment_asks:int", "v3_local.treatment_n:int", "v3_local.treatment_answered:int",
    "derived.v3_asked_on_understood:int", "derived.v3_detector_missed:int"]
V3_DEFECT = (_t("v3_local", "defect_mutant", "n", "floor", "treatment", "ceiling", "mcnemar_p")
             + _k("v3_local", "defect_mutant", "floor_k", "treatment_k", "ceiling_k"))
V3_FALSE = (_t("v3_local", "false_alarm_golden", "n", "floor", "treatment", "ceiling", "mcnemar_p")
            + _k("v3_local", "false_alarm_golden", "floor_k", "treatment_k", "ceiling_k"))
V3_SETUP = ["v3_setup.reviewer_model_name", "v3_setup.reviewer_model", "v3_setup.backend",
            "v3_setup.detector", "v3_setup.threshold:f2", "v3_setup.runs:int",
            "v3_setup.runs_failed:int", "v3_setup.wall_minutes:int",
            "v3_setup.question_oracle_model", "v3_setup.question_oracle.n_logged:int",
            "v3_design.rows:int", "v3_design.v2_rows:int", "v3_design.n_new_rows:int",
            "v3_design.mutants_used:int", "v3_design.mutants_verified_total:int",
            "v3_design.golden_only_rows:int", "v3_design.golden_only_repos:int",
            "mutants.attempted:int", "mutants.by_status.verified:int"]
V2_INTENT = (_t("v2", "intent_all", "n", "floor", "treatment", "ceiling", "gap_recovery",
                "gap_ci", "mcnemar_p")
             + ["v2.complete_triples:int", "v2.judged:int"])
V2_AGENT = (_t("v2_agent_judge", "intent_all", "n", "floor", "treatment", "ceiling",
               "gap_recovery", "gap_ci", "mcnemar_p", "discordant_treatment_better",
               "discordant_floor_better")
            + _k("v2_agent_judge", "intent_all", "floor_k", "treatment_k", "ceiling_k"))
JUDGE_MODELS = ["judges.models.api_v2", "judges.models.agent", "judges.models.gemini_web",
                "judges.models.api_v3", "judges.gemini_sample.n:int", "v3_local.judge_label"]


def _pair(pair: str) -> list[str]:
    out = []
    for m in ("intent_recovered", "defect_caught", "false_alarm"):
        base = f"judges.{pair}.{m}"
        out += [f"{base}.kappa:f2", f"{base}.percent_agreement:pct", f"{base}.n:int",
                f"{base}.reading"]
    return out


J_V2_API_AGENT = _pair("v2_pairs.api_vs_agent")
J_V2_GEM_AGENT = _pair("v2_pairs.gemini_vs_agent")
J_V2_GEM_API = _pair("v2_pairs.gemini_vs_api")
J_V3_LLAMA = _pair("v3_pairs.llama_vs_agent")
J_THREE = ["judges.v2_three_way_intent.all_agree:int", "judges.v2_three_way_intent.n:int"]
LLAMA_REF = ["v3_local_llama_judge.false_alarm_total:int",
             "v3_local_llama_judge.no_defect_claim_mutant.k:int",
             "v3_local_llama_judge.no_defect_claim_mutant.n:int",
             "derived.llama_no_defect_claim_pct:int",
             "v3_local_llama_judge.judge_model"] + _t(
                 "v3_local_llama_judge", "intent_all", "floor", "treatment", "ceiling",
                 "gap_recovery", "gap_ci", "mcnemar_p")
REALPR = ["realpr.n_prs:int", "realpr.n_repos:int", "realpr.n_labelled:int",
          "realpr.n_annotated:int"]
LIVE = ["live_demo.n_prs:int", "live_demo.n_asked:int", "live_demo.n_answered:int",
        "live_demo.n_defects_flagged:int", "live_demo.n_request_changes:int",
        "live_demo.pr1.score:f2", "live_demo.pr1.threshold:f2",
        "live_demo.pr1.without_answer.overall_confidence:pct",
        "live_demo.pr1.overall_confidence:pct", "live_demo.pr1.verdict",
        "live_demo.pr1.n_findings:int", "live_demo.pr1.answer_round_trip_s:f2",
        "live_demo.pr2.score:f2", "live_demo.pr2.verdict", "live_demo.pr2.n_findings:int",
        "live_demo.pr2.finding_severity", "live_demo.pr2.finding_category",
        "live_demo.pr2.facts.provider_retries:int", "live_demo.pr2.answer_round_trip_s:f2",
        "live_demo.pr2.reviewer_model", "live_demo.pr2.question_model"]
LIVE_FRAME = (
    "Framing: it is a DEMONSTRATION on {n_prs} constructed PRs in the authors' own sandbox "
    "repository, NOT an evaluation and not a sample. PR 1 was reviewed by the command-line tool "
    "(review --repo --pr --post, which blocks while waiting for the author) and PR 2 by the "
    "webhook bot (serve behind a tunnel, which parks the run and resumes on the author's reply). "
    "In both the heuristic detector asked unprompted (score {pr1.score}, threshold "
    "{pr1.threshold}) and the author answered on the PR. PR 1: the removed email check was "
    "intentional (phone-number-only accounts); the review's intent summary recovered that reason "
    "and its confidence rose from {pr1.without_answer.overall_confidence} (dry run without an "
    "answer) to {pr1.overall_confidence}; verdict approve, no findings. PR 2: the author's reply "
    "showed the removal of the disabled-account check was unintended; the bot posted a "
    "request-changes review with {pr2.n_findings} {pr2.finding_severity} {pr2.finding_category} "
    "finding. The answer changed the review in both. Reviewer {pr2.reviewer_model}, question "
    "model {pr2.question_model}. The bot rode out {pr2.facts.provider_retries} transient provider "
    "500 errors by retrying and ignored its own comments' webhooks (a fact, not a result). "
    "Limits to state: one laptop behind a tunnel (not permanent hosting), free-tier quota, "
    "heuristic detector, n = {n_prs} constructed cases chosen by the authors, so no rate or "
    "effect is estimated. Do not call it validation or evaluation; do not generalise. Live "
    "deployment beyond a sandbox, on real third-party PRs at scale, remains future work.")
TESTS = ["derived.tests_passed:int", "derived.tests_skipped:int", "test_files:int"]
V2_TOK = ["v2_tokens.input:k", "v2_tokens.output:k", "v2_tokens.cache_read:k"]
DETS = ["detectors.heuristic.recall:pct", "detectors.heuristic.precision:f2",
        "detectors.heuristic.ask_rate:pct"]

# ----------------------------------------------------------------------- spec
# Fields: id, doc, where, kind, words (target), tokens, notes, replaces (existing
# text the placeholder supersedes, quoted so the new text can keep its voice).

SPEC: list[dict] = []


def add(id, doc, where, kind, words, tokens, notes, replaces=""):
    SPEC.append(dict(id=id, doc=doc, where=where, kind=kind, words=words, tokens=tokens,
                     notes=notes, replaces=replaces))


# ----------------------------------------------------------------------- paper
add("paper.abstract.v3", "paper", "Abstract (single block, after the v2 sentences, before "
    "\"We release the system...\")", "2-3 sentences", "45-65",
    ["v3_setup.reviewer_model_name", "v3_local.complete_triples:int"]
    + _t("v3_local", "intent_all", "floor", "treatment", "ceiling", "gap_recovery", "gap_ci",
         "mcnemar_p"),
    "The v3 replication: reviewer {v3_setup.reviewer_model_name}, {n} instances, intent recovery "
    "floor / treatment / ceiling (pct), G with its 95% CI, p. State it as a null result with a "
    "bound. End with a sentence that re-scoring with a second judge preserved the verdict but not "
    "the magnitude (v2 G moved from the API judge's value to the agent judge's value). Do not "
    "pool v2 and v3.")
add("paper.intro.contrib5", "paper", "I. Introduction, contribution 5) (the list item text "
    "after \"5) \")", "one clause ending in a full stop", "25-40", [],
    "A judge-calibration analysis across three AI judges and a second-model replication. The "
    "list items 1-4 are fixed in code and read \"1) ClarifyReview, a four-stage reviewer...;\"; "
    "keep this item as a noun phrase of the same shape, ending with a full stop. Say it is "
    "AI-vs-AI, not human validation.")
add("paper.sys.extraction", "paper", "III. ClarifyReview, Stage 1 sentence", "clause (no leading "
    "capital, no trailing full stop)", "15-30", [],
    "Replaces the clause \"with the Python abstract syntax tree\" in: \"Stage 1 parses the diff "
    "and resolves changed lines to changed symbols <CLAUSE>, assembling a bounded context in a "
    "deterministic order and fingerprinting it.\" Say: Python through its AST; JavaScript, "
    "TypeScript/TSX, Java, C, C++ and Rust through tree-sitter grammars; Python behaviour "
    "byte-identical to before.",
    "with the Python abstract syntax tree")
add("paper.sys.backends", "paper", "III. ClarifyReview, closing paragraph (after the sentence "
    "ending \"automated tests.\")", "1-2 sentences", "25-40", TESTS,
    "Three provider backends behind one interface: Gemini, Anthropic and local Ollama. The "
    "Ollama backend runs a model on the user's own machine with no network and no cost. Keep to "
    "what exists; do not claim the Anthropic backend was used in the studies.")
add("paper.sys.bot", "paper", "III. ClarifyReview, closing paragraph (follows paper.sys.backends)",
    "1-2 sentences", "30-50", TESTS,
    "Bot robustness: parked runs persist in SQLite across restarts, a timeout sweep, handling of "
    "rate limits, signed-webhook verification. State that it passes offline end-to-end tests "
    "and has also been run once on real GitHub in a sandbox repository (the demonstration in the "
    "next paragraph, paper.live.demo; do not describe it here). Do not claim permanent hosting "
    "or use on third-party PRs.")
add("paper.live.demo", "paper", "III. ClarifyReview, new paragraph after paper.sys.bot "
    "(plain paragraph; no heading)", "one paragraph", "70-110", LIVE, LIVE_FRAME)
add("paper.method.v3_design", "paper", "IV-F. Second-model replication (v3) (heading is fixed in "
    "code)", "one paragraph", "110-150", V3_SETUP,
    "Design of v3: {v3_design.rows} rows = the v2 set plus {n_new_rows} new rows; all "
    "{mutants_used} verified mutants (both arms) and golden-only rows from other repositories "
    "({golden_only_repos} repos). Reviewer {reviewer_model_name} through Ollama, heuristic "
    "detector at tau = {threshold}, {runs_failed} failed runs, {wall_minutes} minutes on a laptop "
    "GPU. Question and oracle model {question_oracle_model} (not recorded per DB row; logged in "
    "the oracle log). Same conditions as v2. v3 is NEVER pooled with v2. Mention the judge is "
    "chosen in V-G, not here.")
add("paper.results.v3_lead", "paper", "V-F. Replication on a local reviewer, first paragraph "
    "(precedes Table III)", "2-3 sentences", "40-70", V3_SETUP[:3] + V3_INTENT[:1] + [
        "v3_local.judge_label", "v3_local.judge_model"],
    "Introduce Table III (same rows as Table I, but v3, scored by the Claude agent judge "
    "{v3_local.judge_label}). Say the judge choice is explained in Section V-G and was made after "
    "seeing agreement; v3 is reported separately from v2.")
add("paper.results.v3_effect", "paper", "V-F. after Table III and Fig. 6", "one paragraph",
    "100-150", V3_INTENT + V3_INTENT_SPLIT,
    "(a) A null result WITH A BOUND: G and its CI; the upper bound rules out clarification "
    "recovering more than about a third of the gap at this n (use the upper CI limit). Say "
    "'not significant', never 'trend toward'. (b) Ceiling vs floor shows stripping costs "
    "{derived.v3_local.intent_all.gap_points} points of intent recovery, so the manipulation "
    "works. Mention n and p.")
add("paper.results.v3_funnel", "paper", "V-F. second paragraph", "one paragraph", "100-150",
    V3_FUNNEL + _t("v3_local", "intent_all", "discordant_treatment_better",
                   "discordant_floor_better"),
    "(c) The detector asked on {treatment_asks} of {treatment_n} treatment reviews; the funnel "
    "floor_misses -> detector_asked -> author_answered -> treatment_recovered shows detector "
    "recall is the limit (same finding as v2). (d) Discordant pairs go BOTH ways: clarification "
    "helped on some instances and hurt on others (give both counts).")
add("paper.results.v3_defects", "paper", "V-F. third paragraph", "one paragraph", "80-120",
    V3_DEFECT + V3_FALSE + ["v3_setup.reviewer_model_name"],
    "(e) Defect detection is near the floor even with full context (give k of n for floor, "
    "treatment, ceiling): a 4B reviewer limits defect detection, as the larger v2 reviewer did. "
    "(f) False alarms over the golden rows (k of n for each condition); too few to separate "
    "conditions. No effect claim on defects.")
add("paper.results.judges_lead", "paper", "V-G. Judge calibration, first paragraph (precedes "
    "Table IV)", "2-3 sentences", "50-80", JUDGE_MODELS + J_THREE,
    "Three AI judges scored the v2 reviews: the API judge {judges.models.api_v2}, Claude Sonnet "
    "agents, and the Gemini web app on a stratified sample of {gemini_sample.n} runs "
    "(stratified by condition and variant). Table IV gives % agreement / kappa / n. All of this "
    "is AI-vs-AI agreement; none of it is validation against human scorers.")
add("paper.results.judges_v2", "paper", "V-G. after Table IV and Fig. 7", "one paragraph",
    "120-170", J_V2_API_AGENT + J_V2_GEM_AGENT + J_V2_GEM_API + J_THREE + V2_AGENT + V2_INTENT,
    "v2: the API judge agrees with the agent judge near-perfectly on defects and false alarms, "
    "moderately/fairly on intent (give kappa and % for intent). Three-way intent agreement "
    "{all_agree} of {n}. Re-scoring v2 with the agent judge: intent floor/treatment/ceiling and G "
    "with CI and p; the verdict (not significant) holds, the size of G does not (compare with the "
    "API judge's G).")
add("paper.results.judges_v3", "paper", "V-G. last paragraph", "one paragraph", "130-190",
    J_V3_LLAMA + LLAMA_REF + ["v3_local.judge_label", "v3_local.judge_model"],
    "v3: the local judge {judges.models.api_v3} is unusable (give kappa for each metric versus "
    "the agent); it never flagged a false alarm (total {false_alarm_total}) and wrote 'no defect "
    "was injected' on {k} of {n} mutant rows. So the Claude agent judge is primary for v3 -- "
    "chosen AFTER seeing the agreement: disclose that it is a post hoc choice. State that the "
    "llama judge's own intent result is reference only. Close: all AI-vs-AI; human validation "
    "not done.")
add("paper.disc.replication", "paper", "VI. Discussion, new final paragraph", "one paragraph",
    "90-130", V2_INTENT + V3_INTENT[:9] + V2_AGENT[:7],
    "Two reviewers and two judges give the same picture: no significant effect; recall-bound; "
    "defect detection limited by the reviewer; but the effect SIZE depends on which judge scores "
    "(v2: API judge G vs agent judge G). Keep it short and non-repetitive.")
add("paper.threats.v3", "paper", "VII. Threats to Validity, new paragraph after the first",
    "one paragraph", "120-170", V3_SETUP[:2] + ["v3_design.n_new_rows:int", "v2.complete_triples:int",
    "v3_local.complete_triples:int", "v3_setup.question_oracle_model"] + REALPR[:1]
    + ["live_demo.n_prs:int"],
    "Threats added by v3: samples are small in both studies; the v3 agent judge was chosen after "
    "seeing agreement with the local judge (post hoc); the v3 question/oracle model is small and "
    "its identity is not recorded per DB row (only in the oracle log); the {n_new_rows} new rows "
    "have no Gemini-reviewer run; the live GitHub demonstration is {n_prs} constructed PRs in the "
    "authors' own sandbox repository, run from a laptop behind a tunnel, so it shows the loop "
    "works but estimates nothing; live deployment on real third-party PRs is still to be done. "
    "Each as a plain statement of limitation.")
add("paper.conclusion.v3", "paper", "VIII. Conclusion, one sentence inserted before \"Future work "
    "is ...\"", "1-2 sentences", "35-60", V3_INTENT[:7],
    "A second reviewer (a local 4B model) and a second judge reproduce the null result: G and its "
    "upper CI limit; effect size depends on the judge. No spin.")

# ---------------------------------------------------------------------- report
add("report.abstract.v3", "report", "Abstract (final paragraph; the template caps the abstract "
    "at 500 words and one page and the existing text is already about 435 words)",
    "one short paragraph", "<= 60 (hard cap)",
    ["v3_setup.reviewer_model_name"] + _t("v3_local", "intent_all", "floor", "treatment",
                                           "ceiling", "gap_recovery", "gap_ci"),
    "v3 replication on a local reviewer (null, G with CI), judge calibration across AI judges "
    "(effect size depends on the judge), multi-language support, Ollama backend, bot. List what is "
    "NOT done in a few words: human judge validation, real-PR labelling, permanent hosting and "
    "runs on real third-party PRs at scale. The bot HAS been run live on GitHub on {n_prs} sandbox "
    "PRs (a demonstration); mention that in a few words if it fits. "
    "The total length is a hard constraint (one-page abstract); if it cannot fit in 60 words, "
    "say so rather than overrun.")
add("report.s1_3.scope", "report", "1.3 Scope of the Project, first paragraph", "one paragraph",
    "80-120", ["realpr.n_prs:int"],
    "Replaces the stale text. Scope now: pull request reviewer that detects ambiguous intent and "
    "asks; Python plus JavaScript, TypeScript/TSX, Java, C, C++ and Rust (Python behaviour "
    "unchanged); GitHub bot responding to webhooks; the four stages of Chapter 4. Still out of "
    "scope: an editor extension and any interface beyond PR comments. Permanent hosting, runs on "
    "real third-party PRs at scale and human studies are pending, not out of scope; the bot has "
    "been demonstrated live on a sandbox repository (Section 6.4).",
    "The project builds and evaluates a pull request reviewer that detects ambiguous intent and "
    "asks before commenting. The system targets Python repositories on GitHub, is delivered as a "
    "bot that responds to pull request webhooks, and is restricted to the four stages described "
    "in Chapter 4. Multi-language support, an editor extension and any interface beyond pull "
    "request comments are out of scope because none of them bears on the contribution.")
add("report.s1_3.eval_scope", "report", "1.3 Scope of the Project, last paragraph",
    "one paragraph", "70-110", ["v2.complete_triples:int", "v3_design.rows:int",
                                 "v3_setup.reviewer_model_name", "v3_setup.wall_minutes:int"],
    "Evaluation scope: v2 (free-tier hosted models, {v2.complete_triples} instances) and v3 "
    "(local model through Ollama, {v3_design.rows} rows); the tooling for a paired developer "
    "study; a field deployment is not attempted, which is why the target is TRL 4.",
    "The evaluation is scoped to what one student team can complete in a semester on free-tier "
    "model access: a two-by-three ablation over {v2 n} SWE-bench Verified instances with "
    "execution-verified defects, and the tooling for a paired developer study. A field "
    "deployment is not attempted, which is why the target technology readiness level is TRL 4.")
add("report.s3_2_2.economic", "report", "3.2.2 Economic Feasibility", "one paragraph", "90-130",
    ["v3_setup.wall_minutes:int", "v3_setup.reviewer_model_name", "v3_setup.backend",
     "v2_tokens.input:k", "v2_tokens.output:k"],
    "v2 ran on the Google Gemini free tier at zero monetary cost (Section 7.7) with a per-day "
    "request quota as the binding constraint (roles split across models, commits per instance, "
    "resume). v3 ran locally through Ollama at zero cost in {wall_minutes} minutes on a laptop "
    "GPU. No hardware, licence or dataset was purchased; libraries are open source. Not 'the "
    "whole study ran on Gemini'.",
    "The only recurring cost is model usage. The whole study ran on the Google Gemini free tier "
    "at zero monetary cost (Section 7.7). The binding constraint is a per-day request quota "
    "applied per model, which the design accommodates by assigning roles to different models, "
    "committing results per instance, and resuming after a reset. No hardware, licence or "
    "dataset was purchased; all libraries are open source.")
add("report.s5_1_1.extraction", "report", "5.1.1 Ingestion (sentence 2)", "one sentence",
    "35-60", [],
    "Replaces: \"The semantic layer parses the post-change file with the Python AST and maps each "
    "changed line to its enclosing function, method or class, recording whether the signature "
    "changed.\" Keep that content but add: JavaScript, TypeScript/TSX, Java, C, C++ and Rust via "
    "tree-sitter grammars; Python path unchanged.",
    "The semantic layer parses the post-change file with the Python AST and maps each changed "
    "line to its enclosing function, method or class, recording whether the signature changed.")
add("report.s5_1_4.ollama", "report", "5.1.4 LLM provider layer, closing sentence(s)",
    "1-2 sentences", "25-45", ["v3_setup.backend", "v3_setup.reviewer_model_name"],
    "The Ollama backend: a local model over HTTP, recording the model name and digest that "
    "actually served each call; no key, no network, no cost.")
add("report.s5_1_5.bot", "report", "5.1.5 GitHub bot (new subsection; heading fixed in code)",
    "one paragraph", "90-130", TESTS,
    "Robustness of the live bot: parked runs stored durably so a restart resumes them, a timeout "
    "sweep that publishes an unanswered review, rate-limit handling, signed-webhook "
    "verification, duplicate-delivery handling. State it passes offline end-to-end tests and has "
    "also run live on GitHub in a sandbox repository (Section 6.4, do not describe the run here). "
    "Permanent hosting and use on third-party PRs are not done.")
add("report.s5_2_5.calibration", "report", "5.2.5 Simulated author and judge, new paragraph "
    "after the existing one", "one paragraph", "100-140", JUDGE_MODELS,
    "Method of the judge-calibration analysis: the same context and instructions are given to "
    "the API judge, Claude Sonnet agent judges and (on a stratified sample) the Gemini web app, "
    "blind to condition; agreement as % and Cohen's kappa per metric; the study is re-analysed "
    "under each judge. It is AI-vs-AI. Say nothing about results here.")
add("report.s5_2_7.v3_design", "report", "5.2.7 Replication on a local reviewer (v3) (new "
    "subsection; heading fixed in code)", "one paragraph", "110-150", V3_SETUP,
    "Same content as paper.method.v3_design: rows (v2 set plus new rows), all verified mutants "
    "and golden-only rows from other repositories, local reviewer via Ollama, heuristic detector "
    "at tau {threshold}, failed runs, minutes, question/oracle model. Never pooled with v2.")
add("report.s6_3.status", "report", "6.3 Deployment as a GitHub bot, closing paragraph",
    "one paragraph", "60-90", TESTS,
    "What has and has not been shown: the bot, parked-run store and webhook path pass offline "
    "end-to-end tests and have also run against live GitHub in a sandbox repository (the next "
    "subsection, 6.4, reports it; refer to it, do not repeat it). What is NOT shown: permanent "
    "hosting (it ran from a laptop behind a tunnel) and any use on third-party PRs. Mention the "
    "Windows demo script alongside demo.sh.")
add("report.s6_4.live", "report", "6.4 A live run on GitHub (new subsection; heading fixed in "
    "code, follows report.s6_3.status)", "one paragraph", "120-180", LIVE, LIVE_FRAME)
add("report.s7_8.setup", "report", "7.8 Replication on a Local Reviewer (v3), first paragraph "
    "(precedes Table 7.4)", "one paragraph", "100-140", V3_SETUP + [
        "v3_local.judge_label", "v3_local.judge_model", "v3_local.judged:int"],
    "Set-up in report voice: local reviewer {reviewer_model_name} through Ollama on a laptop GPU, "
    "{runs} reviews, {runs_failed} failed, {wall_minutes} minutes, no monetary cost; the same "
    "three conditions; scored by the Claude agent judge (chosen after seeing agreement; see "
    "Section 7.9). Table 7.4 follows. Never pooled with v2.")
add("report.s7_8.effect", "report", "7.8 after Figure 7.4", "one paragraph", "110-160",
    V3_INTENT + V3_INTENT_SPLIT,
    "Same finding as paper.results.v3_effect: null WITH A BOUND (G, CI, upper limit about a "
    "third), 'not significant', stripping costs {gap_points} points so the manipulation works. "
    "Refer to Figure 7.4 and Table 7.4.")
add("report.s7_8.funnel", "report", "7.8 after Figure 7.5", "one paragraph", "100-150",
    V3_FUNNEL + _t("v3_local", "intent_all", "discordant_treatment_better",
                   "discordant_floor_better"),
    "Same finding as paper.results.v3_funnel: detector asked on {treatment_asks} of {treatment_n} "
    "reviews; funnel floor_misses -> detector_asked -> author_answered -> treatment_recovered; "
    "recall is the limit; discordant pairs in both directions. Refer to Figure 7.5.")
add("report.s7_8.defects", "report", "7.8 final paragraph", "one paragraph", "80-120",
    V3_DEFECT + V3_FALSE,
    "Same as paper.results.v3_defects: defects near the floor even with full context; 4B "
    "reviewer limits detection; false alarms over the golden rows.")
add("report.s7_9.lead", "report", "7.9 Judge Calibration, first paragraph (precedes Table 7.5)",
    "2-3 sentences", "50-80", JUDGE_MODELS + J_THREE + ["v3_local.judge_label"],
    "Same content as paper.results.judges_lead. All AI-vs-AI; none is human validation.")
add("report.s7_9.v2", "report", "7.9 after Figure 7.6", "one paragraph", "120-170",
    J_V2_API_AGENT + J_V2_GEM_AGENT + J_V2_GEM_API + J_THREE + V2_AGENT + V2_INTENT,
    "Same content as paper.results.judges_v2.")
add("report.s7_9.v3", "report", "7.9 next paragraph", "one paragraph", "130-190",
    J_V3_LLAMA + LLAMA_REF + ["v3_local.judge_model", "v3_local.judge_label"],
    "Same content as paper.results.judges_v3, including the post hoc disclosure.")
add("report.s7_9.robust", "report", "7.9 after Figure 7.7", "one paragraph", "80-120",
    V2_INTENT + V2_AGENT + _t("v3_local", "intent_all", "gap_recovery", "gap_ci") + _t(
        "v3_local_llama_judge", "intent_all", "gap_recovery", "gap_ci"),
    "Figure 7.7 plots G with its 95% interval for v2/API judge, v2/agent judge, v3/agent judge "
    "and v3/local judge (hatched = unreliable judge). Point: the size of G depends on the judge "
    "but every interval reaches zero. Do not rank the judges by which gives the better G.")
add("report.s7_10.post_hoc", "report", "7.10 Threats to Validity, bullet", "one bullet (a full "
    "sentence, no leading bullet)", "25-45", ["v3_local.judge_model", "v3_local.judge_label"],
    "The v3 agent judge was chosen after seeing agreement between judges (post hoc), because "
    "the local judge was unusable.")
add("report.s7_10.oracle", "report", "7.10 Threats to Validity, bullet", "one bullet", "25-45",
    ["v3_setup.question_oracle_model", "v3_setup.question_oracle.n_logged:int"],
    "The v3 question and oracle model is small and its identity is not recorded per database "
    "row; it is recorded only in the oracle log.")
add("report.s7_10.new_rows", "report", "7.10 Threats to Validity, bullet", "one bullet", "20-40",
    ["v3_design.n_new_rows:int"],
    "The {n_new_rows} rows added in v3 have no run by the original (Gemini) reviewer, so the two "
    "studies differ in reviewer and judge as well as in rows.")
add("report.s7_10.bot", "report", "7.10 Threats to Validity, bullet", "one bullet", "25-45",
    ["live_demo.n_prs:int"],
    "The live GitHub demonstration (Section 6.4) is {n_prs} constructed PRs in the authors' own "
    "sandbox repository, run from a laptop behind a tunnel on a free-tier quota; it shows the "
    "loop works but is not an evaluation, and behaviour on real third-party PRs at scale is "
    "untested.")
add("report.conclusion.v3", "report", "8. Conclusion, new paragraph after the findings "
    "paragraph", "one paragraph", "90-130", V3_INTENT[:7] + J_THREE + REALPR[:2]
    + ["live_demo.n_prs:int"],
    "The v3 replication on a local reviewer and the judge calibration: null result with a "
    "bound, effect size depends on the judge, v2 and v3 never pooled; what remains not done "
    "(human judge validation, labelling of the {n_prs} real PRs, permanent hosting and a run on "
    "real third-party PRs at scale) stated as not done. One clause may note that the bot has been "
    "demonstrated live on a sandbox repository ({live_demo.n_prs} PRs); no more.")

# ------------------------------------------------------------------------ deck
add("deck.demo.live", "deck", "Slide 14 (Project Demonstration), second text line under the two "
    "figures", "one bullet", "25-35", LIVE,
    LIVE_FRAME + " Compress to one or two sentences: the full loop (ask, answer, review) ran on "
    "real GitHub for {n_prs} sandbox PRs, from the command line and from the webhook bot; "
    "the answer changed the review ({pr2.verdict} on PR 2). A demonstration, not an evaluation.")
add("deck.abstract.v3", "deck", "Slide 4 (Abstract), end of the Result bullet", "one clause or "
    "sentence", "15-25", ["v3_setup.reviewer_model_name"] + _t("v3_local", "intent_all",
                                                              "gap_recovery", "gap_ci"),
    "Append: replicated on a {reviewer_model_name} local reviewer, G with its upper CI limit; "
    "null. Must fit one bullet line or two.")
add("deck.v3.replication", "deck", "Slide 14 (Experiments and Results 3/3), bullet 1",
    "one bullet", "20-35", V3_SETUP[:1] + V3_INTENT[:7],
    "Replication on a local 4B reviewer: intent floor -> treatment -> ceiling (pct), G, CI, p. "
    "Null with a bound.")
add("deck.v3.judges", "deck", "Slide 14, bullet 2", "one bullet", "20-35",
    J_V2_API_AGENT[:4] + J_V3_LLAMA[:4] + J_THREE + ["judges.models.api_v3"],
    "Judge check: AI judges agree on defects and false alarms, only moderately on intent; the "
    "local judge is unusable so the Claude agent judge is primary for v3 (post hoc). AI-vs-AI; "
    "not human validation.")
add("deck.v3.limits", "deck", "Slide 14, bullet 3", "one bullet", "20-35",
    V3_FUNNEL[:5] + V2_AGENT[:6],
    "Same verdict under a different judge, a different magnitude: v2 G under the agent judge; "
    "recall remains the limit (asked/answered/recovered).")
add("deck.conclusion.v3", "deck", "Slide 16 (Conclusion), new Found bullet (after the text "
    "\"Found: \")", "one sentence", "15-30", V3_SETUP[:1] + _t("v3_local", "intent_all",
                                                              "gap_recovery", "gap_ci"),
    "Replicated on a 4B local model: null result, G with upper CI limit.")

IDS = [e["id"] for e in SPEC]
assert len(IDS) == len(set(IDS)), "duplicate placeholder id"
