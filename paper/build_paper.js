/**
 * ClarifyReview paper draft, IEEE conference layout (A4, two-column body).
 *
 * Every number comes from paper/numbers.json, produced by paper/collect.py from
 * the experiment databases. Nothing quantitative is typed into this file.
 *
 *   python -m paper.collect && node paper/build_paper.js
 */

const fs = require("fs");
const path = require("path");
const D = require(path.join(__dirname, "node_modules", "docx"));
const { Document, Packer, Paragraph, TextRun, AlignmentType, Table, TableRow,
        TableCell, WidthType, BorderStyle, ShadingType, SectionType } = D;

const N = JSON.parse(fs.readFileSync(path.join(__dirname, "numbers.json"), "utf8"));
const FONT = "Times New Roman";
const R = (t, o = {}) => new TextRun({ text: t, font: FONT, size: (o.size || 10) * 2,
  bold: !!o.bold, italics: !!o.italics, smallCaps: !!o.sc, superScript: !!o.sup });
const P = (runs, o = {}) => new Paragraph({
  alignment: o.align ?? AlignmentType.JUSTIFIED,
  spacing: { line: 240, before: o.before || 0, after: o.after ?? 60 },
  indent: o.noIndent ? undefined : { firstLine: 202 },
  children: Array.isArray(runs) ? runs : [R(runs)],
});
const H = (num, text) => new Paragraph({
  alignment: AlignmentType.CENTER, spacing: { before: 160, after: 80 },
  children: [R(`${num}. `, { sc: true }), R(text, { sc: true })],
});
const H2 = (letter, text) => new Paragraph({
  spacing: { before: 100, after: 50 },
  children: [R(`${letter}. ${text}`, { italics: true })],
});
const pct = x => (x === null || x === undefined || Number.isNaN(x)) ? "n/a" : `${Math.round(x * 100)}%`;
const f2 = x => (x === null || x === undefined || Number.isNaN(x)) ? "n/a" : Number(x).toFixed(2);
const fp = p => (p === null || p === undefined) ? "n/a" : (p < 0.001 ? "< 0.001" : Number(p).toFixed(3));

function table(header, rows, widths, caption) {
  const b = { style: BorderStyle.SINGLE, size: 4, color: "000000" };
  const none = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
  const cell = (t, i, bold, top) => new TableCell({
    width: { size: widths[i], type: WidthType.DXA },
    borders: { top: top ? b : none, bottom: b, left: none, right: none },
    margins: { top: 30, bottom: 30, left: 50, right: 50 },
    children: [new Paragraph({ alignment: i === 0 ? AlignmentType.LEFT : AlignmentType.CENTER,
      children: [R(String(t), { size: 8, bold })] })],
  });
  return [
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 100, after: 40 },
      children: [R(caption, { size: 8, sc: true })] }),
    new Table({
      columnWidths: widths, width: { size: widths.reduce((a, c) => a + c, 0), type: WidthType.DXA },
      rows: [new TableRow({ children: header.map((t, i) => cell(t, i, true, true)) }),
             ...rows.map(r => new TableRow({ children: r.map((t, i) => cell(t, i, false, false)) }))],
    }),
    new Paragraph({ spacing: { after: 80 }, children: [R("")] }),
  ];
}

// --------------------------------------------------------------------- text

const pilot = N.pilot, v2 = N.v2, mut = N.mutants, det = N.detectors || {};
const T = (v2 && v2.tests) || {};

