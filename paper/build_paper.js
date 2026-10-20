/**
 * ClarifyReview conference paper, IEEE conference layout (A4, two-column body).
 *
 * Every number comes from paper/numbers.json, produced by paper/collect.py from
 * the experiment log; figures come from docs/figures/make_figures.py. Nothing
 * quantitative is typed into this file.
 *
 *   python -m paper.collect && python docs/figures/make_figures.py
 *   node paper/build_paper.js [output.docx]
 */

const fs = require("fs");
const path = require("path");
const D = require(path.join(__dirname, "node_modules", "docx"));
const { Document, Packer, Paragraph, TextRun, AlignmentType, Table, TableRow, TableCell,
        WidthType, BorderStyle, SectionType, ImageRun } = D;

const ROOT = path.join(__dirname, "..");
const N = JSON.parse(fs.readFileSync(path.join(__dirname, "numbers.json"), "utf8"));
const FIG = path.join(ROOT, "docs", "figures");
const FONT = "Times New Roman";
const COL_W_IN = 3.42;

// ------------------------------------------------------------------ helpers

const R = (t, o = {}) => new TextRun({ text: t, font: FONT, size: Math.round((o.size || 10) * 2),
  bold: !!o.bold, italics: !!o.italics, smallCaps: !!o.sc, superScript: !!o.sup });
const runs = (x, size) => (Array.isArray(x) ? x : [R(x, { size })]);
const P = (x, o = {}) => new Paragraph({
  alignment: o.align ?? AlignmentType.JUSTIFIED,
  spacing: { line: 240, before: o.before || 0, after: o.after ?? 40 },
  indent: o.noIndent ? undefined : { firstLine: 202 },
  keepNext: !!o.keepNext,
  children: runs(x, o.size),
});
const H = (num, text) => new Paragraph({
  alignment: AlignmentType.CENTER, spacing: { before: 160, after: 80 }, keepNext: true,
  children: [R(`${num}. `, { sc: true }), R(text, { sc: true })],
});
const H2 = (letter, text) => new Paragraph({
  spacing: { before: 80, after: 40 }, keepNext: true,
  children: [R(`${letter}. ${text}`, { italics: true })],
});
const pct = x => (x === null || x === undefined || Number.isNaN(x)) ? "n/a" : `${Math.round(x * 100)}%`;
const f2 = x => (x === null || x === undefined || Number.isNaN(x)) ? "n/a" : Number(x).toFixed(2);
const fr = (rate, n) => `${Math.round(rate * n)}/${n}`;

function pngSize(file) {
  const b = fs.readFileSync(file);
  return { w: b.readUInt32BE(16), h: b.readUInt32BE(20), data: b };
}

let figNo = 0;
function figure(file, caption, widthIn = COL_W_IN) {
  figNo += 1;
  const { w, h, data } = pngSize(path.join(FIG, file));
  const wpx = Math.round(widthIn * 96);
  return [
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 80, after: 30 }, keepNext: true,
      children: [new ImageRun({ type: "png", data, transformation: { width: wpx, height: Math.round(wpx * h / w) } })] }),
    new Paragraph({ alignment: AlignmentType.JUSTIFIED, spacing: { after: 100 },
      children: [R(`Fig. ${figNo}.  `, { size: 8 }), R(caption, { size: 8 })] }),
  ];
}

let tabNo = 0;
const ROMAN = ["I", "II", "III", "IV", "V", "VI"];
function table(header, rows, widths, caption) {
  tabNo += 1;
  const b = { style: BorderStyle.SINGLE, size: 4, color: "000000" };
  const none = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
  const cell = (t, i, bold, top, last) => new TableCell({
    width: { size: widths[i], type: WidthType.DXA },
    borders: { top: top ? b : none, bottom: (bold || last) ? b : none, left: none, right: none },
    margins: { top: 25, bottom: 25, left: 40, right: 40 },
    children: [new Paragraph({ alignment: i === 0 ? AlignmentType.LEFT : AlignmentType.CENTER,
      children: [R(String(t), { size: 8, bold })] })],
  });
  return [
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 100, after: 0 }, keepNext: true,
      children: [R(`TABLE ${ROMAN[tabNo - 1]}`, { size: 8 })] }),
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 40 }, keepNext: true,
      children: [R(caption, { size: 8, sc: true })] }),
    new Table({
      columnWidths: widths, width: { size: widths.reduce((a, c) => a + c, 0), type: WidthType.DXA },
      rows: [new TableRow({ children: header.map((t, i) => cell(t, i, true, true, false)) }),
             ...rows.map((r, k) => new TableRow({ children: r.map((t, i) =>
               cell(t, i, false, false, k === rows.length - 1)) }))],
    }),
    new Paragraph({ spacing: { after: 60 }, children: [R("")] }),
  ];
}

