"""The text of the Project I report, as data.

Every number is read from paper/numbers.json (written by `python -m paper.collect`)
so the report, the deck and the paper cannot disagree with each other or with
the experiment log. `build_report.py` turns these blocks into the SCOPE template.

Block kinds:
    ("h2", text)                      section heading, e.g. "1.1 Background"
    ("h3", text)                      sub-section heading
    ("p", text)                       body paragraph
    ("lead", bold_lead, text)         paragraph opening with a bold phrase
    ("bullets", [text, ...])          bulleted list
    ("fig", file, caption, width_in)  figure, caption below
    ("table", caption, header, rows, widths_in)   table, caption above
    ("code", text, caption)           code listing
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from prose import fixed, numword, prose  # noqa: E402  (placeholder text: docs/prose_v3.json)

FIG = ROOT / "docs/figures"
N = json.loads((ROOT / "paper/numbers.json").read_text(encoding="utf-8"))
V2 = N["v2"]
T = V2["tests"]
F = V2["funnel"]
DET = N["detectors"]
MUT = N["mutants"]
# Second-model replication (v3) and judge calibration. Never pooled with V2.
V3, V2A, J = N["v3_local"], N["v2_agent_judge"], N["judges"]
G3 = N.get("v3_gemini") or {"available": False}
HUM = N.get("human") or {}
S3, D3, RP, DV = N["v3_setup"], N["v3_design"], N["realpr"], N["derived"]

TITLE = ("CLARIFYREVIEW: AMBIGUITY-AWARE INTENT CLARIFICATION FOR LLM-BASED "
         "PULL REQUEST CODE REVIEW")
TITLE_CASE = ("ClarifyReview: Ambiguity-Aware Intent Clarification for LLM-Based "
              "Pull Request Code Review")
STUDENTS = [("23BCE0225", "YASHIKA GUPTA"), ("23BCE0316", "PRATYAKSH GUPTA")]
# As listed in VIT's SCOPE research-guide list (January 2025).
GUIDE, DESIGNATION = "Dr. Arivoli A", "Associate Professor Sr. Grade 2"
HOD, HOD_DESIGNATION = "Dr. Boominathan P", "Professor & Head"
DEPARTMENT = "School of Computer Science and Engineering (SCOPE)"
N_TESTS = int(N["tests_passing"].split()[0])
N_TEST_FILES = N["test_files"]


def pct(x: float) -> str:
    return f"{round(x * 100)}%"


def pairs(n: int, lead: bool = True) -> str:
    """'One pair' / 'Three pairs' (sentence start) or 'none' / 'one' / 'three' (after 'and')."""
    if not lead:
        return "none" if n == 0 else numword(n)
    w = numword(n).capitalize()
    return f"{w} pair" if n == 1 else f"{w} pairs"


def frac(rate: float, n: int) -> str:
    return f"{round(rate * n)}/{n}"


IA, DM, FA = T["intent_all"], T["defect_mutant"], T["false_alarm_golden"]

# ------------------------------------------------------------------ abstract

ABSTRACT = [
    "Code review is a persistent bottleneck in software development, and there are a number of "
    "commercial tools available to address it. CodeRabbit, Qodo and Greptile now use large "
    "language models (LLMs) to review pull requests automatically. All of them explain their "
    "comments in natural language, so explanation alone is no longer a research contribution. "
    "They share one problem: each reviews a pull request in a single pass, makes inferences "
    "about what the developer wants to do, and comments on that inference. When the intent of a "
    "change is ambiguous, none of them pauses to ask, leading to false alarms on deliberate "
    "changes and overlooked defects on unintended ones.",

    "This project implements and tests a pull request reviewer named ClarifyReview that adds a "
    "decision before critique. A four-step pipeline consumes the change and resolves it to the "
    "symbols it affects, decides whether the amount of context provided is adequate, asks the "
    "author at most two targeted questions when it is not, and only then writes a structured "
    "review. There are four interchangeable ambiguity detectors: a fifteen-feature heuristic, a "
    "trained classifier, and two uncertainty detectors based on self-consistency and prompt "
    "perturbation. The single-pass baseline is the same pipeline with a detector that never "
    "asks, which isolates one stage. The system is a GitHub bot and a benchmark harness, and "
    f"has been subject to {N_TESTS} automated tests.",

    "The evaluation is a two-by-three ablation on SWE-bench Verified, with correct (golden) and "
    "execution-verified defective (mutant) patches, all reviewed with intent withheld (the "
    "floor), with intent withheld but with clarification (the treatment), and with full context "
    "(the ceiling). A pilot run demonstrated that withholding just the linked issue does not "
    "stop the intent from being found in the patch itself, so the manipulation was tightened to "
    "eliminate all natural-language statements of intent while leaving the code unchanged, and "
    f"{MUT['by_status']['verified']} defects were confirmed with the tests of each repository.",

    f"Over {IA['n']} complete instances ({V2['judged']} judged reviews), intent recovery was "
    f"{pct(IA['floor'])} at the floor, {pct(IA['treatment'])} with clarification and "
    f"{pct(IA['ceiling'])} at the ceiling, a gap recovery of {IA['gap_recovery']:.2f}, which is "
    f"not statistically significant at this sample size (McNemar p = {IA['mcnemar_p']:.2f}). "
    f"Tracing each instance pinpoints the limit exactly. The floor misread {F['floor_misses']} "
    f"changes; the detector asked about {F['detector_asked']} of them, the author answered "
    f"{F['author_answered']}, and in that case the treatment restored the intent the floor had "
    "lost. The bottleneck is therefore detector recall rather than the value of an answer. At "
    f"most {numword(DV['v2_defect_max_caught'])} of {numword(DV['v2']['defect_mutant']['n'])} "
    "injected defects were detected in any condition, including with full context, which puts "
    "the limit on defect detection in the reviewer model rather than in missing intent. The "
    "prototype is at technology readiness level 4, and a conference paper reporting these "
    "results has been prepared.",

    # Added for Review 3: second-model replication and judge calibration.
    prose("report.abstract.v3"),
]
SHOW_KEYWORDS = False  # the keywords line is left out of the abstract
KEYWORDS = ("Automated Code Review, Large Language Models, Intent Clarification, Ambiguity "
            "Detection, Uncertainty Quantification, Mutation Testing, Empirical Software "
            "Engineering")

ABBREVIATIONS = [
    ("API", "Application Programming Interface"),
    ("AST", "Abstract Syntax Tree"),
    ("CI", "Confidence Interval"),
    ("CLI", "Command Line Interface"),
    ("DFD", "Data Flow Diagram"),
    ("FR", "Functional Requirement"),
    ("JSON", "JavaScript Object Notation"),
    ("LLM", "Large Language Model"),
    ("NFR", "Non-Functional Requirement"),
    ("PR", "Pull Request"),
    ("REST", "Representational State Transfer"),
    ("SDG", "Sustainable Development Goal"),
    ("SWE-bench", "Software Engineering Benchmark"),
    ("TRL", "Technology Readiness Level"),
    ("UML", "Unified Modelling Language"),
]
SYMBOLS = [
    ("s", "Ambiguity score produced by a detector, in [0, 1]"),
    ("τ", "Detector threshold; the system asks when s ≥ τ"),
    ("G", "Gap recovery, (treatment − floor) / (ceiling − floor)"),
    ("κ", "Cohen's kappa, chance-corrected inter-rater agreement"),
    ("p", "Two-sided p-value of McNemar's exact test"),
    ("n", "Number of paired instances in a comparison"),
]

# ------------------------------------------------------------------ references

REFERENCES = [
    'F. Mu, X. Chen, L. Shi, S. Wang, and Q. Wang, "ClarifyGPT: Empowering LLM-based code '
    'generation with intention clarification," arXiv preprint arXiv:2310.10996, 2023.',
    'S. Fakhoury, A. Naik, G. Sakkas, S. Chakraborty, and S. K. Lahiri, "LLM-based test-driven '
    'interactive code generation: User study and empirical evaluation," IEEE Transactions on '
    'Software Engineering, vol. 50, no. 9, pp. 2254-2268, 2024.',
    'C. E. Jimenez, J. Yang, A. Wettig, S. Yao, K. Pei, O. Press, and K. Narasimhan, '
    '"SWE-bench: Can language models resolve real-world GitHub issues?," in Proc. International '
    'Conference on Learning Representations (ICLR), 2024.',
    'X. Wang, J. Wei, D. Schuurmans, Q. Le, E. Chi, S. Narang, A. Chowdhery, and D. Zhou, '
    '"Self-consistency improves chain of thought reasoning in language models," in Proc. '
    'International Conference on Learning Representations (ICLR), 2023.',
    'L. Kuhn, Y. Gal, and S. Farquhar, "Semantic uncertainty: Linguistic invariances for '
    'uncertainty estimation in natural language generation," in Proc. International '
    'Conference on Learning Representations (ICLR), 2023.',
    'A. Bacchelli and C. Bird, "Expectations, outcomes, and challenges of modern code review," '
    'in Proc. 35th International Conference on Software Engineering (ICSE), 2013, pp. 712-721.',
    'C. Sadowski, E. Söderberg, L. Church, M. Sipko, and A. Bacchelli, "Modern code review: A '
    'case study at Google," in Proc. 40th International Conference on Software Engineering: '
    'Software Engineering in Practice (ICSE-SEIP), 2018, pp. 181-190.',
    'R. Tufano, L. Pascarella, M. Tufano, D. Poshyvanyk, and G. Bavota, "Towards automating code '
    'review activities," in Proc. 43rd International Conference on Software Engineering (ICSE), '
    '2021, pp. 163-174.',
    'Z. Li, S. Lu, D. Guo, N. Duan, S. Jannu, G. Jenks, D. Majumder, J. Green, A. Svyatkovskiy, '
    'S. Fu, and N. Sundaresan, "Automating code review activities by large-scale pre-training," '
    'in Proc. 30th ACM Joint European Software Engineering Conference and Symposium on the '
    'Foundations of Software Engineering (ESEC/FSE), 2022, pp. 1035-1047.',
    'L. Zheng, W.-L. Chiang, Y. Sheng, S. Zhuang, Z. Wu, Y. Zhuang, Z. Lin, Z. Li, D. Li, E. P. '
    'Xing, H. Zhang, J. E. Gonzalez, and I. Stoica, "Judging LLM-as-a-judge with MT-Bench and '
    'Chatbot Arena," in Advances in Neural Information Processing Systems (NeurIPS), Datasets '
    'and Benchmarks Track, 2023.',
    'Y. Jia and M. Harman, "An analysis and survey of the development of mutation testing," '
    'IEEE Transactions on Software Engineering, vol. 37, no. 5, pp. 649-678, 2011.',
    'Q. McNemar, "Note on the sampling error of the difference between correlated proportions '
    'or percentages," Psychometrika, vol. 12, no. 2, pp. 153-157, 1947.',
    'J. Cohen, "A coefficient of agreement for nominal scales," Educational and Psychological '
    'Measurement, vol. 20, no. 1, pp. 37-46, 1960.',
    'J. R. Landis and G. G. Koch, "The measurement of observer agreement for categorical data," '
    'Biometrics, vol. 33, no. 1, pp. 159-174, 1977.',
    'OpenAI, "Introducing SWE-bench Verified," https://openai.com/index/introducing-swe-bench-'
    'verified/, 2024.',
    'Greptile, "Best AI code review tools 2026 - comparison benchmarks," '
    'https://www.greptile.com, 2026.',
    'Stork.AI, "Best AI code review tools 2026: CodeRabbit vs. Greptile vs. Qodo," '
    'https://www.stork.ai, 2026.',
    'Morph, "GitHub AI code review: 6 tools tested on real PRs," https://www.morphllm.com, 2026.',
]

# The literature summary is shared with the Review 3 deck (slide 5).
LITERATURE = [
    ("Mu et al., ClarifyGPT [1]",
     "Ask before generating code when requirements are ambiguous",
     "Code-consistency check flags ambiguity; LLM asks targeted questions; simulated and human users",
     "+ shows clarification helps / - single functions, no repository, generation only",
     "Clarification improves Pass@1 over single-pass generation"),
    ("Fakhoury et al., TiCoder [2]",
     "Clarify intent through tests rather than questions",
     "Generated tests posed as pass/fail queries; 15-person user study",
     "+ rigorous user study / - structured queries, greenfield tasks",
     "Better correctness judgement, lower cognitive load"),
    ("Jimenez et al., SWE-bench [3]",
     "Benchmark LLMs on real GitHub issues",
     "Issue-patch pairs from 12 Python repositories, verified by execution",
     "+ execution-based ground truth / - built for repair, no ambiguity condition",
     "Repository-scale tasks are far harder than synthetic ones"),
    ("Wang et al., Self-consistency [4]",
     "Use agreement across samples as a signal",
     "Sample several reasoning paths and aggregate",
     "+ simple, model-agnostic / - needs temperature and many calls",
     "Disagreement across samples tracks uncertainty"),
    ("Kuhn et al., Semantic uncertainty [5]",
     "Measure uncertainty in meaning, not wording",
     "Cluster sampled outputs by entailment, compute entropy",
     "+ ignores paraphrase / - cost of sampling and clustering",
     "Semantic entropy predicts errors better than token likelihood"),
    ("Tufano et al. [8]; Li et al., CodeReviewer [9]",
     "Automate code review comments",
     "Pre-trained transformers on review data",
     "+ large-scale / - single pass, lexical-overlap evaluation",
     "Comments can be generated; no mechanism to ask the author"),
    ("Zheng et al., LLM-as-a-judge [10]",
     "Use LLMs to score open-ended output",
     "Agreement of LLM judges with human preference",
     "+ scalable scoring / - position and self-preference bias",
     "Strong judges agree with humans about as often as humans agree"),
    ("Industry comparisons, 2026 [16]-[18]",
     "Compare deployed AI reviewers",
     "Benchmarks and hands-on tests on live pull requests",
     "+ current practice / - not peer-reviewed, vendor bias",
     "Tools differ in context depth; all are single-pass and never ask"),
]

# ------------------------------------------------------------------ chapters


def _frac(rate, n):
    return f"{round(rate * n)}/{n}"


def gemini_v3_blocks() -> list:
    """Section 7.10: the full v3 set on the original reviewer, from numbers.json."""
    if not G3.get("available") or not G3.get("tests", {}).get("intent_all"):
        return []
    t = G3["tests"]
    ia, dm, fa = t["intent_all"], t.get("defect_mutant"), t.get("false_alarm_golden")
    f = G3.get("funnel") or {}
    n = ia["n"]
    sig = "significant" if ia["mcnemar_p"] < 0.05 else "not statistically significant"
    rows = [["Intent recovered, all", _frac(ia["floor"], n), _frac(ia["treatment"], n),
             _frac(ia["ceiling"], n), f"{fixed(ia['mcnemar_p'], 2)}"]]
    for key, label in (("intent_golden", "Intent recovered, golden"),
                       ("intent_mutant", "Intent recovered, mutant"),
                       ("defect_mutant", "Defect caught, mutants"),
                       ("false_alarm_golden", "False alarm, golden")):
        if t.get(key):
            x = t[key]
            rows.append([f"{label} (n = {x['n']})", _frac(x["floor"], x["n"]),
                         _frac(x["treatment"], x["n"]), _frac(x["ceiling"], x["n"]),
                         f"{fixed(x['mcnemar_p'], 2)}"])
    out = [
        ("h2", "7.10 The Full v3 Set on the Original Reviewer"),
        ("p", f"The replication in Section 7.8 changed two things at once: the rows and the "
              f"reviewer. To separate them, the full v3 set of {D3['rows']} rows, which includes "
              f"every verified mutant, was also run on the original reviewer "
              f"({', '.join(G3.get('review_models') or ['the v2 reviewer'])}) with the same "
              f"question, oracle and judge models as the original study and the default detector "
              f"threshold. {G3['complete_triples']} of {D3['rows']} rows completed all three "
              f"conditions; the remaining {D3['rows'] - G3['complete_triples']} could not, because "
              f"the question model returned a server error on every attempt for them. "
              f"{G3['judged']} reviews were judged."),
        ("table", "Table 7.6 Judged outcomes of the full v3 set on the original reviewer",
         ["Measure", "Floor", "Treatment", "Ceiling", "McNemar p"], rows,
         [2.4, 0.95, 1.0, 0.95, 1.0]),
        ("p", f"Intent recovery was {pct(ia['floor'])} with intent withheld, {pct(ia['treatment'])} "
              f"with clarification and {pct(ia['ceiling'])} with full context: gap recovery "
              f"{fixed(ia['gap_recovery'], 2)}, 95% interval {fixed(ia['gap_ci'][0], 2)} to "
              f"{fixed(ia['gap_ci'][1], 2)}, McNemar p = {fixed(ia['mcnemar_p'], 2)}, {sig}. "
              f"{ia['discordant_treatment_better']} pairs favoured the treatment and "
              f"{ia['discordant_floor_better']} the floor."
              + (f" The floor missed intent on {f['floor_misses']} instances; the detector asked "
                 f"on {f['detector_asked']} of them, the author answered {f['author_answered']}, and "
                 f"the treatment recovered {f['treatment_recovered']}. Of the detector's "
                 f"{f['asked_total']} questions, {f['asked_total'] - f['detector_asked']} went to "
                 f"instances the floor already understood." if f else "")),
    ]
    dd = G3.get("discordant")
    if dd:
        out.append(("p", f"The improvement is therefore not evidence for clarification. Of the "
                         f"{dd['total']} pairs where floor and treatment disagreed, "
                         f"{dd['not_asked']} were instances on which the detector did not ask, so "
                         f"the two conditions sent the reviewer identical input; "
                         f"{dd['not_asked_treatment_better']} of those favoured the treatment and "
                         f"{dd['not_asked_floor_better']} the floor by chance alone. Only "
                         f"{dd['asked_treatment_better'] + dd['asked_floor_better']} discordant pair "
                         f"involved a question. Across the {G3['not_asked_pairs']} unasked pairs the "
                         f"reviewer's own run-to-run variation is as large as the effect the study "
                         f"was designed to detect, which is the main lesson of this run: a single "
                         f"review per condition cannot resolve a difference of this size."))
    if dm:
        out.append(("p", f"On the {dm['n']} verified mutants the reviewer caught "
                         f"{_frac(dm['floor'], dm['n'])} defects with intent withheld, "
                         f"{_frac(dm['treatment'], dm['n'])} with clarification and "
                         f"{_frac(dm['ceiling'], dm['n'])} with full context."))
    return out


def human_blocks() -> list:
    """Section 7.11: the two human steps, from their own result files."""
    hl, ht, hj = (HUM.get("labelling") or {}), (HUM.get("thresholds") or {}), \
        (HUM.get("judge_validation") or {})
    if not (hl.get("available") or hj.get("available")):
        return []
    # Tables are numbered in order, so this one follows Section 7.10's when that exists.
    tab = "Table 7.7" if gemini_v3_blocks() else "Table 7.6"
    out = [("h2", "7.11 Human Labelling and Judge Validation")]
    if hl.get("available"):
        txt = (f"Two annotators independently labelled all {hl['n']} code-only pull requests of "
               f"the classifier's training set as clear or unclear, following the codebook. They "
               f"agreed on {hl['n'] - hl['n_disagree']} ({pct(hl['observed_agreement'])}); Cohen's "
               f"kappa was {hl['kappa']:.2f} ({hl['reading']}), low despite the high agreement "
               f"because almost every pull request was labelled clear. ")
        if hl.get("n_adjudicated_by_ai"):
            txt += (f"The {hl['n_disagree']} disagreements were adjudicated by an AI model "
                    f"({hl['adjudicated_by']}) applying the same codebook, at the team's request, so "
                    f"those {hl['n_adjudicated_by_ai']} labels are not human judgements. ")
        if ht.get("available"):
            v = ht.get("values") or {}
            dev = ht.get("dev") or {}
            txt += (f"The labelled set has {ht.get('n_ambiguous', '?')} unclear examples out of "
                    f"{ht.get('n_labels', '?')}; the development split used to freeze thresholds "
                    f"holds {dev.get('n_ambiguous', '?')} of its {dev.get('n', '?')} rows. "
                    f"Thresholds frozen on it are {v.get('heuristic', 0):.2f} for "
                    f"the heuristic and {v.get('classifier', 0):.2f} for the classifier. With so "
                    f"few unclear examples the classifier is degenerate: it scores the ambiguous "
                    f"demonstration change at 0.00. The frozen heuristic threshold, being higher "
                    f"than the default, would make the detector ask less often, against the recall "
                    f"limit found in Section 7.3 and Section 7.10, so the ablations keep the default.")
        out.append(("p", txt))
    if hj.get("available"):
        m = hj["metrics"]
        rows = []
        for key, label in (("intent_recovered", "Intent recovered"),
                           ("defect_caught", "Defect caught"), ("false_alarm", "False alarm")):
            if key in m:
                x = m[key]
                rows.append([label, str(x["n"]), pct(x["percent_agreement_mean"]),
                             f"{x['kappa_mean']:.2f}", pct(x.get("human_yes_rate", 0)),
                             pct(x.get("judge_yes_rate", 0))])
        out.append(("p", f"The original study's judge was checked against {hj['n_scorers']} human "
                         f"scorers, each scoring a stratified sample of {m['intent_recovered']['n']} "
                         "of its reviews independently, without seeing the condition or the "
                         f"judge's answers ({tab})."))
        out.append(("table", f"{tab} Agreement between the judge and the human scorers",
                    ["Measure", "n", "Agreement", "Kappa", "Humans said yes", "Judge said yes"],
                    rows, [1.6, 0.5, 0.9, 0.7, 1.2, 1.1]))
        ir = m.get("intent_recovered") or {}
        out.append(("p", "On defects and false alarms the judge agrees with the humans almost "
                         "perfectly. On intent recovery it agrees on "
                         f"{pct(ir.get('percent_agreement_mean', 0))} of reviews, but kappa is near "
                         "zero: the humans judged intent recovered in "
                         f"{pct(ir.get('human_yes_rate', 0))} of reviews and the judge in "
                         f"{pct(ir.get('judge_yes_rate', 0))}, so the judge is the stricter of the "
                         "two and the intent recovery rates in this chapter are conservative."))
    return out

def chapters() -> list[tuple[str, list]]:
    ia, dm, fa = IA, DM, FA
    det = DET
    loc = N["loc"]
    ch = []

    # ---------------------------------------------------------------- 1
    ch.append(("INTRODUCTION", [
        ("h2", "1.1 Background"),
        ("p", "Reviewing code is a standard best practice in professional software development, a "
              "standard quality gate and a standard bottleneck [6], [7]. Reviewer availability, "
              "turnaround time and inconsistency between reviewers all delay delivery, and the cost "
              "increases as the number of team members increases. A class of commercial tools has "
              "sprouted up that uses large language models to review pull requests automatically: "
              "CodeRabbit, Qodo and Greptile are the most commonly used, and GitHub's own reviewer "
              "is in the same position."),
        ("p", "These tools have evolved into a similar design. A webhook is sent to them, they "
              "collect any context they can get their hands on (the diff and, in the better tools, "
              "the surrounding repository), and they create comments in natural language "
              "describing the problems they think they found. Independent 2026 comparisons report "
              "bug-catch rates high enough to be useful and low enough that trust in the output "
              "matters [16]-[18]."),
        ("p", "Since all of these tools already provide explanations, explanation quality alone "
              "no longer differentiates a research prototype from a shipping product. The question "
              "that is yet to be explored is the moment when a tool decides it has a good enough "
              "grasp of a change to be justified in critiquing it."),
        ("h2", "1.2 Motivations"),
        ("p", "All currently available tools perform a single-pass review of a pull request. Each "
              "reads the diff, infers the developer's intention and comments on that inference. "
              "When the diff is unambiguous this works. When it is not, for example when a "
              "validation check disappears without a linked issue and the commit message reads only "
              "\"fix\", the tool does not stop. It commits to one reading and comments as if that "
              "reading were established."),
        ("p", "There are two consequences. A false positive objects to a change that was "
              "intentional and correct, which costs the author time to justify it. A false negative "
              "passes over a true defect because, with no indication of what the change was for, "
              "nothing looked obviously wrong. Both teach developers that the output should not be "
              "blindly trusted, and a low signal-to-noise ratio is one of the most commonly reported "
              "reasons for turning off automated review."),
        ("p", "These tools do not do what a human reviewer does in the same situation: ask. The "
              "motivation for this project is that one well-aimed question, asked before the "
              "critique rather than after it, may regain much of the accuracy lost to missing "
              "context, and whether it does is an empirical question that had not been answered for "
              "code review."),
        ("h2", "1.3 Scope of the Project"),
        ("p", prose("report.s1_3.scope")),
        ("p", "The research scope is narrower still. Generating and explaining review comments is "
              "not claimed as novel. What is claimed is the mechanism that decides when to ask, "
              "implemented in four designs, together with empirical evidence on whether asking "
              "first changes what a reviewer understands and detects."),
        ("p", prose("report.s1_3.eval_scope")),
    ]))

    # ---------------------------------------------------------------- 2
    lit_rows = [list(r) for r in LITERATURE]
    ch.append(("PROJECT DESCRIPTION AND GOALS", [
        ("h2", "2.1 Literature Review"),
        ("p", "The existing literature covers four areas that are each well developed and "
              "relevant but rarely interwoven: automated code review, clarification-seeking in "
              "LLM-based programming assistants, uncertainty quantification, and the evaluation of "
              "generated text. Table 2.1 summarizes the works that influenced the design."),
        ("table", "Table 2.1 Summary of the literature reviewed",
         ["Paper", "Objective", "Methodology", "Pros / Cons", "Findings"], lit_rows,
         [1.25, 1.25, 1.45, 1.35, 1.3]),
        ("h3", "2.1.1 Automated code review"),
        ("p", "Bacchelli and Bird showed that the main outcome developers expect from review is "
              "finding defects, but that much of review effort actually goes into understanding "
              "the change [6]. Sadowski et al. found the same at Google, where review is "
              "lightweight and understanding the author's intent is the reviewer's first task "
              "[7]. Tufano et al. [8] and Li et al. [9] trained models to generate review "
              "comments, and current LLM-based products follow the same single-pass shape. None "
              "of these systems has a mechanism for resolving what a change is for before "
              "commenting on it."),
        ("h3", "2.1.2 Clarification-seeking in code generation"),
        ("p", "Mu et al. introduced ClarifyGPT, which detects ambiguous requirements through a "
              "code-consistency check and asks targeted questions before generating code [1]. "
              "Fakhoury et al. approached the same problem through tests, surfacing a generated "
              "test as a clarifying query; in a fifteen-person study participants judged "
              "generated code more accurately and reported lower cognitive load [2]. Both "
              "establish that clarification improves outcomes, and both concern greenfield "
              "generation rather than review of an existing change. A consistent finding across "
              "this work is that models do not ask unprompted; asking has to be scaffolded, and "
              "it has to be selective, because a system that interrupts on every input is "
              "unusable regardless of its accuracy."),
        ("h3", "2.1.3 Benchmarks and ground truth"),
        ("p", "SWE-bench pairs real GitHub issues with the patches that resolved them and the "
              "tests those patches make pass [3]; SWE-bench Verified is a 500-instance subset "
              "whose issues were validated by human annotators [15]. Two properties matter here. "
              "The accepted patch is known, so a review can be scored on whether it understood "
              "the problem the patch addressed; and the tests are known, so defective variants "
              "can be built whose defectiveness is verified by execution [11] rather than "
              "asserted."),
        ("h3", "2.1.4 Uncertainty quantification and evaluation"),
        ("p", "Self-consistency samples a model repeatedly and treats disagreement as a signal "
              "[4]; semantic uncertainty clusters samples by meaning before measuring dispersion, "
              "so that eight paraphrases are not mistaken for eight different answers [5]. These "
              "supply the basis for two of the four detectors. For scoring, LLM judges agree with "
              "human preference about as often as humans agree with each other, but show known "
              "biases, including a preference for their own output [10]; this is why the judge "
              "here is a different model family from the reviewer; it has been cross-checked "
              "against other AI judges and against two human scorers (Section 7.11)."),
        ("h2", "2.2 Research Gap"),
        ("p", "LLM-based pull request review is studied extensively in industry and "
              "clarification-seeking is studied extensively in academia, but the intersection is "
              "nearly empty. Every study showing that clarification helps does so for code "
              "generation or repair; every study of automated review concerns context retrieval, "
              "comment generation and precision. No existing system treats ambiguous intent as "
              "something to resolve before commenting rather than something to guess at."),
        ("p", "The stakes also differ. A wrong guess during generation costs a compiler cycle "
              "and is corrected automatically; a wrong guess during review costs a human "
              "reviewer's attention, and repeated wrong guesses cost the tool its credibility. "
              "Results from generation cannot simply be assumed to transfer."),
        ("p", "A second gap concerns evaluation. Lexical-overlap metrics measure prose rather "
              "than understanding, and organisational labels such as fixed or will-not-fix "
              "reflect scheduling as much as correctness. A credible evaluation of a review "
              "system needs ground truth that depends on neither."),
        ("lead", "Research question. ",
         "Does asking a clarifying question before generating review comments improve a "
         "reviewer's recovery of developer intent and its detection of defects, relative to a "
         "single-pass review of the same change under the same context?"),
        ("h2", "2.3 Objectives"),
        ("table", "Table 2.2 Objectives and their status at Review 3",
         ["No.", "Objective", "Status"],
         [["O1", "Design an ambiguity-detection mechanism for pull request review and compare "
                 "designs: heuristic, trained classifier, sampling and perturbation uncertainty",
           "Done. Four detectors built and three compared (Section 7.5); the classifier is "
           "trained on 300 human-labelled PRs but, with almost no unclear examples, is "
           "degenerate (Section 7.11)"],
          ["O2", "Build a four-stage clarify-then-review pipeline deployable as a GitHub bot",
           "Done. Pipeline, bot and CLI implemented and tested"],
          ["O3", "Construct an evaluation set from SWE-bench Verified with execution-verified "
                 "defective variants",
           f"Done. {MUT['by_status']['verified']} verified mutants; {V2['complete_triples']}-row "
           f"v2 study set and {D3['rows']}-row v3 set"],
          ["O4", "Run a 2 x 3 ablation and report the share of the ambiguity gap that "
                 "clarification recovers",
           f"Done (v2 and v3 local). Gap recovery {ia['gap_recovery']:.2f} on v2 and "
           f"{fixed(V3['tests']['intent_all']['gap_recovery'], 2)} on v3 (Chapter 7)"],
          ["O5", "Run a paired blind developer study of usefulness and trust",
           "Tooling built (blind study page, analysis)"],
          ["O6", "Produce a TRL 4 prototype and a paper for a Scopus-indexed conference",
           "Done. Prototype at TRL 4; conference paper prepared"],
          ["O7", f"Collect real pull requests in {numword(len(RP['languages']))} languages "
                 "for human labelling",
           f"Collected ({RP['n_prs']} pull requests, {RP['n_repos']} repositories)"]],
         [0.5, 3.6, 2.5]),
        ("h2", "2.4 Problem Statement"),
        ("p", "Existing LLM-based pull request reviewers infer developer intent from the diff in "
              "a single pass and comment on that inference, with no mechanism for recognising "
              "when the inference is unreliable. When the available context is insufficient to "
              "determine why a change was made, the system nonetheless commits to an "
              "interpretation, producing false positives on intentional changes and false "
              "negatives on genuine defects."),
        ("p", "The problem addressed is the absence of a mechanism that decides, per pull "
              "request, whether the available context is sufficient to review confidently, and "
              "that resolves the deficit by asking the author a targeted question when it is not. "
              "The mechanism must be selective: deciding when to stay silent is as much part of "
              "the problem as deciding when to ask."),
        ("h2", "2.5 Project Plan"),
        ("p", "The project runs over twenty-six weeks from 22 July 2026 (Figure 2.1). The "
              "pipeline was built first so that the detectors - the research component - had a "
              "full block from week 7 to week 12, and the evaluation was preceded by a pilot run "
              "whose findings changed the study design before the main run (Section 7.1)."),
        ("fig", "fig1_gantt.png", "Figure 2.1 Gantt chart of the project schedule", 6.3),
        ("p", "Two dependencies drove the ordering. The heuristic detector was built before the "
              "others because it is the baseline they must beat and because having it running "
              "end to end unblocked the clarification loop and the review generator. The "
              "developer study is the only task with an external dependency - recruited "
              "participants - and is therefore the one item scheduled to complete after this "
              "review."),
    ]))

    # ---------------------------------------------------------------- 3
    ch.append(("TECHNICAL SPECIFICATION", [
        ("h2", "3.1 Requirements"),
        ("h3", "3.1.1 Functional"),
        ("lead", "FR1 - Pull request ingestion: ", "The system shall retrieve the diff, commit "
         "messages and linked issue text for a pull request through the GitHub API, triggered by "
         "a webhook on pull request opened and synchronize events, or read a local diff file."),
        ("lead", "FR2 - Semantic diffing: ", "The system shall parse the diff into hunks and "
         "resolve changed lines to the functions, methods and classes they affect, detecting "
         "signature changes."),
        ("lead", "FR3 - Context assembly: ", "The system shall assemble a bounded, deterministic "
         "context under a fixed token budget, such that the same pull request always produces an "
         "identical context and fingerprint."),
        ("lead", "FR4 - Ambiguity detection: ", "The system shall produce an ask or proceed "
         "decision for each pull request with a numeric score, the threshold applied and a "
         "human-readable justification."),
        ("lead", "FR5 - Selective questioning: ", "The system shall generate at most two "
         "clarifying questions, each naming a specific file, line or symbol, and none when the "
         "detector proceeds."),
        ("lead", "FR6 - Clarification loop: ", "The system shall post its questions on the pull "
         "request, resume when the author replies, and fall back to a review flagged "
         "low-confidence if no reply arrives within a configurable timeout."),
        ("lead", "FR7 - Review generation: ", "The system shall produce findings as structured "
         "records - file, line, severity, category, claim, evidence, suggested fix and "
         "confidence - conditioned on any clarification received."),
        ("lead", "FR8 - Publication: ", "The system shall render its findings as a markdown "
         "comment on the pull request."),
        ("lead", "FR9 - Experiment logging: ", "The system shall persist every context "
         "fingerprint, decision, question, reply, finding, token count and latency to a "
         "database, so that the experiment record is a by-product of normal operation."),
        ("lead", "FR10 - Evaluation harness: ", "The system shall run the three experimental "
         "conditions over a benchmark set, score the reviews against ground truth, and produce "
         "the statistics reported in Chapter 7."),
        ("h3", "3.1.2 Non-Functional"),
        ("lead", "NFR1 - Determinism: ", "Ingestion shall be byte-deterministic; two runs over "
         "the same pull request produce identical fingerprints."),
        ("lead", "NFR2 - Condition equivalence: ", "With the detector forced to proceed, the "
         "baseline and treatment shall render byte-identical prompts, enforced by an automated "
         "test."),
        ("lead", "NFR3 - Selectivity: ", "The detector shall not ask on the majority of pull "
         "requests; ask rate is reported alongside every accuracy figure."),
        ("lead", "NFR4 - Non-blocking behaviour: ", "A pull request shall never be blocked "
         "waiting for a reply; timeout produces a flagged review, not an error."),
        ("lead", "NFR5 - Fault tolerance: ", "A failure on one pull request shall not end a "
         "batch run; transient provider errors are retried with exponential backoff and "
         "results are committed per instance."),
        ("lead", "NFR6 - Cost control: ", "The system shall run on free-tier model access, "
         "stop cleanly on an exhausted daily quota, and resume without repeating paid work."),
        ("lead", "NFR7 - Reproducibility: ", "Random seeds, thresholds and selection parameters "
         "are fixed and committed, and every reported number is regenerated from the "
         "experiment log by a script."),
        ("lead", "NFR8 - Maintainability: ", "Each detector implements one interface over one "
         "input type, so the review stage cannot observe which detector made a decision."),
        ("h2", "3.2 Feasibility Study"),
        ("h3", "3.2.1 Technical Feasibility"),
        ("p", "Every component relies on established technology: the GitHub API for pull request "
              "data, Python's ast module and tree-sitter grammars for symbol extraction, "
              "scikit-learn for the trained detector, SQLite for the experiment log and either a "
              "hosted or a local LLM for generation. No component requires a GPU, because no "
              "model is trained beyond a small classifier over fifteen features; a GPU is "
              "optional, for running the reviewer locally."),
        ("p", "The principal technical risk was verifying injected defects, which requires "
              "running each benchmark repository's tests. It was resolved without the "
              "containerised SWE-bench harness: sympy's tests were run in a local Python 3.9 "
              f"environment, yielding {MUT['by_status']['verified']} verified mutants from "
              f"{MUT['attempted']} instances (Section 5.2)."),
        ("h3", "3.2.2 Economic Feasibility"),
        ("p", prose("report.s3_2_2.economic")),
        ("h3", "3.2.3 Social Feasibility"),
        ("p", "The system is designed around the concern that would prevent adoption: an "
              "over-eager questioner is more irritating than an occasional wrong guess, so "
              "selectivity is measured rather than claimed. The system is advisory; it comments "
              "and never merges, closes or modifies code, so a human keeps every consequential "
              "decision. The developer study uses public open-source pull requests, records no "
              "personal data beyond programming experience, and runs under informed consent."),
        ("h2", "3.3 System Specification"),
        ("h3", "3.3.1 Hardware Specification"),
        ("table", "Table 3.1 Hardware specification",
         ["Component", "Specification", "Purpose"],
         [["Processor", "Apple M-series or x86-64, 4 cores minimum",
           "Diff parsing, symbol extraction, running repository test suites"],
          ["Memory (RAM)", "16 GB", "Repository checkouts during defect verification"],
          ["Storage", "20 GB free", "Benchmark checkouts, test environment, experiment log"],
          ["GPU", "Optional; the local (v3) run used an RTX 3050 laptop GPU",
           "Local reviewer inference through Ollama; hosted inference needs none"],
          ["Network", "Broadband", "GitHub API and model API calls"]],
         [1.4, 2.4, 2.8]),
        ("h3", "3.3.2 Software Specification"),
        ("table", "Table 3.2 Software specification",
         ["Category", "Selection", "Role in the system"],
         [["Operating system", "macOS 14+, Ubuntu 22.04+ or Windows 11",
           "Development and evaluation host (the v3 run and the bot tests ran on Windows 11)"],
          ["Language", "Python 3.11+ (3.9 for sympy test execution)",
           "Entire system and harness"],
          ["Review model", "Google gemini-3.5-flash-lite (free tier)",
           "Stage 4 review generation; uncertainty-detector sampling"],
          ["Question, oracle, judge (v2)", "Google gemma-4-31b-it (free tier)",
           "Clarifying questions, simulated author, API judge"],
          ["Alternative backend", "Anthropic Claude API",
           "Second provider behind the same interface"],
          ["Local backend", f"Ollama, {S3['reviewer_model_name']}",
           "Reviewer for the v3 replication; no network, no cost"],
          ["Question and oracle (v3)", f"{S3['question_oracle_model']} via Ollama",
           "Clarifying questions and simulated author in the v3 replication"],
          ["Judges", f"{J['models']['api_v2']} (v2 API judge); Claude Sonnet agents; Gemini "
                     f"web app ({J['gemini_sample']['n']}-run sample)",
           "Scoring and AI-vs-AI calibration (Section 7.9)"],
          ["LLM clients", "google-genai, anthropic, httpx (Ollama)", "Provider access"],
          ["Code analysis", "Python ast; tree-sitter grammars for JavaScript, TypeScript, Java, "
                            "C, C++ and Rust", "Semantic diffing"],
          ["Machine learning", "scikit-learn, NumPy, SciPy",
           "Classifier, dispersion measures, statistics"],
          ["Web framework", "FastAPI, Uvicorn", "GitHub App webhook receiver"],
          ["Database", "SQLite", "Experiment log"],
          ["Benchmark", "SWE-bench Verified (Hugging Face datasets)", "Ground truth"],
          ["Testing", "pytest", f"{N_TESTS} automated tests"]],
         [1.6, 2.4, 2.6]),
    ]))

    # ---------------------------------------------------------------- 4
    ch.append(("DESIGN APPROACH AND DETAILS", [
        ("h2", "4.1 System Architecture"),
        ("p", "The system is organised into four stages (Figure 4.1). The design rests on one "
              "structural change relative to existing tools: a branch point inserted before "
              "comment generation. Everything downstream of that branch is comparable to what "
              "commercial tools already do; the research effort is concentrated on the branch."),
        ("fig", "fig2_architecture.png",
         "Figure 4.1 System architecture: four stages with the decision point at Stage 2", 6.3),
        ("lead", "Stage 1 - Ingestion: ", "Triggered by a webhook or a local diff, this stage "
         "parses the diff into hunks and resolves them to symbols: rather than reporting that "
         "lines 40 to 48 changed, it reports that the function validate_user was modified and "
         "whether its signature changed. The context is assembled in a deterministic order and "
         "truncated to a fixed budget, so identical input always yields an identical prompt."),
        ("lead", "Stage 2 - Ambiguity detector: ", "The research component. It emits an ask or "
         "proceed decision with a score, the threshold applied and a justification. Four designs "
         "share one interface. The heuristic combines fifteen diff features - missing linked "
         "issue, generic commit message, removed guard, no test alongside, public symbol touched, "
         "deletion ratio and others - as weighted evidence and costs nothing at inference time. "
         "The classifier learns weights over the same features from labelled pull requests. The "
         "two uncertainty detectors sample eight one-sentence hypotheses about what the change "
         "is for - by temperature sampling, or by perturbing the prompt - and score their "
         "dispersion and semantic entropy."),
        ("lead", "Stage 3 - Clarification loop: ", "When Stage 2 asks, this stage generates at "
         "most two questions, each required by its output schema to name a file, line or symbol, "
         "so the model cannot fall back on asking the author to explain the pull request. The "
         "questions go to a Responder: on GitHub it posts a comment and waits; in the benchmark "
         "it is the simulated author. On timeout the pipeline proceeds and flags the review "
         "low-confidence."),
        ("lead", "Stage 4 - Review generator: ", "Produces structured findings conditioned on any "
         "clarification received. Markdown rendering happens only at the end, so evaluation "
         "scores findings mechanically rather than parsing prose."),
        ("p", "Two design decisions protect the validity of the evaluation. The single-pass "
              "baseline is not separate code: it is the same pipeline with a detector that never "
              "asks, and a test asserts that both conditions then render byte-identical prompts. "
              "And production and benchmark differ only in which Responder is plugged in, so the "
              "experiment exercises exactly the code that would be deployed."),
        ("h2", "4.2 Design"),
        ("h3", "4.2.1 Data Flow Diagram"),
        ("p", "The context diagram shows ClarifyReview mediating between the pull request author "
              "and the services it depends on; the level 1 decomposition expands it into the four "
              "processes of the architecture and their two data stores (Figure 4.2)."),
        ("fig", "fig3_dfd.png", "Figure 4.2 Data flow diagram: level 0 and level 1", 6.0),
        ("p", "The flow from process 2.0 to 3.0, labelled ask, is the branch that distinguishes "
              "this system from single-pass review; when the detector proceeds, that flow is "
              "absent. The flow from process 4.0 into the experiment log carries the complete "
              "record of the run, which is how the raw data for Chapter 7 accumulated."),
        ("h3", "4.2.2 Use Case Diagram"),
        ("p", "The system serves two actors: the pull request author, who interacts through "
              "GitHub in the ordinary course of work, and the researcher, who configures and "
              "evaluates it (Figure 4.3). Answering a clarifying question is the one use case no "
              "deployed tool offers, and it is optional: an author who ignores the question still "
              "receives a review, marked lower-confidence."),
        ("fig", "fig4_usecase.png", "Figure 4.3 Use case diagram", 5.6),
        ("h3", "4.2.3 Class Diagram"),
        ("p", "The class diagram reflects the implementation (Figure 4.4). The detector classes "
              "share one abstract base, so the pipeline never learns which detector is installed. "
              "PRContext is the single input every stage reads, and the Responder protocol is the "
              "substitution point between production and benchmark."),
        ("fig", "fig5_class.png", "Figure 4.4 Class diagram of the implemented system", 6.3),
        ("h3", "4.2.4 Sequence Diagram"),
        ("p", "Figure 4.5 traces a pull request the detector flags as ambiguous: a null check "
              "removed with no linked issue and the commit message \"fix\". The detector scores "
              "it 0.889 against a threshold of 0.50, the loop asks, and the review is written "
              "from the author's stated intent rather than from a guess."),
        ("fig", "fig6_sequence.png", "Figure 4.5 Sequence diagram for an ambiguous pull request",
         6.3),
    ]))

    # ---------------------------------------------------------------- 5
    module_rows = [
        ["Ingestion", "ingest/diff.py, semantic.py, context.py, builder.py",
         "Diff parsing, symbol resolution (Python AST; tree-sitter for six more languages), "
         "deterministic context and fingerprint"],
        ["Detection", "detect/heuristic.py, classifier.py, uncertainty.py, features.py",
         "Four detectors behind one interface; fifteen-feature extractor"],
        ["Clarification", "clarify/question.py, loop.py",
         "Targeted question generation; Responder protocol with GitHub, oracle and null "
         "implementations"],
        ["Review", "review/generator.py, render.py",
         "Structured findings; markdown rendering"],
        ["Pipeline", "pipeline.py", "Composes the stages; builds the three conditions"],
        ["LLM layer", "llm/client.py, providers/gemini_backend.py, anthropic_backend.py, "
                      "ollama_backend.py",
         "Provider-independent facade over Gemini, Anthropic and local Ollama; retries, "
         "timeouts, quota handling, JSON recovery"],
        ["GitHub bot", "gh/app.py, client.py, auth.py, settings.py",
         "Signed-webhook receiver, API client, durable parked-run handling"],
        ["Storage", "store/db.py", "SQLite experiment log; parked runs, posted reviews, "
                                   "webhook deliveries"],
        ["CLI", "cli.py", "ingest, detect, review, replay, models, serve"],
        ["Benchmark", "experiments/build_dataset.py, build_study_set.py, mutate.py, "
                      "verify_mutants.py, fetch_prs.py",
         "Instance selection, mutation operators, execution verification; real pull request "
         "fetching for the labelling set"],
        ["Ablation", "experiments/strip.py, oracle.py, run_matrix.py",
         "Intent stripping, simulated author, 2 x 3 runner"],
        ["Scoring", "experiments/judge.py, external_judge.py, analyze.py, compare_detectors.py",
         "LLM judge, external-judge export, import and comparison, statistics, detector "
         "comparison"],
        ["Human studies", "experiments/label_tool.py, study/",
         "Labelling sheet and agreement; blind developer-study page"],
        ["Reporting", "paper/collect.py, build_paper.js, docs/",
         "Numbers, figures, paper and this report, generated from the log"],
    ]
    test_desc = {
        "test_diff.py": "Unified diff parsing and hunk arithmetic",
        "test_semantic.py": "Line-to-symbol resolution and signature changes",
        "test_types.py": "Context fingerprint determinism and schema limits",
        "test_features.py": "Feature extraction from diffs",
        "test_heuristic.py": "Ask on ambiguous, proceed on clear changes",
        "test_uncertainty.py": "Dispersion and entropy scoring",
        "test_pipeline.py": "Baseline equivalence, timeout fallback, fault isolation",
        "test_llm_policy.py": "Model roles, provider rules, independent judge",
        "test_providers.py": "Gemini/Anthropic backends, retries, quota, timeouts",
        "test_store.py": "Experiment log round-trip and cascades",
        "test_experiments.py": "Stripping, mutation, statistics, oracle isolation",
        "test_tooling.py": "Judge agreement, oracle audit, sweeps, replay",
        "test_cli_encoding.py": "CLI output survives a legacy Windows code page",
        "test_collect_v3.py": "Judge-copy helper and collection of the v3 numbers",
        "test_external_judge.py": "External-judge export, import, comparison, re-analysis",
        "test_features_polyglot.py": "Feature extraction beyond Python; Python invariance snapshot",
        "test_fetch_prs.py": "Real pull request fetching against a fake GitHub API",
        "test_finish.py": "Result-file plumbing for the human steps",
        "test_gh_client.py": "GitHub API client against a mock transport",
        "test_gh_webhook_e2e.py": "Live bot end to end: signed webhooks, parking, timeouts, replay",
        "test_judge_context.py": "Judge context renders findings and ground truth",
        "test_live_gaps.py": "Live-tool defaults: thresholds, body-reference issues, Python symbols without a checkout",
        "test_judge_study_prep.py": "Judge-validation and developer-study preparation",
        "test_labelling_prep.py": "Labelling-set preparation; never writes a label",
        "test_ollama_backend.py": "Ollama backend against a mock transport",
        "test_prose.py": "Prose placeholders: formats, fail-loud rule, ids kept in step",
        "test_parked_store.py": "Durable bot state: parked runs, posted reviews, deliveries",
        "test_semantic_polyglot.py": "Symbol extraction for six further languages",
        "test_study_set_superset.py": "The v3 study set contains the v2 set",
    }
    test_rows = []
    for path, count in N["tests_by_file"].items():
        name = path.rsplit("/", 1)[-1]
        if name not in test_desc:  # a new test file must get a description here
            raise KeyError(f"no description for {name} in report_content.test_desc")
        test_rows.append([name, str(count), test_desc[name]])
    ch.append(("METHODOLOGY AND TESTING", [
        ("h2", "5.1 Module Description"),
        ("p", f"The implementation comprises {loc['src']:,} lines in the core package, "
              f"{loc['experiments']:,} lines of experiment harness and {loc['tests']:,} lines of "
              f"tests. Table 5.1 lists the modules."),
        ("table", "Table 5.1 Modules of the implementation", ["Module", "Files", "Responsibility"],
         module_rows, [1.2, 2.6, 2.8]),
        ("h3", "5.1.1 Ingestion"),
        ("p", "The diff parser reads unified diffs into hunks with exact line arithmetic. "
              + prose("report.s5_1_1.extraction") +
              " The context builder orders every section deterministically and "
              "computes a SHA-256 fingerprint, which the ablation uses to prove that two "
              "conditions saw the same input."),
        ("h3", "5.1.2 Ambiguity detectors"),
        ("p", "All detectors implement score(context) returning a value in [0, 1], and a shared "
              "decide() compares it with a threshold loaded from a frozen file, so the threshold "
              "comparison happens in one place. The heuristic normalises its score as the "
              "fraction of available evidence present, so it reads as \"how many ambiguity "
              "signals fired\". The uncertainty detectors embed the eight intent hypotheses and "
              "combine mean pairwise dispersion with the entropy of their semantic clusters."),
        ("h3", "5.1.3 Clarification loop and review generator"),
        ("p", "Questions and reviews are requested as JSON validated against Pydantic schemas. "
              "The question schema requires a target, which is what keeps questions specific. "
              "The loop is written against the Responder protocol, so the GitHub implementation "
              "(post and poll for a reply), the benchmark oracle and a null responder are "
              "interchangeable."),
        ("h3", "5.1.4 LLM provider layer"),
        ("p", "A facade exposes structured() and text() calls and hides provider differences. "
              "Running a long study on free-tier access shaped this layer: transient 503 and "
              "per-minute 429 errors are retried with exponential backoff and jitter, a per-day "
              "quota error fails fast so retries do not burn quota, requests time out after "
              "180 s, malformed JSON is recovered and re-validated, and the model that actually "
              "served each call is recorded. " + prose("report.s5_1_4.ollama")),
        ("h3", "5.1.5 GitHub bot"),
        ("p", prose("report.s5_1_5.bot")),
        ("h2", "5.2 Evaluation Methodology"),
        ("h3", "5.2.1 Study design"),
        ("p", "Each instance is reviewed in three conditions by the same reviewer model with the "
              "same prompt template (Figure 5.1). The floor and the treatment receive "
              "byte-identical code and differ only in whether Stages 2 and 3 run; the runner "
              "asserts this for every instance. Gap recovery G = (treatment - floor) / (ceiling - "
              "floor) is the share of the context-induced loss that clarification restores."),
        ("fig", "fig11_design.png", "Figure 5.1 The two-by-three study design", 6.3),
        ("h3", "5.2.2 Withholding intent"),
        ("p", "Version 1 of the manipulation removed the linked issue, title, description and "
              "commit messages. The pilot showed this was insufficient (Section 7.1), so version "
              "2 also removes every comment, trailing comment and docstring that the patch adds, "
              "leaving every line of code untouched. Only docstrings opened on an added line are "
              "removed, a rule adopted after an earlier version deleted real code in a hunk that "
              "began inside an existing docstring; a regression test guards it."),
        ("h3", "5.2.3 Execution-verified defects"),
        ("p", "Correct patches measure false alarms but not detection, so defects are injected "
              "into the lines a golden patch adds using six operators (invert comparison, negate "
              "condition, flip constant, drop guard, swap boolean operator, off-by-one). A mutant "
              "is kept only if the repository's FAIL_TO_PASS tests pass with the golden patch and "
              "fail with the mutant. Figure 5.2 shows the yield."),
        ("fig", "fig10_mutants.png", "Figure 5.2 Yield of execution-verified mutants on sympy",
         5.6),
        ("h3", "5.2.4 Instance selection"),
        ("p", f"The study set has {N['v2_design']['rows']} rows: "
              f"{numword(N['v2_design']['arms']['mutant/mutant'])} sympy instances reviewed "
              f"both as the golden patch and as its verified mutant, and "
              f"{numword(N['v2_design']['arms']['golden/golden'])} further golden "
              "patches from xarray, sphinx, astropy, django, pylint, pytest and scikit-learn. "
              "Instances were chosen hardest-first by SWE-bench's own difficulty annotation, an "
              "attribute assigned by the benchmark's annotators rather than by our detector, so "
              "selection does not favour the detector being evaluated."),
        ("h3", "5.2.5 Simulated author and judge"),
        ("p", "When the treatment asks, a simulated author answers. It sees only the withheld "
              "issue text and commit messages - never the diff, the defect, or whether one "
              "exists - and must decline when its notes do not cover the question. Every "
              "exchange is logged with its prompt version for a leakage audit. Reviews are "
              "scored by an LLM judge from a different model family than the reviewer, on three "
              "checklist questions: was the intent recovered, was the injected defect caught, "
              "and was a false alarm raised on correct code."),
        ("p", prose("report.s5_2_5.calibration")),
        ("h3", "5.2.6 Statistical analysis"),
        ("p", "Paired binary outcomes are compared with McNemar's exact test [12] and gap "
              "recovery is reported with a bootstrap confidence interval. Agreement between "
              "human scorers and the judge, and between the two labellers of the classifier's "
              "training set, is measured with Cohen's kappa [13] and read on the Landis-Koch "
              "scale [14]."),
        ("h3", "5.2.7 Replication on a local reviewer (v3)"),
        ("p", prose("report.s5_2_7.v3_design")),
        ("h2", "5.3 Testing"),
        ("p", f"The system is covered by {N_TESTS} automated tests in {numword(N_TEST_FILES)} "
              f"files (Table 5.2), all of which run offline in about "
              f"{numword(DV['tests_seconds'])} seconds. Tests were written for the "
              "properties the study's validity rests on, not only for function behaviour: "
              "determinism of ingestion, byte-identical prompts between baseline and treatment, "
              "that the oracle never sees the diff, and that prose stripping never alters code."),
        ("table", "Table 5.2 The automated test suite", ["Test file", "Tests", "Property protected"],
         test_rows, [1.8, 0.6, 4.2]),
        ("fig", "fig14_tests.png", "Figure 5.3 The test suite passing", 4.2),
        ("h3", "5.3.1 Defects found by running against the live service"),
        ("p", "A passing offline suite did not catch everything. Table 5.3 lists defects that "
              "appeared only against the live provider; each was fixed and given a regression "
              "test."),
        ("table", "Table 5.3 Defects found in live runs and their fixes",
         ["Defect", "Effect", "Fix"],
         [["Hidden reasoning tokens exhausted the simulated author's 400-token budget",
           "Every answer empty; treatment silently equal to floor",
           "Budget raised to 4,000; empty answers logged"],
          ["Stalled HTTP request after a 500 error", "A run blocked for over ten minutes",
           "180 s timeout; timeouts retried"],
          ["Per-day quota errors retried like per-minute ones", "Each refusal cost five requests",
           "Fail fast on per-day quota"],
          ["Results held in one transaction", "A crash would lose a whole run",
           "Commit per instance; resume flag"],
          ["Concurrent writers on the log", "database is locked killed a judge pass",
           "60 s busy timeout"],
          ["Model returned JSON with leading whitespace", "Valid reviews rejected",
           "Recover and re-validate against the schema"]],
         [2.6, 2.0, 2.0]),
        ("p", "End-to-end tests of the GitHub bot against a fake GitHub, driven through "
              "signed webhooks, found further defects in its webhook path, all fixed: a reply "
              "resumed the review but the log recorded the run as never having asked; a pull "
              "request whose author never replied waited indefinitely; running under the "
              "author's own token, the bot read its own question as the answer; and a failure "
              "to generate the question left the pull request with no review. Parked runs now "
              "persist in SQLite and survive restarts, a sweep finishes them at the timeout, "
              "hidden markers identify every comment the bot posts, the recorded detector "
              "decision is replayed on resumption, and a failed question falls back to a "
              "single-pass review that says why."),
    ]))

    # ---------------------------------------------------------------- 6
    ch.append(("PROJECT DEMONSTRATION", [
        ("p", "The demonstration runs from a single script and needs no API key: Stages 1 and 2 "
              "run live, and Stages 3 and 4 are replayed from the study's experiment log, so "
              "nothing depends on a model provider being available during a presentation."),
        ("code", "$ git clone https://github.com/Praty0512/clarify-review && cd clarify-review\n"
                 "$ python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'\n"
                 "$ ./demo.sh            # all four stages, offline, about ten seconds\n"
                 "$ ./demo.sh --full     # Stages 3-4 live; needs GEMINI_API_KEY\n"
                 "\n"
                 "# Windows (PowerShell)\n"
                 "> python -m venv .venv; .venv\\Scripts\\pip install -e \".[dev]\"\n"
                 "> .\\demo.ps1           # same demonstration, offline\n"
                 "> .\\demo.ps1 -Full     # Stages 3-4 live; needs GEMINI_API_KEY",
         "Listing 6.1 Running the demonstration"),
        ("h2", "6.1 Stages 1 and 2: ask, and knowing when not to"),
        ("p", "The first pull request removes a null check, has no linked issue and the commit "
              "message \"fix\". Ingestion reports that the function validate_user was modified "
              "and prints a stable fingerprint. The heuristic detector fires seven rules and "
              "scores 0.889 against a threshold of 0.50, so it asks. The second pull request is "
              "well described and carries a regression test; the same detector scores 0.296 and "
              "proceeds (Figure 6.1). The second case matters as much as the first: a tool that "
              "asks on every pull request gets switched off."),
        ("fig", "fig12_demo_detect.png", "Figure 6.1 Stage 2 asks on an ambiguous change and "
                                         "proceeds on a clear one", 6.3),
        ("h2", "6.2 Stages 3 and 4: a recorded run from the study"),
        ("p", "clarifyreview replay prints one study instance in all three conditions "
              "(Figure 6.2). In sympy-12481 the patch lets the Permutation constructor accept "
              "non-disjoint cycles. Without its issue text the single-pass reviewer read the "
              "change as \"tidy up permutation instantiation logic\" - the intent was missed. "
              "ClarifyReview's detector scored the stripped change 0.556 and asked whether "
              "removing the specialised error was intended. The simulated author answered that "
              "non-disjoint cycles should be accepted and applied left to right, and the "
              "resulting review matched the full-context reading. The judge scored intent "
              "recovered for the treatment and the ceiling, and not for the floor."),
        ("fig", "fig13_demo_replay.png", "Figure 6.2 Replay of sympy-12481 across the three "
                                         "conditions", 6.3),
        ("h2", "6.3 Deployment as a GitHub bot"),
        ("p", "clarifyreview serve starts the FastAPI webhook receiver for a GitHub App. On a "
              "pull request event it runs the pipeline; if the detector asks, it posts the "
              "questions as a comment and waits for the author's reply, with a configurable "
              "timeout after which it reviews anyway and marks the review low-confidence. "
              "clarifyreview review runs the same pipeline from the command line on a local diff "
              "or a live pull request."),
        ("p", prose("report.s6_3.status")),
        ("h2", "6.4 A live run on GitHub"),
        ("p", prose("report.s6_4.live")),
    ]))

    # ---------------------------------------------------------------- 7
    pc = V2["per_condition"]
    tk = N["v2_tokens"]
    pc3 = V3["per_condition"]
    t3 = V3["tests"]
    ia3, dm3, fa3 = t3["intent_all"], t3["defect_mutant"], t3["false_alarm_golden"]
    ia_n, ig_n, im_n = ia["n"], T["intent_golden"]["n"], T["intent_mutant"]["n"]
    ch.append(("RESULT AND DISCUSSION", [
        ("h2", "7.1 Pilot Run and the Design Correction"),
        ("p", f"A pilot on 2 September 2026 ran the ablation over {N['pilot']['attempted']} "
              f"SWE-bench Verified instances from ten repositories with manipulation version 1; "
              f"{N['pilot']['complete_triples']} completed all three conditions before the daily "
              "free-tier quota ran out. Intent recovery was 100 per cent in every condition. With "
              "the floor equal to the ceiling there was no gap for clarification to close."),
        ("p", "Inspection showed why: golden patches state their purpose in the code, comments "
              "and docstrings they add. The flask instance adds an error whose message names the "
              "rule being enforced, so withholding the issue removed nothing a reader needed. "
              "Three changes followed - the version 2 manipulation, the execution-verified "
              "mutant arm, and difficulty-ordered instance selection - all made before the main "
              "run."),
        ("h2", "7.2 Main Study Results"),
        ("p", f"All {V2['complete_triples']} rows completed all three conditions and all "
              f"{V2['judged']} reviews were judged (Table 7.1, Figure 7.1)."),
        ("table", "Table 7.1 Judged outcomes of the main study (manipulation version 2)",
         ["Measure", "Floor", "Treatment", "Ceiling", "McNemar p"],
         [[f"Intent recovered, all (n = {ia_n})", frac(ia["floor"], ia_n),
           frac(ia["treatment"], ia_n), frac(ia["ceiling"], ia_n), f"{ia['mcnemar_p']:.2f}"],
          [f"Intent recovered, golden (n = {ig_n})", frac(T["intent_golden"]["floor"], ig_n),
           frac(T["intent_golden"]["treatment"], ig_n), frac(T["intent_golden"]["ceiling"], ig_n),
           f"{T['intent_golden']['mcnemar_p']:.2f}"],
          [f"Intent recovered, mutant (n = {im_n})", frac(T["intent_mutant"]["floor"], im_n),
           frac(T["intent_mutant"]["treatment"], im_n), frac(T["intent_mutant"]["ceiling"], im_n),
           f"{T['intent_mutant']['mcnemar_p']:.2f}"],
          [f"Defect caught ({dm['n']} mutants)", frac(dm["floor"], dm["n"]),
           frac(dm["treatment"], dm["n"]), frac(dm["ceiling"], dm["n"]),
           f"{dm['mcnemar_p']:.2f}"],
          [f"False alarm ({fa['n']} golden)", frac(fa["floor"], fa["n"]),
           frac(fa["treatment"], fa["n"]), frac(fa["ceiling"], fa["n"]),
           f"{fa['mcnemar_p']:.2f}"],
          ["Mean latency per review", f"{pc['stripped_plain']['ms'] / 1000:.1f} s",
           f"{pc['stripped_clarify']['ms'] / 1000:.1f} s", f"{pc['full_plain']['ms'] / 1000:.1f} s",
           "-"]],
         [2.4, 0.95, 1.0, 0.95, 1.0]),
        ("fig", "fig7_results.png", "Figure 7.1 Outcomes by condition", 6.3),
        ("p", f"Withholding all natural-language intent lowered intent recovery from "
              f"{pct(ia['ceiling'])} to {pct(ia['floor'])}: the version 2 manipulation opened a "
              f"gap where version 1 opened none. Clarification raised recovery to "
              f"{pct(ia['treatment'])}, a gap recovery of {ia['gap_recovery']:.2f} with a 95% "
              f"bootstrap interval of {ia['gap_ci'][0]:.2f} to {ia['gap_ci'][1]:.2f}. "
              f"{pairs(ia['discordant_treatment_better'])} "
              f"favoured the treatment and {pairs(ia['discordant_floor_better'], False)} the floor "
              f"(McNemar p = {ia['mcnemar_p']:.2f}). "
              "The effect is in the hypothesised direction and is not statistically significant; "
              "at this sample size it could not have been, because only pairs where the "
              "detector asked can differ for a reason other than sampling variation."),
        ("h2", "7.3 Where the Effect Is Lost"),
        ("p", "The treatment can improve on the floor only for an instance the floor got wrong, "
              "that the detector flagged, and whose author answered. Counting each step "
              "(Figure 7.2) shows which one limits the result."),
        ("fig", "fig8_funnel.png", "Figure 7.2 Tracing each instance from floor miss to recovery",
         6.0),
        ("p", f"The floor missed the intent of {F['floor_misses']} changes. The detector asked on "
              f"{F['detector_asked']} of them, the author answered {F['author_answered']} "
              f"substantively, and the treatment recovered intent in "
              f"{F['treatment_recovered']} - sympy-12481, the case shown in Chapter 6. The other "
              f"flagged miss (scikit-learn-25102) received a refusal: the question concerned a "
              f"parameter the issue text never mentions. Of the detector's {F['asked_total']} "
              f"questions overall, {F['asked_total'] - F['detector_asked']} went to instances the "
              "floor already understood, where an answer cannot improve intent recovery."),
        ("p", "Where clarification was given the chance, it worked; but the chance arose "
              "rarely. The binding constraint is the detector's recall, not the usefulness of an "
              "answer once given. This is the most actionable result of the study, because it "
              "says which component to improve next."),
        ("h2", "7.4 Defect Detection"),
        ("p", f"The reviewer caught {frac(dm['floor'], dm['n'])} injected defects at the floor, "
              f"{frac(dm['treatment'], dm['n'])} with clarification and "
              f"{frac(dm['ceiling'], dm['n'])} with "
              "full context. The full-context figure is the informative one: with the issue in "
              f"hand, the reviewer still approved {numword(DV['v2_defect_ceiling_missed'])} of "
              f"{numword(dm['n'])} broken patches. On this "
              "reviewer model, the limit on defect detection is reading the code, not knowing "
              "the intent, and clarification cannot lift detection above that ceiling. One "
              "mutant was caught without the issue text and approved with it - a single case, "
              "but consistent with a stated intent anchoring a reviewer toward acceptance."),
        ("h2", "7.5 Detector Comparison"),
        ("p", "Using constructed labels - a stripped context is ambiguous by construction and "
              "its full counterpart is clear - Table 7.2 and Figure 7.3 compare the detectors. "
              "A detector that keys on a missing issue gets part of its recall for free under "
              "these labels, so the figures bound real-world recall from above."),
        ("table", "Table 7.2 Detectors on constructed labels",
         ["Detector", "Decisions", "Ask rate", "Precision", "Recall", "Mean score (stripped / full)"],
         [[n, str(det[n]["n_decisions"]), pct(det[n]["ask_rate"]), f"{det[n]['precision']:.2f}",
           f"{det[n]['recall']:.2f}",
           f"{det[n]['mean_score_stripped']:.2f} / {det[n]['mean_score_full']:.2f}"]
          for n in ("heuristic", "sampling", "perturbation") if n in det],
         [1.2, 0.85, 0.85, 0.85, 0.75, 2.0]),
        ("fig", "fig9_detectors.png", "Figure 7.3 Mean detector score by context", 5.6),
        ("p", "The heuristic is perfectly precise and misses most ambiguous cases - the recall "
              "limit traced in Section 7.3. The uncertainty detectors cost eight model calls per "
              f"decision and were therefore run on {numword(DV['uncertainty_instances'])} instances only. "
              "At their default "
              "thresholds both asked on every decision. Sampling dispersion did separate the "
              "conditions, and re-sweeping its recorded scores suggests a threshold near 0.60 "
              "would have separated them almost perfectly; because those scores come from the "
              "study set, that threshold is reported as a diagnosis and not adopted. Prompt "
              "perturbation did not separate the conditions at all."),
        ("h2", "7.6 A Protocol Deviation, Reported"),
        ("p", "In the first version 2 run, the detector asked six questions and the treatment "
              "received no usable answer: four were empty and two were refusals. The simulated "
              "author's model reasons internally whether or not reasoning is requested, and "
              "those hidden tokens exhausted its 400-token budget before an answer was written; "
              "its prompt also refused any question phrased in terms of code it had not seen. "
              "The budget was raised, the prompt revised to answer intent questions from the "
              "issue text and refuse only when the text is silent, and the treatment re-run for "
              "the six affected instances; floor and ceiling were not re-run. Because the prompt "
              "was revised after the refusals were seen, both versions are logged with every "
              "exchange and the deviation is reported here and in the paper."),
        ("h2", "7.7 Cost Analysis"),
        ("table", "Table 7.3 Resources used by the main study",
         ["Item", "Quantity"],
         [["Reviews generated and judged", f"{V2['runs_ok']}"],
          ["Clarifying exchanges (question + answer)", f"{V2['treatment_asks']}"],
          ["Reviewer input tokens", f"{tk['input']:,}"],
          ["Reviewer output tokens", f"{tk['output']:,}"],
          ["Implicitly cached input tokens", f"{tk['cache_read']:,}"],
          ["Monetary cost (Gemini free tier)", "US$ 0.00"],
          ["Detector cost per decision",
           f"heuristic: 0 calls, {DET['heuristic']['mean_ms']} ms; uncertainty: 8 calls, "
           f"{DV['uncertainty_s_min']}-{DV['uncertainty_s_max']} s"],
          ["Added latency when the detector asks",
           f"about {numword(DV['v2_asked_latency_minutes'])} minutes, dominated by provider "
           "retries and hidden reasoning"]],
         [3.4, 3.2]),
        ("p", "The study cost nothing in money; its real cost was quota and time. A per-day "
              "request quota applied per model was the binding constraint throughout, which is "
              "why roles were spread across two model families. A clarification round added "
              f"about {numword(DV['v2_asked_latency_minutes'])} minutes to the asked instances, "
              "almost all of it waiting on provider "
              "retries and the question and answer models' hidden reasoning; the heuristic "
              f"detector itself adds {DET['heuristic']['mean_ms']} ms. On a paid key the same "
              "run would be "
              "priced by the token counts above and the provider's published rates, which the "
              "configuration holds in one table."),
        ("h2", "7.8 Replication on a Local Reviewer (v3)"),
        ("p", prose("report.s7_8.setup")),
        ("table", "Table 7.4 Judged outcomes of the local replication (v3, agent judge)",
         ["Measure", "Floor", "Treatment", "Ceiling", "McNemar p"],
         [[f"Intent recovered, all (n = {ia3['n']})", frac(ia3["floor"], ia3["n"]),
           frac(ia3["treatment"], ia3["n"]), frac(ia3["ceiling"], ia3["n"]),
           fixed(ia3["mcnemar_p"], 2)],
          [f"Intent recovered, golden (n = {t3['intent_golden']['n']})",
           frac(t3["intent_golden"]["floor"], t3["intent_golden"]["n"]),
           frac(t3["intent_golden"]["treatment"], t3["intent_golden"]["n"]),
           frac(t3["intent_golden"]["ceiling"], t3["intent_golden"]["n"]),
           fixed(t3["intent_golden"]["mcnemar_p"], 2)],
          [f"Intent recovered, mutant (n = {t3['intent_mutant']['n']})",
           frac(t3["intent_mutant"]["floor"], t3["intent_mutant"]["n"]),
           frac(t3["intent_mutant"]["treatment"], t3["intent_mutant"]["n"]),
           frac(t3["intent_mutant"]["ceiling"], t3["intent_mutant"]["n"]),
           fixed(t3["intent_mutant"]["mcnemar_p"], 2)],
          [f"Defect caught ({dm3['n']} mutants)", frac(dm3["floor"], dm3["n"]),
           frac(dm3["treatment"], dm3["n"]), frac(dm3["ceiling"], dm3["n"]),
           fixed(dm3["mcnemar_p"], 2)],
          [f"False alarm ({fa3['n']} golden)", frac(fa3["floor"], fa3["n"]),
           frac(fa3["treatment"], fa3["n"]), frac(fa3["ceiling"], fa3["n"]),
           fixed(fa3["mcnemar_p"], 2)],
          ["Mean latency per review", f"{pc3['stripped_plain']['ms'] / 1000:.1f} s",
           f"{pc3['stripped_clarify']['ms'] / 1000:.1f} s",
           f"{pc3['full_plain']['ms'] / 1000:.1f} s", "-"]],
         [2.4, 0.95, 1.0, 0.95, 1.0]),
        ("fig", "fig15_v3_results.png", "Figure 7.4 Outcomes by condition in the local replication",
         6.3),
        ("p", prose("report.s7_8.effect")),
        ("fig", "fig18_v3_funnel.png",
         "Figure 7.5 Tracing each v3 instance from floor miss to recovery", 6.0),
        ("p", prose("report.s7_8.funnel")),
        ("p", prose("report.s7_8.defects")),
        ("h2", "7.9 Judge Calibration"),
        ("p", prose("report.s7_9.lead")),
        ("table", "Table 7.5 Agreement between AI judges (percent agreement / kappa / n)",
         ["Pair", "Intent recovered", "Defect caught", "False alarm"],
         [[label] + [f"{pct(pair[m]['percent_agreement'])} / {fixed(pair[m]['kappa'], 2)} / "
                     f"{pair[m]['n']}"
                     for m in ("intent_recovered", "defect_caught", "false_alarm")]
          for label, pair in (
              (f"v2: {J['models']['api_v2']} vs Claude agent", J["v2_pairs"]["api_vs_agent"]),
              ("v2: Gemini web app vs Claude agent", J["v2_pairs"]["gemini_vs_agent"]),
              (f"v2: Gemini web app vs {J['models']['api_v2']}", J["v2_pairs"]["gemini_vs_api"]),
              (f"v3: {J['models']['api_v3']} vs Claude agent", J["v3_pairs"]["llama_vs_agent"]))],
         [2.4, 1.4, 1.4, 1.4]),
        ("fig", "fig16_judges.png", "Figure 7.6 Cohen's kappa between pairs of AI judges", 5.6),
        ("p", prose("report.s7_9.v2")),
        ("p", prose("report.s7_9.v3")),
        ("fig", "fig17_judge_robustness.png",
         "Figure 7.7 Gap recovery under each judge, with 95% intervals", 5.6),
        ("p", prose("report.s7_9.robust")),
        *gemini_v3_blocks(),
        *human_blocks(),
        ("h2", "7.12 Threats to Validity"),
        ("bullets", [
            f"Sample size: {V2['complete_triples']} instances in v2 and {V3['complete_triples']} "
            "in v3; intervals are wide and neither intent result is significant.",
            "Judge: checked against two human scorers on 60 of its reviews (Section 7.11). It "
            "agrees almost perfectly on defects and false alarms; on intent it is stricter than "
            "the humans, so intent recovery rates are conservative. The replication's judges are "
            "cross-checked only against other AI judges (Section 7.9).",
            "Labels: only 4 of 300 code-only PRs were labelled unclear, and the 7 annotator "
            "disagreements were adjudicated by an AI model at the team's request, so the "
            "classifier and the frozen thresholds rest on very few positive examples.",
            "Simulated author: answers come from withheld text only, but leakage needs the hand "
            "audit the tooling prepares; the prompt deviation is reported.",
            "Mutants: all verified mutants come from sympy and the operators produce simple "
            "defects, which may be easier or harder to catch than natural ones.",
            "Reviewer: small models (a free-tier hosted model in v2, a 4B local model in v3); "
            "their low detection rate may not hold for stronger reviewers.",
            prose("report.s7_10.post_hoc"),
            prose("report.s7_10.oracle"),
            prose("report.s7_10.new_rows"),
            prose("report.s7_10.bot"),
        ]),
    ]))

    # ---------------------------------------------------------------- 8
    ch.append(("CONCLUSION", [
        ("p", "This project built ClarifyReview, a pull request reviewer that decides before "
              "critiquing whether it understands what a change is for, and asks the author when "
              "it does not. The system is complete: four pipeline stages, four interchangeable "
              f"detectors, three provider backends (Gemini, Anthropic and local Ollama), a GitHub bot, "
              "and a benchmark harness covered "
              f"by {N_TESTS} automated tests, at technology readiness level 4."),
        ("p", "The evaluation produced three findings. First, evaluating this idea on golden "
              "patches requires withholding more than the linked issue, because well-written "
              "patches document their own intent; the pilot found this before the main run "
              "spent its quota. Second, with all natural-language intent withheld, clarification "
              f"recovered {IA['gap_recovery']:.2f} of the intent gap - in the expected direction "
              "but not significant at this sample size - and tracing each instance shows that "
              "clarification succeeded where it was given the chance and that the limit is the "
              "detector's recall. Third, defect detection was low even with full context, so on "
              "this reviewer the bottleneck for catching defects is the reviewer, not the intent."),
        ("p", prose("report.conclusion.v3")),
        ("h2", "8.1 Future Work"),
        ("bullets", [
            "Raise detector recall: label more pull requests that are genuinely unclear, so the "
            "classifier has positive examples to learn from, and freeze the sampling detector's "
            "threshold on a development split; then repeat the ablation with frozen thresholds.",
            "Check the replication's judges against human scorers, as was done for the original "
            "judge, and complete the oracle leakage audit.",
            f"Label the {RP['n_prs']} collected real pull requests ({RP['n_repos']} repositories, "
            f"{numword(len(RP['languages']))} languages).",
            "Run the paired blind developer study of perceived usefulness and trust.",
            "Host the bot permanently and run it on real third-party pull requests at scale.",
            "Repeat the study at a larger scale and with a stronger reviewer model on a paid key.",
            "Extend mutant verification beyond sympy and to more realistic defect types.",
        ]),
    ]))
    return ch


APPENDIX_FILES = [
    ("A.1 The decision point: a detector that never asks makes the baseline",
     "src/clarifyreview/pipeline.py", "class Pipeline", 40),
    ("A.2 Heuristic ambiguity score",
     "src/clarifyreview/detect/heuristic.py", "class HeuristicDetector", 40),
    ("A.3 Removing intent while keeping every line of code",
     "experiments/strip.py", "def strip_prose_from_diff", 60),
    ("A.4 McNemar's exact test",
     "experiments/analyze.py", "def mcnemar", 46),
]


def appendix_snippets() -> list[tuple[str, str]]:
    out = []
    for title, path, start, n in APPENDIX_FILES:
        lines = (ROOT / path).read_text(encoding="utf-8").splitlines()
        i = next(k for k, line in enumerate(lines) if line.startswith(start))
        out.append((title + f"  ({path})", "\n".join(lines[i:i + n]).rstrip()))
    return out