const title = [
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 160 },
    children: [R("Asking Before Critiquing: Ambiguity-Aware Intent Clarification for LLM-Based Pull Request Review", { size: 22 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 20 }, children: [
    R("Yashika Gupta, Pratyaksh Gupta, Arivoli A", { size: 11 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 20 }, children: [
    R("School of Computer Science and Engineering, Vellore Institute of Technology, Vellore, India", { size: 10, italics: true })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 240 }, children: [
    R("yashika.gupta2023@vitstudent.ac.in", { size: 9 })] }),
];

function abstractText() {
  const s = [];
  s.push("Commercial LLM-based code reviewers read a pull request once, infer the author's intent, and comment on that inference. When intent is ambiguous they guess. We present ClarifyReview, a reviewer that inserts an ambiguity-detection step before comment generation and asks the author one targeted question when the available context is insufficient.");
  s.push(`We evaluate it in a two-by-three ablation on SWE-bench Verified, comparing a single-pass reviewer with intent removed, the same reviewer with clarification, and a full-context ceiling.`);
  s.push(`A pilot showed that removing only the linked issue leaves intent recoverable from the patch itself: intent recovery was ${pct(pilot.tests?.intent_all?.floor)} in the floor condition, leaving no gap to measure. A revised manipulation removes all natural-language statements of intent, and a mutant arm adds ${mut.by_status.verified} execution-verified defects.`);
  if (T.intent_all) {
    s.push(`On ${T.intent_all.n} complete instances, intent recovery was ${pct(T.intent_all.floor)} without clarification, ${pct(T.intent_all.treatment)} with it, and ${pct(T.intent_all.ceiling)} with full context (McNemar p = ${fp(T.intent_all.mcnemar_p)}).`);
  }
  if (T.defect_mutant) {
    s.push(`Verified defects were caught in ${pct(T.defect_mutant.floor)}, ${pct(T.defect_mutant.treatment)} and ${pct(T.defect_mutant.ceiling)} of cases respectively.`);
  }
  s.push("We report these as a small-sample study under free-tier quota limits, and release the system, harness and data.");
  return s.join(" ");
}

const abstract = [
  P([R("Abstract", { bold: true, italics: true }), R("—" + abstractText(), { bold: true, size: 9 })], { noIndent: true }),
  P([R("Index Terms", { bold: true, italics: true }), R("—automated code review, large language models, intent clarification, ambiguity detection, empirical software engineering", { bold: true, size: 9 })], { noIndent: true, after: 160 }),
];

const intro = [
  H("I", "Introduction"),
  P("Code review is a persistent bottleneck in software delivery, and tools such as CodeRabbit, Qodo and Greptile now use large language models (LLMs) to review pull requests automatically. All of them explain their comments in natural language, so explanation is no longer a distinguishing feature. What they share is a structural limitation: each reviews a pull request in a single pass. The tool reads the diff, infers what the author intended, and comments on that inference as though it were established."),
  P("When the diff is ambiguous—a validation check removed with no linked issue, a commit message reading only \"fix\"—a human reviewer asks. Current tools do not. They commit to a reading, producing false alarms on intentional changes and missed defects on unintentional ones. Both erode the trust that keeps such tools switched on."),
  P("Clarification-seeking is well established for code generation [1], [2], but we are not aware of work applying it to review of an existing change, where a wrong guess costs a human reviewer's attention rather than a compiler cycle. This paper makes three contributions: (i) ClarifyReview, a four-stage reviewer whose second stage decides per pull request whether to ask, with four interchangeable detector designs; (ii) an evaluation design for intent-dependent review on SWE-bench Verified [3], including a manipulation that withholds intent and a mutant arm with execution-verified defects; and (iii) an account of a pilot whose principal result was a correction to that design."),
];

const related = [
  H("II", "Related Work"),
  P("ClarifyGPT [1] detects ambiguous requirements through code-consistency checks and asks targeted questions before generating code, improving Pass@1. TiCoder [2] formalises intent through test-based queries and reports, in a fifteen-person study, improved correctness judgement and lower cognitive load. Both concern generation, not review of an existing diff."),
  P("SWE-bench [3] pairs real GitHub issues with the patches that resolved them and the tests those patches make pass, giving execution-based ground truth. It was built for autonomous repair and contains no ambiguity condition; our manipulation constructs one."),
  P("Self-consistency [4] and semantic uncertainty [5] measure disagreement across samples as a proxy for model uncertainty. We adapt them to measure instability in a reviewer's reading of a change's intent. Industry comparisons of deployed reviewers [6]–[8] differentiate tools by context depth; none reports a clarification step."),
];

const system = [
  H("III", "ClarifyReview"),
  P("ClarifyReview has four stages (Fig. 1 in the project report). Stage 1 parses the diff and resolves changed lines to changed symbols using the Python abstract syntax tree, assembling a bounded, deterministic context. Stage 2 decides whether to ask. Stage 3 generates at most two questions—each required by its output schema to name a file, line or symbol—posts them, and waits, falling back to a review flagged low-confidence on timeout. Stage 4 produces structured findings with severity, category, evidence, suggested fix and confidence."),
  P("Four detectors implement Stage 2 behind one interface. A heuristic combines fifteen diff features (missing issue, generic commit message, removed guard, absent test change, deletion ratio and others) as weighted evidence, normalised so the score is the fraction of available evidence present. A classifier learns weights over the same features. Two uncertainty detectors sample eight one-sentence intent hypotheses—by temperature sampling or by prompt perturbation—and score their dispersion and semantic entropy. The single-pass baseline is the same pipeline with a detector that never asks, so baseline and treatment differ in exactly one stage; an automated test asserts they render byte-identical prompts when the detector proceeds."),
];

const method = [
  H("IV", "Experimental Design"),
  H2("A", "Conditions"),
  P("Each instance is reviewed three times by the same model: with full context (the ceiling); with intent withheld, single-pass (the floor); and with intent withheld, through ClarifyReview (the treatment). When the treatment asks, a simulated author answers. The simulated author sees only the withheld issue text and commit message—never the diff, the defect, or whether one exists—and every exchange is logged for a leakage audit. Gap recovery is (treatment − floor)/(ceiling − floor)."),
  H2("B", "Withholding intent"),
  P("Version 1 of the manipulation removed the linked issue, title, description and commit messages, leaving the diff unchanged. Version 2 additionally removes comments, trailing comments and docstrings that the patch adds, leaving every line of code intact; the runner asserts code equivalence per instance, and this check caught a defect in our own stripping code before any data was collected."),
  H2("C", "Instances and verified defects"),
  P(`Golden patches are correct by construction, so reviewing them measures false alarms but not detection. We therefore inject defects into the added lines of golden patches with six mutation operators and keep a mutant only if the repository's own FAIL_TO_PASS tests pass with the golden patch and fail with the mutant. Of ${mut.attempted} sympy instances, ${mut.by_status.verified} yielded a verified mutant; ${mut.by_status.no_mutation_applies || 0} admitted no applicable operator, ${mut.by_status.every_mutant_survived || 0} produced only mutants the tests could not detect, and ${mut.by_status.environment_cannot_run_tests || 0} could not run in the available environment.`),
  P(`The v2 study set comprises ${N.v2_design ? N.v2_design.rows : "n/a"} rows: verified-mutant instances, each reviewed as both golden and mutant, and further golden patches from other repositories selected hardest-first by SWE-bench's own difficulty annotation. Selecting on an annotation assigned by the benchmark's authors, rather than on our detector's score, avoids biasing the detector comparison.`),
  H2("D", "Scoring"),
  P("An LLM judge scores each review for intent recovery, detection of the injected defect, and false alarms on correct code. The judge is a different model from the reviewer, to avoid self-preference. Paired binary outcomes are compared with McNemar's exact test and gap recovery is reported with a bootstrap confidence interval."),
];

function resultsSection() {
  const out = [H("V", "Results")];
  out.push(H2("A", "Pilot (manipulation v1)"));
  const pt = pilot.tests?.intent_all;
  out.push(P(`The pilot attempted ${pilot.attempted} SWE-bench Verified instances from ${pilot.attempted} repositories; ${pilot.complete_triples} completed all three conditions before the free-tier daily quota was exhausted. Intent recovery was ${pct(pt?.ceiling)} at the ceiling, ${pct(pt?.floor)} in the floor and ${pct(pt?.treatment)} in the treatment. With the floor equal to the ceiling there was no gap to recover. Inspection showed why: the patches stated their purpose in code, comments and docstrings, so withholding the issue removed nothing a reader needed. The detector asked on ${pilot.treatment_asks} of ${pilot.treatment_n} treatment runs.`));

  out.push(H2("B", "Main study (manipulation v2)"));
  if (!v2 || !v2.available || !T.intent_all) {
    out.push(P(`The v2 run had completed ${v2?.complete_triples ?? 0} instances at the time of writing; results are reported when the run completes.`));
    return out;
  }
  out.push(P(`${v2.complete_triples} of ${N.v2_design.rows} rows completed all three conditions${v2.runs_failed ? ` (${v2.runs_failed} failed calls)` : ", with no failed calls once transient provider errors were retried"}, and all ${v2.judged} reviews were judged. Table I gives the outcomes. Gap recovery is shown only where the ceiling exceeds the floor; elsewhere it is undefined.`));
  const rows = [];
  const add = (label, t, higherIsBetter = true) => t && rows.push([label, String(t.n), pct(t.floor), pct(t.treatment), pct(t.ceiling),
    higherIsBetter && t.ceiling > t.floor ? f2(t.gap_recovery) : "n/a", fp(t.mcnemar_p)]);
  add("Intent recovered (all)", T.intent_all);
  add("Intent recovered (golden)", T.intent_golden);
  add("Intent recovered (mutant)", T.intent_mutant);
  add("Defect caught (mutant)", T.defect_mutant);
  add("False alarm (golden)", T.false_alarm_golden, false);
  out.push(...table(["Measure", "n", "Floor", "Treat.", "Ceil.", "Gap rec.", "p"], rows,
    [1500, 330, 520, 520, 520, 560, 520], "Table I. Judged outcomes, manipulation v2"));
  out.push(P(`The detector asked on ${v2.treatment_asks} of ${v2.treatment_n} treatment runs (${pct(v2.treatment_ask_rate)}). The simulated author gave a substantive answer to ${v2.treatment_asks - (v2.treatment_refused || 0)} of these and declined ${v2.treatment_refused || 0}, saying the notes did not cover the question. Because the treatment differs from the floor only on runs where the detector asked, at most ${v2.treatment_asks} pairs can differ for a reason other than sampling variation; the remaining ${v2.treatment_n - v2.treatment_asks} pairs are two independent samples of the same single-pass review.`));
  const ia = T.intent_all, dm = T.defect_mutant;
  if (ia) {
    out.push(P(`Withholding all natural-language intent lowered intent recovery from ${pct(ia.ceiling)} to ${pct(ia.floor)}: the v2 manipulation opens a gap where v1 opened none, but a small one, because code alone still reveals the purpose of most of these patches. The treatment recovered intent in ${pct(ia.treatment)} of instances (McNemar p = ${fp(ia.mcnemar_p)}; discordant pairs: ${ia.discordant_treatment_better} favouring the treatment, ${ia.discordant_floor_better} favouring the floor).`));
  }
  const F = v2.funnel;
  if (F && F.floor_misses !== undefined) {
    out.push(P(`Tracing each instance shows where the effect is lost. The treatment can only improve on the floor for an instance the floor got wrong, that the detector flagged, and whose author answered. The floor missed intent on ${F.floor_misses} instances (the ceiling also missed ${F.ceiling_also_missed} of these). The detector asked on ${F.detector_asked} of the ${F.floor_misses}; the author answered ${F.author_answered} substantively; and the treatment recovered intent on ${F.treatment_recovered}. Where clarification was given the chance it recovered intent (${F.treatment_recovered} of ${F.author_answered}, too few to estimate a rate), but the chance arose rarely: the binding constraint is detector recall, not the value of an answer once given. Of the detector's ${F.asked_total} questions overall, ${F.asked_total - F.detector_asked} went to instances the floor already understood, where an answer cannot improve intent recovery.`));
  }
  if (dm) {
    out.push(P(`Injected defects were rarely caught in any condition—${pct(dm.floor)} in the floor, ${pct(dm.treatment)} in the treatment and ${pct(dm.ceiling)} with full context. The full-context figure is the informative one: with the issue in hand the reviewer still approved most mutants, so on this model the binding limit on defect detection is the reviewer's reading of the code, not missing intent, and clarification cannot raise detection above that ceiling. One mutant was caught without the issue text but approved with it, an isolated case but consistent with a stated intent anchoring the reviewer toward acceptance.`));
  }
  return out;
}

function detectorSection() {
  const out = [H2("C", "Detector comparison")];
  const names = Object.keys(det);
  if (!names.length) { out.push(P("Detector comparison results are not yet available.")); return out; }
  out.push(P("Using constructed labels—a stripped context is ambiguous by construction and its full counterpart clear—Table II compares the detectors. A detector that keys on a missing issue gains part of its recall for free under these labels, so the figures bound real-world recall from above."));
  const sm = det.sampling, pt = det.perturbation;
  if (sm && pt) {
    out.push(P(`The heuristic was run on every golden row; the two uncertainty detectors, which cost eight model calls per decision, on ${sm.n_decisions / 2} instances only, so their rows are indicative. At the default threshold both asked on every decision. Sampling dispersion did separate the conditions (mean score ${f2(sm.mean_score_stripped)} stripped against ${f2(sm.mean_score_full)} full), so a higher threshold might make it usable; perturbation did not (${f2(pt.mean_score_stripped)} against ${f2(pt.mean_score_full)}). The heuristic was the most conservative: it never asked on a full-context instance, but caught only ${pct(det.heuristic.recall)} of stripped ones, which is the recall limit traced above.`));
  }
  out.push(...table(["Detector", "Decisions", "Ask rate", "Prec.", "Recall", "Score (stripped / full)"],
    names.map(n => [n, String(det[n].n_decisions), pct(det[n].ask_rate), f2(det[n].precision),
      f2(det[n].recall), `${f2(det[n].mean_score_stripped)} / ${f2(det[n].mean_score_full)}`]),
    [900, 600, 560, 480, 480, 1100], "Table II. Detectors on constructed labels"));
  return out;
}

const discussion = [
  H("VI", "Threats to Validity"),
  P("The sample is small. Free-tier daily quotas, applied per model, bounded the number of instances, and confidence intervals are correspondingly wide; we report every completed instance rather than a selected subset. The judge is an LLM and has not yet been validated against human scoring; we provide a stratified sample and agreement tooling for that purpose. The simulated author answers only from withheld text and its exchanges are logged, but leakage cannot be excluded without audit. We also report a protocol deviation: in the first v2 run the simulated author's token budget was exhausted by the model's hidden reasoning, returning empty answers, and its prompt refused questions phrased in terms of code it had not seen. Both were corrected and the treatment condition re-run for the affected instances only; floor and ceiling runs were not repeated. The prompt change was made after observing refusals, and both versions are logged with every exchange. Mutants are verified by execution, yet the mutation operators produce simple defects that may be easier or harder to detect than natural ones. All verified mutants come from one repository, sympy, because it could be tested in the available environment. Every model used is a free-tier model, and the reviewer is a small one; its low defect-detection rate even with full context may not hold for stronger reviewers."),
  P("The detector comparison uses constructed labels; the classifier awaits the planned human-labelled set, and its absence means one of the four designs is not evaluated here."),
];

const conclusion = [
  H("VII", "Conclusion"),
  P(`ClarifyReview inserts a decision before critique: ask the author when the intent of a change cannot be read from the change itself. Our pilot showed that evaluating this idea on golden patches requires withholding more than the linked issue, because well-written patches document their own intent; the revised design withholds all natural-language intent and adds execution-verified defects. The system, harness, verified mutants and all results are released. On ${v2?.complete_triples ?? 0} complete instances clarification recovered ${f2(T.intent_all?.gap_recovery)} of the gap between floor and ceiling; the effect is not significant at this sample size, and the trace through detection, answering and recovery locates the limit in the detector's recall rather than in the usefulness of an answer once given. Remaining work is a human-labelled set for the classifier, human validation of the judge, a paired developer study of perceived trust and usefulness, and a larger run beyond free-tier limits.`),
];

const refs = [
  H("", "References"),
  ...[
    "F. Mu, X. Chen, L. Shi, S. Wang, and Q. Wang, \"ClarifyGPT: Empowering LLM-based code generation with intention clarification,\" arXiv:2310.10996, 2023.",
    "S. Fakhoury, A. Naik, G. Sakkas, S. Chakraborty, and S. K. Lahiri, \"LLM-based test-driven interactive code generation: User study and empirical evaluation,\" IEEE Trans. Softw. Eng., 2024.",
    "C. E. Jimenez, J. Yang, A. Wettig, S. Yao, K. Pei, O. Press, and K. Narasimhan, \"SWE-bench: Can language models resolve real-world GitHub issues?\" in Proc. ICLR, 2024.",
    "X. Wang, J. Wei, D. Schuurmans, Q. Le, E. Chi, S. Narang, A. Chowdhery, and D. Zhou, \"Self-consistency improves chain of thought reasoning in language models,\" in Proc. ICLR, 2023.",
    "L. Kuhn, Y. Gal, and S. Farquhar, \"Semantic uncertainty: Linguistic invariances for uncertainty estimation in natural language generation,\" in Proc. ICLR, 2023.",
    "Greptile, \"Best AI code review tools 2026—comparison benchmarks,\" greptile.com, 2026.",
    "Stork.AI, \"Best AI code review tools 2026: CodeRabbit vs. Greptile vs. Qodo,\" stork.ai, 2026.",
    "Morph, \"GitHub AI code review: 6 tools tested on real PRs,\" morphllm.com, 2026.",
  ].map((t, i) => new Paragraph({ spacing: { after: 30 }, indent: { left: 300, hanging: 300 },
      alignment: AlignmentType.JUSTIFIED, children: [R(`[${i + 1}]  ${t}`, { size: 8 })] })),
];

const page = { size: { width: 11906, height: 16838 },
               margin: { top: 1080, bottom: 1440, left: 820, right: 820 } };
const doc = new Document({
  creator: "Yashika Gupta, Pratyaksh Gupta",
  title: "Asking Before Critiquing",
  styles: { default: { document: { run: { font: FONT, size: 20 } } } },
  sections: [
    { properties: { page }, children: [...title, ...abstract] },
    { properties: { page, type: SectionType.CONTINUOUS, column: { count: 2, space: 340 } },
      children: [...intro, ...related, ...system, ...method, ...resultsSection(), ...detectorSection(),
                 ...discussion, ...conclusion, ...refs] },
  ],
});
Packer.toBuffer(doc).then(b => {
  const out = path.join(__dirname, "ClarifyReview_Paper_Draft.docx");
  fs.writeFileSync(out, b);
  console.log("saved", out);
});