// --------------------------------------------------------------------- data

const pilot = N.pilot, v2 = N.v2, mut = N.mutants, det = N.detectors || {};
const T = v2.tests, F = v2.funnel;
const IA = T.intent_all, DM = T.defect_mutant, FA = T.false_alarm_golden;
const nTests = parseInt(N.tests_passing, 10);
const verified = mut.by_status.verified;

// References, numbered in order of first citation.
const REFS = [
  ["bacchelli", "A. Bacchelli and C. Bird, \"Expectations, outcomes, and challenges of modern code review,\" in Proc. ICSE, 2013, pp. 712-721."],
  ["sadowski", "C. Sadowski, E. Söderberg, L. Church, M. Sipko, and A. Bacchelli, \"Modern code review: A case study at Google,\" in Proc. ICSE-SEIP, 2018, pp. 181-190."],
  ["industry", "Greptile, \"Best AI code review tools 2026—comparison benchmarks,\" greptile.com, 2026; Morph, \"GitHub AI code review: 6 tools tested on real PRs,\" morphllm.com, 2026."],
  ["clarifygpt", "F. Mu, X. Chen, L. Shi, S. Wang, and Q. Wang, \"ClarifyGPT: Empowering LLM-based code generation with intention clarification,\" arXiv:2310.10996, 2023."],
  ["ticoder", "S. Fakhoury, A. Naik, G. Sakkas, S. Chakraborty, and S. K. Lahiri, \"LLM-based test-driven interactive code generation: User study and empirical evaluation,\" IEEE Trans. Softw. Eng., vol. 50, no. 9, pp. 2254-2268, 2024."],
  ["swebench", "C. E. Jimenez, J. Yang, A. Wettig, S. Yao, K. Pei, O. Press, and K. Narasimhan, \"SWE-bench: Can language models resolve real-world GitHub issues?\" in Proc. ICLR, 2024."],
  ["tufano", "R. Tufano, L. Pascarella, M. Tufano, D. Poshyvanyk, and G. Bavota, \"Towards automating code review activities,\" in Proc. ICSE, 2021, pp. 163-174."],
  ["codereviewer", "Z. Li et al., \"Automating code review activities by large-scale pre-training,\" in Proc. ESEC/FSE, 2022, pp. 1035-1047."],
  ["selfconsistency", "X. Wang, J. Wei, D. Schuurmans, Q. Le, E. Chi, S. Narang, A. Chowdhery, and D. Zhou, \"Self-consistency improves chain of thought reasoning in language models,\" in Proc. ICLR, 2023."],
  ["semantic", "L. Kuhn, Y. Gal, and S. Farquhar, \"Semantic uncertainty: Linguistic invariances for uncertainty estimation in natural language generation,\" in Proc. ICLR, 2023."],
  ["verified", "OpenAI, \"Introducing SWE-bench Verified,\" openai.com, 2024."],
  ["mutation", "Y. Jia and M. Harman, \"An analysis and survey of the development of mutation testing,\" IEEE Trans. Softw. Eng., vol. 37, no. 5, pp. 649-678, 2011."],
  ["judge", "L. Zheng et al., \"Judging LLM-as-a-judge with MT-Bench and Chatbot Arena,\" in Proc. NeurIPS Datasets and Benchmarks Track, 2023."],
  ["mcnemar", "Q. McNemar, \"Note on the sampling error of the difference between correlated proportions or percentages,\" Psychometrika, vol. 12, no. 2, pp. 153-157, 1947."],
  ["cohen", "J. Cohen, \"A coefficient of agreement for nominal scales,\" Educ. Psychol. Meas., vol. 20, no. 1, pp. 37-46, 1960."],
];
const cite = (...keys) => "[" + keys.map(k => REFS.findIndex(r => r[0] === k) + 1).join("], [") + "]";

// ------------------------------------------------------------------- title

const title = [
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 },
    children: [R("Asking Before Critiquing: Ambiguity-Aware Intent Clarification for LLM-Based Pull Request Review", { size: 22 })] }),
  ...[["Yashika Gupta", "Pratyaksh Gupta", "Arivoli A"]].map(names => new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { after: 20 },
    children: [R(names.join("        "), { size: 11 })] })),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 20 }, children: [
    R("School of Computer Science and Engineering", { size: 10, italics: true })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 240 }, children: [
    R("Vellore Institute of Technology, Vellore, India", { size: 10, italics: true })] }),
];

const abstractText =
  "LLM-based pull request reviewers read a change once, infer what its author intended, and comment on that " +
  "inference; when the intent is ambiguous they guess. We present ClarifyReview, a reviewer that decides " +
  "before critiquing whether the available context is sufficient, and asks the author a targeted question " +
  "when it is not. Its single-pass baseline is the same pipeline with a detector that never asks, so the two " +
  "differ in one stage. We evaluate it in a two-by-three ablation on SWE-bench Verified, crossing correct and " +
  `execution-verified defective patches (${verified} mutants) with three conditions: intent withheld, intent ` +
  "withheld with clarification, and full context. A pilot showed that withholding only the linked issue " +
  "leaves intent recoverable from the patch itself; withholding every natural-language statement of intent " +
  `opened a gap. On ${IA.n} instances, intent recovery was ${pct(IA.floor)} without clarification, ` +
  `${pct(IA.treatment)} with it and ${pct(IA.ceiling)} with full context (gap recovery ${f2(IA.gap_recovery)}, ` +
  `McNemar p = ${f2(IA.mcnemar_p)}). Tracing each instance shows that clarification recovered intent where it ` +
  `was given the chance, and that the binding limit is detector recall: the detector flagged ${F.detector_asked} ` +
  `of the ${F.floor_misses} changes the reviewer misread. Defect detection was low in every condition, including ` +
  "full context, so it is limited by the reviewer rather than by missing intent. We release the system, harness, " +
  "verified mutants and study log.";

const abstract = [
  P([R("Abstract", { bold: true, italics: true, size: 9 }), R("—" + abstractText, { bold: true, size: 9 })], { noIndent: true }),
  P([R("Index Terms", { bold: true, italics: true, size: 9 }), R("—automated code review, large language models, intent clarification, ambiguity detection, mutation testing, empirical software engineering", { bold: true, size: 9 })], { noIndent: true, after: 160 }),
];

// ---------------------------------------------------------------- sections

const intro = [
  H("I", "Introduction"),
  P(`Code review is a persistent bottleneck in software delivery, and most of a reviewer's effort goes into understanding what a change is for ${cite("bacchelli", "sadowski")}. Tools such as CodeRabbit, Qodo and Greptile now use large language models (LLMs) to review pull requests automatically ${cite("industry")}. All of them explain their comments, so explanation is no longer distinguishing. What they share is a structural limitation: each reviews a pull request in a single pass, inferring the author's intent and commenting on that inference as though it were established.`),
  P("When the change is ambiguous—a validation check removed with no linked issue and a commit message reading only \"fix\"—a human reviewer asks. Current tools do not. They commit to a reading, producing false alarms on intentional changes and missed defects on unintentional ones, and both erode the trust that keeps such tools switched on."),
  P(`Clarification-seeking improves code generation ${cite("clarifygpt", "ticoder")}, but we are not aware of work applying it to review of an existing change, where a wrong guess costs a human reviewer's attention rather than a compiler cycle. We ask whether a reviewer that asks before critiquing understands and detects more than one that does not. This paper makes four contributions:`),
  P("1) ClarifyReview, a four-stage reviewer whose second stage decides per pull request whether to ask, with four interchangeable detector designs and a baseline that differs from it in exactly one stage;", { noIndent: true }),
  P(`2) an evaluation design for intent-dependent review on SWE-bench ${cite("swebench")}: a manipulation that withholds all natural-language intent while leaving code untouched, and ${verified} execution-verified defects;`, { noIndent: true }),
  P("3) a two-by-three ablation with a per-instance trace that separates the value of an answer from the chance to ask, locating the limit of the approach in detector recall; and", { noIndent: true }),
  P("4) an account of a pilot whose principal result was a correction to the evaluation design, and of a protocol deviation, both reported in full.", { noIndent: true, after: 80 }),
];

const related = [
  H("II", "Related Work"),
  H2("A", "Automated code review"),
  P(`Empirical studies at Microsoft and Google found that understanding a change is the reviewer's first and costliest task ${cite("bacchelli", "sadowski")}. Learned reviewers generate comments from review data ${cite("tufano", "codereviewer")}, and deployed LLM tools differ mainly in how much repository context they retrieve ${cite("industry")}. All are single-pass; none resolves intent before commenting.`),
  H2("B", "Clarification in code generation"),
  P(`ClarifyGPT detects ambiguous requirements through a code-consistency check and asks targeted questions before generating code, improving Pass@1 ${cite("clarifygpt")}. TiCoder clarifies intent through generated tests and, in a fifteen-person study, improved correctness judgement and lowered cognitive load ${cite("ticoder")}. Both concern greenfield generation; both show that asking must be scaffolded and selective.`),
  H2("C", "Uncertainty quantification"),
  P(`Self-consistency treats disagreement across samples as a signal ${cite("selfconsistency")}; semantic uncertainty clusters samples by meaning before measuring dispersion ${cite("semantic")}. We adapt both to measure instability in a reviewer's reading of a change's intent.`),
  H2("D", "Benchmarks and evaluation"),
  P(`SWE-bench pairs real issues with the patches that resolved them and the tests those patches make pass ${cite("swebench")}; its Verified subset was validated by human annotators ${cite("verified")}. Known tests allow defective variants whose defectiveness is established by execution ${cite("mutation")}. LLM judges agree with human raters about as often as humans agree, with known biases including self-preference ${cite("judge")}, which motivates using a judge from a different model family than the reviewer.`),
];

const system = [
  H("III", "ClarifyReview"),
  P("ClarifyReview has four stages (Fig. 1). Stage 1 parses the diff and resolves changed lines to changed symbols with the Python abstract syntax tree, assembling a bounded context in a deterministic order and fingerprinting it. Stage 2 decides whether to ask. Stage 3 generates at most two questions—each required by its output schema to name a file, line or symbol, so that it cannot degenerate into \"please explain this PR\"—and sends them through a Responder. Stage 4 produces structured findings with severity, category, evidence, suggested fix and confidence."),
  ...figure("fig2_architecture.png", "ClarifyReview's four stages. Stage 2 is the decision point; when it proceeds, Stage 3 does not run."),
  H2("A", "Ambiguity detectors"),
  P("Four detectors implement one interface, score(context) → s ∈ [0, 1], and a shared decision asks when s ≥ τ for a threshold τ frozen in configuration. The heuristic combines fifteen diff features—missing linked issue, generic commit message, removed guard, no test alongside, public symbol touched, deletion ratio and others—as weighted evidence, s = Σ wᵢfᵢ / Σ wᵢ, so the score reads as the fraction of ambiguity evidence present; it makes no model call. A logistic-regression classifier learns weights over the same features from labelled pull requests. Two uncertainty detectors sample eight one-sentence hypotheses about what the change is for—by temperature sampling, or by perturbing the prompt at fixed temperature—and score their mean pairwise embedding distance and semantic entropy."),
  H2("B", "One pipeline, two conditions"),
  P(`The single-pass baseline is not separate code: it is the same pipeline with a detector that never asks, and a test asserts that, with the detector forced to proceed, both conditions render byte-identical prompts. Stage 3 talks to the author through a Responder protocol with three implementations—a GitHub responder that posts a comment and waits, a benchmark responder that calls a simulated author, and a null responder—so the experiment exercises the code that would be deployed. The system is written in Python, runs as a GitHub App or from a command line, records every run to an SQLite log, and is covered by ${nTests} automated tests.`),
];

const method = [
  H("IV", "Experimental Design"),
  P("We ask three questions. RQ1: does clarification recover intent that is lost when the author's stated intent is withheld? RQ2: does it improve defect detection or reduce false alarms? RQ3: how well do the detectors identify the changes that need a question?"),
  H2("A", "Conditions"),
  P("Each instance is reviewed three times by the same reviewer model with the same prompt template (Fig. 2): with full context (the ceiling); with intent withheld, single-pass (the floor); and with intent withheld, through ClarifyReview (the treatment). Floor and treatment see byte-identical code, asserted per instance. Gap recovery G = (treatment − floor)/(ceiling − floor) is the share of the context-induced loss that clarification restores."),
  ...figure("fig11_design.png", "The two-by-three design. Golden patches measure intent recovery and false alarms; verified mutants measure intent recovery and defect detection."),
  H2("B", "Withholding intent"),
  P("Version 1 of the manipulation removed the linked issue, title, description and commit messages. Version 2 additionally removes every comment, trailing comment and docstring the patch adds, leaving every line of code intact. A docstring is removed only when the patch opens it on an added line, after an earlier rule deleted real code in a hunk that began inside an existing docstring."),
  H2("C", "Execution-verified defects"),
  P(`Golden patches are correct by construction, so they measure false alarms but not detection. We inject defects into the lines a golden patch adds with six operators—invert comparison, negate condition, flip constant, drop guard, swap boolean operator, off-by-one—and keep a mutant only if the repository's FAIL_TO_PASS tests pass with the golden patch and fail with the mutant ${cite("mutation")}. Of ${mut.attempted} sympy instances, ${verified} yielded a verified mutant; ${mut.by_status.no_mutation_applies} admitted no operator, ${mut.by_status.every_mutant_survived} produced only mutants the tests did not catch, and ${mut.by_status.environment_cannot_run_tests} could not run in the available environment.`),
  H2("D", "Instances"),
  P(`The study set has ${N.v2_design.rows} rows: twelve sympy instances reviewed both as the golden patch and as its verified mutant, and twelve golden patches from xarray, sphinx, astropy, django, pylint, pytest and scikit-learn. Instances were chosen hardest-first by SWE-bench's own difficulty annotation, assigned by the benchmark's annotators rather than by our detector, so selection does not favour the detector under evaluation.`),
  H2("E", "Simulated author, judge and statistics"),
  P(`When the treatment asks, a simulated author answers using only the withheld issue text and commit messages; it never sees the diff, the defect, or whether one exists, and must decline when its notes are silent. Every exchange is logged with its prompt version. Reviews are scored by an LLM judge from a different model family than the reviewer on three checklist questions: was the intent recovered, was the injected defect caught, and was a false alarm raised on correct code. Paired outcomes are compared with McNemar's exact test ${cite("mcnemar")}; gap recovery is reported with a bootstrap 95% interval. The reviewer is gemini-3.5-flash-lite; questions, the simulated author and the judge use gemma-4-31b-it; all calls ran on free-tier access.`),
];

function results() {
  const out = [H("V", "Results")];
  const pt = pilot.tests?.intent_all;
  out.push(H2("A", "Pilot (manipulation v1)"));
  out.push(P(`The pilot attempted ${pilot.attempted} instances from ten repositories; ${pilot.complete_triples} completed all three conditions before the daily quota was exhausted. Intent recovery was ${pct(pt?.ceiling)} at the ceiling, ${pct(pt?.floor)} at the floor and ${pct(pt?.treatment)} in the treatment: with the floor equal to the ceiling there was nothing to recover. The patches stated their purpose in the comments and docstrings they added, so withholding the issue removed nothing a reader needed. This led to manipulation v2, the mutant arm and difficulty-ordered selection.`));

  out.push(H2("B", "RQ1: intent recovery"));
  out.push(P(`All ${v2.complete_triples} rows completed all three conditions and all ${v2.judged} reviews were judged (Table I, Fig. 3). Withholding all natural-language intent lowered intent recovery from ${pct(IA.ceiling)} to ${pct(IA.floor)}, opening the gap v1 did not. Clarification raised it to ${pct(IA.treatment)}: G = ${f2(IA.gap_recovery)} (95% CI ${f2(IA.gap_ci[0])}–${f2(IA.gap_ci[1])}), with ${IA.discordant_treatment_better} discordant pair favouring the treatment and ${IA.discordant_floor_better} the floor (p = ${f2(IA.mcnemar_p)}). The direction is as hypothesised; at this sample size the effect is not significant, and could not have been, since only pairs where the detector asked can differ for a reason other than sampling variation.`));
  const row = (label, t, n) => [label, fr(t.floor, n), fr(t.treatment, n), fr(t.ceiling, n), f2(t.mcnemar_p)];
  out.push(...table(["Measure", "Floor", "Treat.", "Ceiling", "p"], [
    row("Intent, all", IA, 36), row("Intent, golden", T.intent_golden, 24), row("Intent, mutant", T.intent_mutant, 12),
    row("Defect caught", DM, 12), row("False alarm", FA, 24)],
    [1500, 760, 760, 760, 560], "Judged outcomes, manipulation v2"));
  out.push(...figure("fig7_results.png", "Outcomes by condition. Bars show the share of instances; labels give counts."));

  out.push(H2("C", "Where the effect is lost"));
  out.push(P(`The treatment can improve on the floor only for an instance the floor got wrong, that the detector flagged, and whose author answered (Fig. 4). The floor misread ${F.floor_misses} changes. The detector asked on ${F.detector_asked}; the author answered ${F.author_answered} substantively; and the treatment recovered intent in ${F.treatment_recovered}. The other flagged miss received a refusal: its question concerned a parameter the issue never mentions. Of the detector's ${F.asked_total} questions, ${F.asked_total - F.detector_asked} went to instances the floor already understood, where an answer cannot raise intent recovery. Clarification worked where it was given the chance (too few cases to estimate a rate), and the chance arose rarely: the binding constraint is detector recall.`));
  out.push(...figure("fig8_funnel.png", "Tracing each instance from a floor miss to recovery."));
  out.push(P("In the recovered case (sympy-12481) the patch lets the Permutation constructor accept non-disjoint cycles. The floor summarised it as \"tidy up permutation instantiation logic\". The detector scored the stripped change 0.556 and asked whether removing the specialised error was intended; the author replied that non-disjoint cycles should be applied left to right; the treatment's summary then matched the ceiling's."));

  out.push(H2("D", "RQ2: defects and false alarms"));
  out.push(P(`The reviewer caught ${fr(DM.floor, 12)} injected defects at the floor, ${fr(DM.treatment, 12)} with clarification and ${fr(DM.ceiling, 12)} with full context. The full-context figure bounds what intent can contribute: given the issue, the reviewer still approved eleven of twelve broken patches, so on this model detection is limited by reading the code, not by knowing its purpose. One mutant was caught without the issue and approved with it—an isolated case, but consistent with stated intent anchoring a reviewer toward acceptance. False alarms on correct patches were rare in every condition (${fr(FA.floor, 24)}, ${fr(FA.treatment, 24)}, ${fr(FA.ceiling, 24)}).`));

  out.push(H2("E", "RQ3: detectors"));
  out.push(P("With constructed labels—a stripped context is ambiguous by construction, its full counterpart clear—Table II and Fig. 5 compare the detectors. A detector keyed on a missing issue gains recall for free under these labels, so recall is bounded from above."));
  const dn = ["heuristic", "sampling", "perturbation"].filter(n => det[n]);
  out.push(...table(["Detector", "n", "Ask", "Prec.", "Rec.", "Score s / f"],
    dn.map(n => [n, String(det[n].n_decisions), pct(det[n].ask_rate), f2(det[n].precision), f2(det[n].recall),
      `${f2(det[n].mean_score_stripped)} / ${f2(det[n].mean_score_full)}`]),
    [1080, 380, 520, 520, 480, 1060], "Detectors on constructed labels"));
  out.push(...figure("fig9_detectors.png", "Mean detector score with intent withheld and with full context; dashed lines mark default thresholds."));
  if (det.sampling && det.perturbation) {
    out.push(P(`The heuristic never asked on a full-context instance but found only ${pct(det.heuristic.recall)} of stripped ones—the recall limit of Section V-C. The uncertainty detectors cost eight calls per decision and were run on ${det.sampling.n_decisions / 2} instances. At their default thresholds both asked on every decision. Sampling dispersion separated the contexts (${f2(det.sampling.mean_score_stripped)} vs ${f2(det.sampling.mean_score_full)}); re-sweeping its recorded scores suggests a threshold near 0.60 would separate them, which we report as a diagnosis rather than adopt, since those scores come from the study set. Prompt perturbation did not separate them (${f2(det.perturbation.mean_score_stripped)} vs ${f2(det.perturbation.mean_score_full)}).`));
  }
  return out;
}

const discussion = [
  H("VI", "Discussion"),
  P("Asking is cheap to add and hard to target. Once a question reached an author who could answer it, the answer did what it was meant to do; nearly all of the loss happened earlier, in deciding when to ask. This shifts the research problem: the quality of a clarifying question matters less than the recall of the decision to pose one, at a precision that keeps the tool tolerable. A detector built from diff features was precise and conservative; a sampling-based detector separated the conditions but needs calibration on held-out data."),
  P("Golden patches are a poor population for studying ambiguity. Well-written fixes state their purpose in the code, comments and docstrings they add; evaluating intent-dependent review requires withholding all of it, and even then most changes remain self-explanatory. Benchmarks of genuinely under-specified changes would strengthen this line of work."),
  P("Finally, clarification cannot exceed the reviewer. On a small free-tier model, full context did not make the reviewer catch injected defects, so detection gains, if they exist, require a stronger reviewer before intent can matter."),
];

const threats = [
  H("VII", "Threats to Validity"),
  P(`The sample is small (${v2.complete_triples} instances under per-model daily quotas), so intervals are wide. The judge has not yet been validated against human scoring; a stratified sample and agreement tooling (Cohen's κ ${cite("cohen")}) are provided. The simulated author answers from withheld text only, but leakage requires the hand audit the tooling prepares. We report a protocol deviation: in the first v2 run the simulated author's token budget was exhausted by its model's hidden reasoning, returning empty answers, and its prompt refused questions phrased in terms of unseen code. Both were corrected and the treatment re-run for the six affected instances; floor and ceiling were not re-run, and the prompt revision, made after observing refusals, is logged with every exchange. All verified mutants come from sympy and the operators produce simple defects. The reviewer is a small model; results may differ for stronger ones.`),
];

const conclusion = [
  H("VIII", "Conclusion"),
  P(`ClarifyReview inserts a decision before critique: ask the author when the intent of a change cannot be read from the change. Evaluating the idea required withholding all natural-language intent, because golden patches document their own. With that manipulation, clarification recovered ${f2(IA.gap_recovery)} of the intent gap on ${v2.complete_triples} instances—in the expected direction, not significant at this size—and a per-instance trace shows it succeeded where it was given the chance, with detector recall as the limit. Future work is a human-labelled set to train and calibrate the detectors, human validation of the judge, a paired developer study of usefulness and trust, and a larger run with a stronger reviewer.`),
];

const ack = [
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 120, after: 60 },
    children: [R("Acknowledgment", { sc: true })] }),
  P("The authors thank the School of Computer Science and Engineering, Vellore Institute of Technology, for supporting this work."),
];

const refs = [
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 120, after: 60 },
    children: [R("References", { sc: true })] }),
  ...REFS.map(([, t], i) => new Paragraph({ spacing: { after: 30 }, indent: { left: 300, hanging: 300 },
    alignment: AlignmentType.JUSTIFIED, children: [R(`[${i + 1}]  ${t}`, { size: 8 })] })),
];

// ---------------------------------------------------------------- document

const page = { size: { width: 11906, height: 16838 },
               margin: { top: 1080, bottom: 1440, left: 820, right: 820 } };
const doc = new Document({
  creator: "Yashika Gupta, Pratyaksh Gupta, Arivoli A",
  title: "Asking Before Critiquing",
  styles: { default: { document: { run: { font: FONT, size: 20 } } } },
  sections: [
    { properties: { page }, children: [...title, ...abstract] },
    { properties: { page, type: SectionType.CONTINUOUS, column: { count: 2, space: 340 } },
      children: [...intro, ...related, ...system, ...method, ...results(), ...discussion,
                 ...threats, ...conclusion, ...ack, ...refs] },
  ],
});
const out = process.argv[2] || path.join(__dirname, "ClarifyReview_Paper_Draft.docx");
Packer.toBuffer(doc).then(b => {
  fs.writeFileSync(out, b);
  console.log("saved", out);
});
