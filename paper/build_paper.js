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

const { PROSE, fmt } = require(path.join(__dirname, "prose.js"));   // text: docs/prose_v3.json

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
const kap = f2;                                              // kappa and G: two decimals
const ci = a => `${f2(a[0])} to ${f2(a[1])}`;
const cap = t => t ? t[0].toUpperCase() + t.slice(1) : t;
const word = n => fmt(n, "word", "");                        // 11 -> "eleven"

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
const ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII"];
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
// Second-model replication (v3) and judge calibration. Never pooled with v2; AI-vs-AI only.
const V3 = N.v3_local, J = N.judges, V2A = N.v2_agent_judge, S3 = N.v3_setup, D3 = N.v3_design;
const RP = N.realpr, DV = N.derived;
const G3 = N.v3_gemini?.available && N.v3_gemini.tests?.intent_all ? N.v3_gemini : null;
const T3 = V3.tests, IA3 = T3.intent_all, DM3 = T3.defect_mutant, FA3 = T3.false_alarm_golden;
const verified = mut.by_status.verified;

// References, numbered in order of first citation.
const REFS = [
  ["bacchelli", "A. Bacchelli and C. Bird, \"Expectations, outcomes, and challenges of modern code review,\" in Proc. ICSE, 2013, pp. 712-721."],
  ["sadowski", "C. Sadowski, E. Söderberg, L. Church, M. Sipko, and A. Bacchelli, \"Modern code review: A case study at Google,\" in Proc. ICSE-SEIP, 2018, pp. 181-190."],
  ["industry", "Greptile, \"Best AI code review tools 2026: comparison benchmarks,\" greptile.com, 2026; Morph, \"GitHub AI code review: 6 tools tested on real PRs,\" morphllm.com, 2026."],
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
  "LLM-based pull request reviewers typically inspect a change, infer the author's intent, and generate comments " +
  "based on that interpretation. When the intent is unclear, the reviewer may make an incorrect assumption. We " +
  "introduce ClarifyReview, a system that checks whether the available context is sufficient before producing " +
  "feedback and asks the author a focused question when additional information is needed. The single-pass " +
  "baseline uses the same pipeline but disables clarification, allowing us to isolate the effect of this decision " +
  "stage. We evaluate ClarifyReview on SWE-bench Verified using a two-by-three ablation that includes correct " +
  `patches and defective variants drawn from ${verified} execution-verified mutants. Each instance is assessed ` +
  "under three conditions: with intent withheld, with intent withheld but clarification enabled, and with full " +
  "context available. An initial pilot showed that removing only the linked issue was insufficient because the " +
  "patch itself often revealed its purpose. We therefore removed all natural-language statements of intent while " +
  `preserving the code. Across ${IA.n} instances, intent recovery was ${pct(IA.floor)} without clarification, ` +
  `${pct(IA.treatment)} with clarification, and ${pct(IA.ceiling)} with full context. The resulting gap recovery ` +
  `was ${f2(IA.gap_recovery)}, with a McNemar p-value of ${f2(IA.mcnemar_p)}. Instance-level analysis suggests ` +
  "that clarification can recover intent when the detector identifies a need to ask, but detector recall remains " +
  `a major limitation: it flagged only ${word(F.detector_asked)} of the ${word(F.floor_misses)} changes whose intent ` +
  "the reviewer misinterpreted. Defect detection remained low even with full context, indicating that the " +
  "reviewer's ability to identify defects, rather than missing intent alone, limits performance. We also " +
  `replicated the experiment on ${V3.complete_triples} instances using a local model, ${S3.reviewer_model_name}. ` +
  `Intent recovery was ${pct(IA3.floor)} without clarification, ${pct(IA3.treatment)} with clarification, and ` +
  `${pct(IA3.ceiling)} with full context. Gap recovery was ${f2(IA3.gap_recovery)} (95% interval: ` +
  `${f2(IA3.gap_ci[0])} to ${f2(IA3.gap_ci[1])}), which was not statistically significant. Re-scoring the ` +
  "original study with an alternative judge preserved the overall conclusion, although the estimated effect " +
  "changed. " +
  (G3 ? `When the replication set was evaluated using the original reviewer, intent recovery increased from ${pct(G3.tests.intent_all.floor)} to ${pct(G3.tests.intent_all.treatment)}. However, ${word(G3.discordant.not_asked)} of the ${word(G3.discordant.total)} instances with changed outcomes involved cases where no clarification question was asked, suggesting that run-to-run reviewer variation, rather than clarification, explains most of this difference. ` : "") +
  "We release the system, evaluation harness, verified mutants, and study log.";

const abstract = [
  P([R("Abstract", { bold: true, italics: true, size: 9 }), R(": " + abstractText, { bold: true, size: 9 })], { noIndent: true }),
  P([R("Index Terms", { bold: true, italics: true, size: 9 }), R(": automated code review, large language models, intent clarification, ambiguity detection, mutation testing, empirical software engineering.", { bold: true, size: 9 })], { noIndent: true, after: 160 }),
];

// ---------------------------------------------------------------- sections

const intro = [
  H("I", "Introduction"),
  P(`Code review remains a bottleneck in software development, with much of a reviewer's effort spent understanding the purpose of a change ${cite("bacchelli", "sadowski")}. Tools such as CodeRabbit, Qodo, and Greptile use large language models (LLMs) to review pull requests automatically ${cite("industry")}. Although these tools can explain their findings, they share a limitation: they inspect a pull request in a single pass and provide feedback based on an inferred interpretation of the author's intent, even when that interpretation is uncertain.`),
  P("Consider a change that removes a validation check without a linked issue or a descriptive commit message. A human reviewer would typically ask the author why the check was removed. Existing automated reviewers generally proceed with the information available. If their interpretation is wrong, they may flag an intentional change as defective or overlook a genuine defect. Both outcomes can undermine the trust developers place in automated review tools."),
  P(`Clarification has been studied in code generation ${cite("clarifygpt", "ticoder")}, but its application to reviewing existing changes remains less explored. The setting is different: an incorrect assumption during code generation may lead to an unsuccessful result, whereas an incorrect review can cost a developer time and attention. This raises a practical question: can a reviewer that asks for clarification before commenting interpret changes and identify defects more effectively than one that proceeds without asking?`),
  P("This paper makes five contributions:"),
  P("1) We introduce ClarifyReview, a four-stage review system in which the second stage decides whether clarification is needed for each pull request. The system supports four interchangeable ambiguity detectors and uses a baseline that differs only in this decision stage.", { noIndent: true }),
  P(`2) We develop an evaluation design for intent-dependent code review on SWE-bench ${cite("swebench")}. It removes natural-language statements of intent without modifying the code and includes ${verified} defects verified through execution.`, { noIndent: true }),
  P("3) We conduct a two-by-three ablation and trace individual instances to distinguish the value of an author's answer from the detector's ability to identify when a question is needed. The analysis identifies detector recall as a key limitation.", { noIndent: true }),
  P("4) We report an initial pilot that led to changes in the evaluation design, together with a protocol deviation and the steps taken to address it.", { noIndent: true }),
  P("5) We examine agreement among three AI judges and replicate the experiment using a local reviewer. The replication is reported separately from the original study.", { noIndent: true, after: 80 }),
];

const related = [
  H("II", "Related Work"),
  H2("A", "Automated Code Review"),
  P(`Studies at Microsoft and Google identified understanding a proposed change as one of the most demanding parts of code review ${cite("bacchelli", "sadowski")}. Learning-based reviewers generate comments from historical review data ${cite("tufano", "codereviewer")}, while deployed LLM-based tools vary in how they retrieve and use repository context ${cite("industry")}. These approaches generally produce feedback in a single pass. ClarifyReview instead introduces a decision point at which the system can request additional information before evaluating the change.`),
  H2("B", "Clarification in Code Generation"),
  P(`ClarifyGPT identifies ambiguous requirements using a code-consistency check and asks targeted questions before generating code, improving Pass@1 performance ${cite("clarifygpt")}. TiCoder uses generated tests to help clarify user intent and reports improvements in correctness judgement and reductions in cognitive load in a study involving fifteen participants ${cite("ticoder")}. Both systems focus on generating new code rather than reviewing existing changes. Their findings also highlight the importance of making clarification targeted and selective rather than asking questions indiscriminately.`),
  H2("C", "Uncertainty Quantification"),
  P(`Self-consistency uses disagreement among multiple generated samples as an indicator of uncertainty ${cite("selfconsistency")}. Semantic uncertainty groups responses according to their meaning before measuring variation ${cite("semantic")}. We adapt these ideas to assess how consistently a reviewer interprets the intent behind a code change. The aim is to identify cases where the reviewer's interpretation may be unstable enough to warrant clarification.`),
  H2("D", "Benchmarks and Evaluation"),
  P(`SWE-bench links real software issues to the patches that resolve them and the tests that those patches pass ${cite("swebench")}. Its Verified subset underwent human validation ${cite("verified")}. Existing test suites can also be used to assess defective patch variants by checking whether the original patch passes the relevant tests while the modified version fails them ${cite("mutation")}. LLM-based judges provide another way to evaluate generated reviews, but their assessments can exhibit biases, including preferences for outputs from their own model family ${cite("judge")}. For this reason, our evaluation uses a judge from a different model family than the reviewer and separately examines agreement between judges.`),
];

const LD = N.live_demo, LP1 = LD.pr1, LP2 = LD.pr2;
const goldenOnly3 = D3.rows - 2 * D3.mutants_used;
const otherRepos3 = Object.keys(D3.repos).filter(r => !r.startsWith("sympy/")).length;

const system = [
  H("III", "ClarifyReview"),
  P(`ClarifyReview consists of four stages, as shown in Fig. 1. Stage 1 parses the diff and maps changed lines to the corresponding symbols. It uses the Python Abstract Syntax Tree (AST) for Python and tree-sitter grammars for JavaScript, TypeScript/TSX, Java, C, C++, and Rust. The system then builds a bounded context in a deterministic order and computes its fingerprint. Python behaviour remains byte-identical to the previous implementation. Stage 2 determines whether clarification is needed. If the detector decides to ask, Stage 3 generates at most two questions and sends them through a Responder. Each question must identify a file, line, or symbol, preventing vague requests such as "please explain this PR." Stage 4 produces structured review findings containing severity, category, evidence, a suggested fix, and confidence.`),
  ...figure("fig2_architecture.png", "The four stages of ClarifyReview. Stage 2 determines whether clarification is needed; Stage 3 is skipped when the system proceeds directly to review."),
  H2("A", "Ambiguity Detectors"),
  P("The four detectors share a common interface that maps a context to a score s ∈ [0, 1]. A shared decision rule triggers clarification when s ≥ τ, where the threshold τ is fixed in the configuration. The heuristic detector combines fifteen diff features, including the absence of a linked issue, a generic commit message, a removed guard, the lack of an accompanying test, changes to public symbols, and the deletion ratio. These features contribute weighted evidence according to s = Σᵢ wᵢfᵢ / Σᵢ wᵢ, where fᵢ represents a feature and wᵢ its weight. The detector requires no model call. A logistic-regression classifier learns weights for the same features from labelled pull requests. The other two detectors estimate uncertainty by generating eight one-sentence hypotheses about the purpose of a change. One uses temperature sampling, while the other perturbs the prompt at a fixed temperature. Both assess the resulting hypotheses using mean pairwise embedding distance and semantic entropy."),
  H2("B", "One Pipeline, Two Conditions"),
  P("The single-pass baseline does not use a separate implementation. It runs the same pipeline with clarification disabled. An automated test verifies that, when the detector is forced to proceed without asking, the two conditions produce byte-identical prompts."),
  P("Stage 3 communicates with the author through a Responder interface with three implementations: a GitHub responder that posts a comment and waits for a reply, a benchmark responder that queries a simulated author, and a null responder. This design allows the experiment to exercise the same interaction code intended for deployment."),
  P(`The system is written in Python and runs either as a GitHub App or from the command line. It records each run in an SQLite database and is covered by ${nTests} automated tests. Three provider backends implement a common interface: Gemini, Anthropic, and local Ollama. The Ollama backend runs the model on the user's machine without an API key, external model traffic, or per-call monetary cost. Pending runs persist across restarts, and a timeout mechanism publishes reviews when authors do not respond. The system also handles rate limits and verifies signed webhooks. It passes offline end-to-end tests and has been exercised on live GitHub in a sandbox repository.`),
  P([R("Sandbox demonstration, not an evaluation. ", { italics: true }),
     R(`We tested ${word(LD.n_prs)} constructed pull requests in the authors' sandbox repository. In the first, reviewed from the command line, the detector asked a question at a score of ${f2(LP1.score)}, above the threshold of ${f2(LP1.threshold)}. The author confirmed that removing the email check was intentional, and the reviewer's confidence increased from ${pct(LP1.without_answer.overall_confidence)} to ${pct(LP1.overall_confidence)}. The final verdict was to approve the change.`)]),
  P(`In the second case, the webhook bot operated behind a tunnel. The author's response established that removing the disabled-account check was unintended. The bot requested changes and reported ${word(LP2.n_findings)} major correctness finding. It also retried after ${word(LP2.facts.provider_retries)} transient provider errors. These demonstrations ran on a laptop using a free-tier quota and the heuristic detector. They establish that the interaction flow works, but they do not provide evidence of its effectiveness or error rates in general use.`),
];

const method = [
  H("IV", "Experimental Design"),
  P("The evaluation addresses three research questions:"),
  P("RQ1: Does clarification recover intent that would otherwise be lost when the author's stated intent is withheld?", { noIndent: true }),
  P("RQ2: Does clarification improve defect detection or reduce false alarms?", { noIndent: true }),
  P("RQ3: How effectively do the detectors identify changes for which clarification is needed?", { noIndent: true, after: 80 }),
  H2("A", "Conditions"),
  P("Each instance is reviewed three times using the same reviewer model and prompt template (Fig. 2). The first condition provides full context and serves as the ceiling. The second withholds intent and uses the single-pass baseline, serving as the floor. The third also withholds intent but enables ClarifyReview, forming the treatment condition. The floor and treatment use byte-identical code, verified by an assertion for each instance."),
  P("We measure the proportion of the context-related loss in intent recovery restored by clarification using gap recovery, G = (treatment - floor) / (ceiling - floor). This measure represents the share of the gap between the floor and ceiling that the treatment recovers."),
  ...figure("fig11_design.png", "Two-by-three evaluation design. Golden patches measure intent recovery and false alarms, while verified mutants measure intent recovery and defect detection."),
  H2("B", "Withholding Intent"),
  P("The first version of the manipulation removed the linked issue, title, description, and commit messages. However, the pilot showed that the patch could still reveal its purpose through natural-language text added alongside the code. Version 2 therefore also removes every comment, trailing comment, and docstring introduced by the patch, while leaving the code unchanged."),
  P("Docstring removal required an additional safeguard. A docstring is removed only when the patch introduces a line within it. This rule was added after an earlier implementation deleted actual code in a hunk that began inside an existing docstring. The revised procedure was designed to remove statements of intent without altering executable code."),
  H2("C", "Execution-Verified Defects"),
  P("Golden patches are correct by construction, making them suitable for measuring false alarms but not defect detection. To evaluate detection, we introduce defects into lines added by a golden patch using six mutation operators: invert a comparison, negate a condition, flip a constant, remove a guard, swap a Boolean operator, and introduce an off-by-one error."),
  P(`A mutant is retained only when the repository's FAIL_TO_PASS tests pass with the original golden patch and fail with the mutant ${cite("mutation")}. Of the ${mut.attempted} SymPy instances examined, ${verified} produced a verified mutant. For ${mut.by_status.no_mutation_applies} instances, none of the operators could be applied; ${word(mut.by_status.every_mutant_survived)} produced only mutants that the tests failed to detect; and ${word(mut.by_status.environment_cannot_run_tests)} could not be executed in the available environment.`),
  H2("D", "Instances"),
  P(`The original study contains ${N.v2_design.rows} rows. ${cap(word(N.v2_design.arms["mutant/mutant"]))} SymPy instances are represented twice, once as the golden patch and once as the corresponding verified mutant. The remaining ${word(N.v2_design.arms["golden/golden"])} rows are golden patches from xarray, sphinx, astropy, django, pylint, pytest, and scikit-learn.`),
  P("Instances were selected in descending order of difficulty using SWE-bench's own difficulty annotations. These annotations were assigned by the benchmark's annotators rather than by our detector, avoiding selection based on the behaviour of the system under evaluation."),
  H2("E", "Simulated Author, Judge, and Statistics"),
  P("When the treatment asks a question, a simulated author responds using only the withheld issue text and commit messages. The simulated author does not see the diff, the injected defect, or whether a defect exists. It must decline to answer when the available notes do not provide the necessary information. Each exchange is logged with its prompt version."),
  P(`An LLM judge from a different model family than the reviewer evaluates each review against three criteria: whether the reviewer recovered the intended purpose of the change, whether it detected the injected defect, and whether it raised a false alarm on correct code. We compare paired outcomes using McNemar's exact test ${cite("mcnemar")} and report a bootstrap 95% interval for gap recovery.`),
  P("The reviewer is gemini-3.5-flash-lite. The question generator, simulated author, and judge use gemma-4-31b-it. All model calls were made using free-tier access."),
  H2("F", "Second-Model Replication (v3)"),
  P(`The replication contains ${D3.rows} rows: the original ${N.v2_design.rows} rows and ${D3.n_new_rows} additional rows. It includes all ${D3.mutants_used} verified mutants, evaluated in both arms, together with ${goldenOnly3} golden-only rows from ${word(otherRepos3)} additional repositories. The reviewer is ${S3.reviewer_model_name}, served through Ollama, with the heuristic detector configured at τ = ${f2(S3.threshold)}.`),
  P(`All ${V3.attempted ?? D3.rows * 3} runs completed without failure in ${Math.round(S3.wall_minutes)} minutes on a laptop GPU. The question and oracle model identity was recorded in the oracle log but was not stored for each database row. The replication follows the same evaluation conditions as the original study and is reported separately rather than pooled with the original results. The choice of judge for this replication is discussed in Section V-G.`),
];

function results() {
  const out = [H("V", "Results")];
  const pt = pilot.tests?.intent_all;
  out.push(H2("A", "Pilot (Manipulation v1)"));
  out.push(P(`The pilot covered ${word(pilot.attempted)} instances from ten repositories, but only ${word(pilot.complete_triples)} completed all three conditions before the daily quota was exhausted. Intent recovery reached ${pct(pt?.ceiling)} in all three conditions: the ceiling, floor, and treatment. Because the floor already matched the ceiling, there was no loss for clarification to recover. The patches often explained their purpose in the comments and docstrings they introduced, so removing the issue information alone did not make their intent difficult to understand. This finding led to the revised manipulation (v2), the addition of the mutant arm, and selection based on benchmark difficulty.`));

  out.push(H2("B", "RQ1: Intent Recovery"));
  out.push(P(`All ${v2.complete_triples} instances completed the three evaluation conditions, and all ${v2.judged} reviews were judged (Table I, Fig. 3). Removing all natural-language statements of intent reduced recovery from ${pct(IA.ceiling)} with full context to ${pct(IA.floor)} without clarification. Enabling clarification raised recovery to ${pct(IA.treatment)}. The resulting gap recovery was ${f2(IA.gap_recovery)} (95% CI: ${ci(IA.gap_ci)}), with ${word(IA.discordant_treatment_better)} discordant pair favouring the treatment and ${IA.discordant_floor_better === 0 ? "none" : word(IA.discordant_floor_better)} favouring the floor (McNemar's p = ${f2(IA.mcnemar_p)}).`));
  out.push(P("The results follow the expected direction, but the improvement was not statistically significant. The small number of instances limits the evidence for an effect. In addition, clarification can produce a different outcome only when the detector asks a question and the resulting exchange changes the reviewer's interpretation."));
  const row = (label, t, n) => [label, fr(t.floor, n), fr(t.treatment, n), fr(t.ceiling, n), f2(t.mcnemar_p)];
  out.push(...table(["Measure", "Floor", "Treat.", "Ceiling", "p"], [
    row("Intent, all", IA, IA.n), row("Intent, golden", T.intent_golden, T.intent_golden.n), row("Intent, mutant", T.intent_mutant, T.intent_mutant.n),
    row("Defect caught", DM, DM.n), row("False alarm", FA, FA.n)],
    [1500, 760, 760, 760, 560], "Judged outcomes under manipulation v2"));
  out.push(...figure("fig7_results.png", "Outcomes across the three conditions. Bars represent proportions, with counts shown as labels."));

  out.push(H2("C", "Where the Effect Is Lost"));
  out.push(P(`For clarification to improve on the floor, three things must happen: the initial reviewer must misinterpret the change, the detector must identify the need to ask, and the author must provide a useful answer (Fig. 4). The floor misinterpreted ${word(F.floor_misses)} changes. The detector asked about ${word(F.detector_asked)} of them, the simulated author provided a substantive answer in ${word(F.author_answered)} case, and the treatment recovered the intended meaning in that case.`));
  out.push(P(`The other flagged case received no useful answer because the question concerned a parameter that was not mentioned in the issue. Of the ${word(F.asked_total)} questions asked by the detector overall, ${word(F.asked_total - F.detector_asked)} concerned changes whose intent the floor had already recovered. Answers to those questions could not improve the intent-recovery score.`));
  out.push(P("These traces suggest that clarification can help when the system identifies a genuine need for additional information. However, the number of eligible cases was too small to estimate its success rate reliably. The more immediate limitation was the detector's ability to identify changes that the reviewer was likely to misunderstand."));
  out.push(...figure("fig8_funnel.png", "Instance-level trace showing how many initial intent errors progressed through detection, author response, and successful recovery."));
  out.push(P("In the recovered case, sympy-12481, the patch allows the Permutation constructor to accept non-disjoint cycles. The floor described the change as a cleanup of permutation instantiation logic, missing its intended behaviour. The detector assigned the stripped change a score of 0.556 and asked whether removing the specialised error was intentional. The author explained that non-disjoint cycles should be applied from left to right. With this information, the treatment produced a summary consistent with the full-context condition."));

  out.push(H2("D", "RQ2: Defects and False Alarms"));
  out.push(P(`The reviewer detected ${word(Math.round(DM.floor * DM.n))} of the ${word(DM.n)} injected defects under both the floor and treatment conditions, compared with ${word(Math.round(DM.ceiling * DM.n))} under full context. The full-context result is particularly important: even when the issue was available, the reviewer approved ${word(DV.v2_defect_ceiling_missed)} of the ${word(DM.n)} defective patches. For this model, knowing the intended behaviour was not enough to ensure that the code was reviewed correctly. Its ability to recognise defects remained a major limitation.`));
  out.push(P("One mutant was detected without the issue information but was approved when that information was provided. Although this was an isolated result, it is consistent with the possibility that stated intent can sometimes lead a reviewer to accept a change without adequately examining its correctness."));
  out.push(P(`False alarms on correct patches were uncommon across all three conditions, occurring in ${Math.round(FA.floor * FA.n)} of ${FA.n} floor reviews, ${Math.round(FA.treatment * FA.n)} of ${FA.n} treatment reviews, and ${Math.round(FA.ceiling * FA.n)} of ${FA.n} ceiling reviews. The experiment therefore provides no clear evidence that clarification reduced false alarms.`));

  out.push(H2("E", "RQ3: Detectors"));
  out.push(P("For this analysis, the labels were constructed so that a context with intent removed was ambiguous by design, while its full-context counterpart was considered clear. Table II and Fig. 5 compare detector behaviour under these labels. This setup favours detectors that respond to missing issue information, so the resulting recall figures should be interpreted in light of how the labels were constructed."));
  const dn = ["heuristic", "sampling", "perturbation"].filter(n => det[n]);
  out.push(...table(["Detector", "n", "Ask", "Prec.", "Rec.", "Score s / f"],
    dn.map(n => [n[0].toUpperCase() + n.slice(1), String(det[n].n_decisions), pct(det[n].ask_rate), f2(det[n].precision), f2(det[n].recall),
      `${f2(det[n].mean_score_stripped)} / ${f2(det[n].mean_score_full)}`]),
    [1080, 380, 520, 520, 480, 1060], "Detector performance on constructed labels"));
  out.push(...figure("fig9_detectors.png", "Mean detector scores with intent withheld and with full context. Dashed lines indicate the default thresholds."));
  if (det.sampling && det.perturbation) {
    out.push(P(`The heuristic detector did not ask for clarification on any full-context instance, but it identified only ${pct(det.heuristic.recall)} of the stripped instances. This low recall helps explain why clarification had limited opportunities to improve the reviewer's interpretation.`));
    out.push(P(`The two uncertainty-based detectors required eight model calls per decision and were evaluated on ${word(det.sampling.n_decisions / 2)} instances each. At their default thresholds, both asked questions on every decision. Sampling-based uncertainty distinguished the stripped and full contexts, with mean scores of ${f2(det.sampling.mean_score_stripped)} and ${f2(det.sampling.mean_score_full)}, respectively. Re-examining the recorded scores suggests that a threshold near 0.60 might separate the two conditions. We treat this as a diagnostic observation rather than adopt the threshold, since it was identified using scores from the study set. Prompt perturbation did not distinguish the conditions: both received a mean score of ${f2(det.perturbation.mean_score_stripped)}.`));
    out.push(P("These findings highlight a trade-off between asking questions frequently and identifying the cases where they are genuinely needed. The heuristic was conservative but missed many ambiguous changes, while the uncertainty-based detectors asked too often at their default thresholds."));
  }

  // ---- V-F: the same ablation on a local reviewer. Never pooled with v2.
  const F3 = V3.funnel, IG3 = T3.intent_golden, IM3 = T3.intent_mutant;
  out.push(H2("F", "Replication on a Local Reviewer"));
  out.push(P(`Table III reports the replication results for the local reviewer, ${S3.reviewer_model_name}, served through Ollama. The outcomes were scored by the Claude agent judge, ${V3.judge_label}. As discussed in Section V-G, this judge was selected after its agreement with the local judge had been examined. The replication is reported separately and is not pooled with the original experiment.`));
  const row3 = (label, t) => [label, fr(t.floor, t.n), fr(t.treatment, t.n), fr(t.ceiling, t.n), f2(t.mcnemar_p)];
  out.push(...table(["Measure", "Floor", "Treat.", "Ceiling", "p"], [
    row3("Intent, all", IA3), row3("Intent, golden", IG3), row3("Intent, mutant", IM3),
    row3("Defect caught", DM3), row3("False alarm", FA3)],
    [1500, 760, 760, 760, 560], "Judged outcomes for the local replication (v3)"));
  out.push(...figure("fig15_v3_results.png", "Outcomes across conditions in the local replication. Counts represent instances; the figure reports gap recovery, its 95% interval, and the McNemar p-value."));
  out.push(P(`Clarification did not significantly improve intent recovery in the replication. Across ${IA3.n} instances, recovery increased from ${pct(IA3.floor)} without clarification to ${pct(IA3.treatment)} with clarification, while full context achieved ${pct(IA3.ceiling)}. Gap recovery was ${f2(IA3.gap_recovery)} (95% interval: ${ci(IA3.gap_ci)}; McNemar's p = ${f2(IA3.mcnemar_p)}). The interval includes zero and does not establish a positive effect. Its upper bound also rules out recovering more than approximately one-third of the gap under the reported interval.`));
  out.push(P(`Withholding intent reduced recovery by ${Math.round((IA3.ceiling - IA3.floor) * 100)} percentage points relative to full context, while clarification restored ${word(Math.round((IA3.treatment - IA3.floor) * 100))} percentage points. The results were also inconclusive when examined separately: gap recovery was ${f2(IG3.gap_recovery)} on golden instances (p = ${f2(IG3.mcnemar_p)}) and ${f2(IM3.gap_recovery)} on mutant instances (p = ${f2(IM3.mcnemar_p)}).`));
  out.push(P(`As in the original study, detector recall was a key limitation. The detector asked questions in ${V3.treatment_asks} of the ${V3.treatment_n} treatment reviews. Among the ${F3.floor_misses} changes whose intent the reviewer failed to recover without clarification, it asked about ${word(F3.detector_asked)} and missed ${DV.v3_detector_missed}. The simulated author provided answers in ${word(F3.author_answered)} of those ${word(F3.detector_asked)} cases, and the treatment recovered intent in ${word(F3.treatment_recovered)} of the ${F3.floor_misses} initially misinterpreted changes.`));
  out.push(P(`The effect was not uniformly positive. Clarification helped on ${IA3.discordant_treatment_better} instances and hurt on ${word(IA3.discordant_floor_better)}. Among the ${word(F3.author_answered)} cases where the simulated author answered a question about a change the floor had misinterpreted, the treatment recovered intent in ${word(F3.treatment_recovered)}. These results suggest that the main challenge lies not simply in obtaining an answer, but in identifying when asking is worthwhile. Detector recall remains a central limitation.`));
  out.push(P(`Defect detection remained low even with full context. The reviewer caught ${word(Math.round(DM3.floor * DM3.n))} of ${DM3.n} injected defects without clarification, ${word(Math.round(DM3.treatment * DM3.n))} with clarification, and ${word(Math.round(DM3.ceiling * DM3.n))} with full context, corresponding to ${pct(DM3.floor)}, ${pct(DM3.treatment)}, and ${pct(DM3.ceiling)}, respectively. The difference was not statistically significant (McNemar's p = ${f2(DM3.mcnemar_p)}). The local reviewer's limited ability to recognise defects therefore remained a constraint, consistent with the original experiment.`));
  const fa3 = x => { const k = Math.round(x * FA3.n); return k === 1 ? "once" : `${word(k)} times`; };
  out.push(P(`Among the ${FA3.n} golden instances, false alarms occurred ${fa3(FA3.floor)} without clarification, ${fa3(FA3.treatment)} with clarification, and ${fa3(FA3.ceiling)} with full context. These differences were also inconclusive (p = ${f2(FA3.mcnemar_p)}). The replication does not establish that clarification improves defect detection or reduces false alarms.`));

  // ---- V-G: agreement between AI judges. AI-vs-AI; not validation against humans.
  out.push(H2("G", "Judge Calibration"));
  out.push(P(`Three AI judges evaluated the original reviews: the API judge ${J.models.api_v2}, the Claude Sonnet agent (${V3.judge_label}), and ${J.models.gemini_web.replace(/ \(web app\)$/, "")} through the web application. The API judge and the agent each scored all ${J.v2_pairs.api_vs_agent.intent_recovered.n} original reviews; the web-application judge scored a stratified sample of ${J.gemini_sample.n} runs selected across conditions and patch variants. Table IV reports percentage agreement, Cohen's kappa, and sample size for each judge pair.`));
  out.push(P("These measurements describe agreement between AI judges. They should not be interpreted as evidence of agreement with human reviewers, which is assessed separately."));
  const cell = c => `${pct(c.percent_agreement)} / ${kap(c.kappa)} / ${c.n}`;
  const jrow = (label, pr) => [label, cell(pr.intent_recovered), cell(pr.defect_caught), cell(pr.false_alarm)];
  out.push(...table(["Judge pair", "Intent", "Defect", "False alarm"], [
    jrow(`V2: ${J.models.api_v2} vs. agent`, J.v2_pairs.api_vs_agent),
    jrow("V2: Gemini web vs. agent", J.v2_pairs.gemini_vs_agent),
    jrow(`V2: Gemini web vs. ${J.models.api_v2}`, J.v2_pairs.gemini_vs_api),
    jrow(`V3: ${J.models.api_v3} vs. agent`, J.v3_pairs.llama_vs_agent)],
    [1500, 760, 760, 760], "Agreement between AI judges (% agreement / Cohen's kappa / n)"));
  out.push(...figure("fig16_judges.png", "Cohen's kappa for pairs of AI judges. These values measure agreement between AI judges, not agreement with human reviewers."));
  const pAA = J.v2_pairs.api_vs_agent, pGA = J.v2_pairs.gemini_vs_agent, pLA = J.v3_pairs.llama_vs_agent;
  const VA = V2A.tests.intent_all, LJ = N.v3_local_llama_judge.tests.intent_all;
  out.push(P(`Compared with the agent judge, the API judge showed strong agreement on defect detection (κ = ${kap(pAA.defect_caught.kappa)}, ${pct(pAA.defect_caught.percent_agreement)} agreement, n = ${pAA.defect_caught.n}) and false alarms (κ = ${kap(pAA.false_alarm.kappa)}). Agreement on intent recovery was lower (κ = ${kap(pAA.intent_recovered.kappa)}, ${pct(pAA.intent_recovered.percent_agreement)} agreement). The Gemini web judge achieved κ = ${kap(pGA.intent_recovered.kappa)} for intent recovery against the agent judge, and all three judges agreed on intent recovery in ${J.v2_three_way_intent.all_agree} of the ${J.v2_three_way_intent.n} sampled runs.`));
  out.push(P(`When the original study was rescored using the agent judge, intent recovery was ${pct(VA.floor)} at the floor, ${pct(VA.treatment)} in the treatment, and ${pct(VA.ceiling)} at the ceiling. Gap recovery increased to ${f2(VA.gap_recovery)} (95% interval: ${ci(VA.gap_ci)}; McNemar's p = ${f2(VA.mcnemar_p)}). The conclusion remained unchanged: the effect was not statistically significant. However, its estimated magnitude differed from the value of ${f2(IA.gap_recovery)} obtained with the API judge (95% interval: ${ci(IA.gap_ci)}). These comparisons measure agreement between AI judges and do not independently establish agreement with human assessments.`));
  out.push(P(`The local judge, ${J.models.api_v3}, performed poorly in the replication. Its agreement with the agent judge was ${pct(pLA.intent_recovered.percent_agreement)} for intent recovery (κ = ${kap(pLA.intent_recovered.kappa)}, n = ${pLA.intent_recovered.n}), ${pct(pLA.defect_caught.percent_agreement)} for defect detection (κ = ${kap(pLA.defect_caught.kappa)}), and ${pct(pLA.false_alarm.percent_agreement)} for false alarms (κ = ${kap(pLA.false_alarm.kappa)}). Despite the high percentage agreement on false alarms, its kappa value indicates that this agreement did not extend beyond what would be expected from the marginal distributions. The local judge never flagged a false alarm and reported that no defect had been injected in ${N.v3_local_llama_judge.no_defect_claim_mutant.k} of the ${N.v3_local_llama_judge.no_defect_claim_mutant.n} mutant rows, or ${pct(N.v3_local_llama_judge.no_defect_claim_mutant.k / N.v3_local_llama_judge.no_defect_claim_mutant.n)}.`));
  out.push(P(`We therefore used ${V3.judge_label} as the primary judge for the replication. This choice was made after examining the agreement results, making it a post hoc decision. The local judge's own gap-recovery estimate of ${f2(LJ.gap_recovery)} (95% interval: ${ci(LJ.gap_ci)}) is included for reference only. Its intent-recovery rates across the floor, treatment, and ceiling were ${pct(LJ.floor)}, ${pct(LJ.treatment)}, and ${pct(LJ.ceiling)}, respectively. These comparisons remain AI-to-AI evaluations. Only the API judge used in the original study was checked against human scorers; the judges used for the replication were not.`));

  // ---- V-H: the full v3 rows on the original (v2) reviewer, question, oracle and judge models.
  if (G3) {
    const t = G3.tests, ia = t.intent_all, dd = G3.discordant, fu = G3.funnel, fg = t.false_alarm_golden;
    out.push(H2("H", "Replication Set on the Original Reviewer"));
    out.push(P(`The results in Sections V-B and V-F differ in both the instances evaluated and the reviewer model. To examine the effect of changing the reviewer independently of the dataset, we ran all ${D3.rows} replication instances through the original reviewer, ${G3.review_models.join(", ")}, using the original question, author, and judge models (${G3.judge_model}).`));
    out.push(P(`Three conditions were completed for ${G3.complete_triples} instances. For the remaining ${word(D3.rows - G3.complete_triples)}, the question model returned a server error on every attempt.`));
    out.push(...table(["Measure", "Floor", "Treat.", "Ceiling", "p"], [
      row3("Intent, all", ia), row3("Intent, golden", t.intent_golden), row3("Intent, mutant", t.intent_mutant),
      row3("Defect caught", t.defect_mutant), row3("False alarm", fg)],
      [1500, 760, 760, 760, 560], "Judged outcomes for the replication set on the original reviewer"));
    out.push(P(`Intent recovery was ${pct(ia.floor)} with intent withheld, ${pct(ia.treatment)} with clarification, and ${pct(ia.ceiling)} with full context. Gap recovery was ${f2(ia.gap_recovery)} (95% interval: ${ci(ia.gap_ci)}; McNemar's p = ${f2(ia.mcnemar_p)}). Although the interval excludes zero, the paired test does not reach the conventional significance threshold. The instance-level trace also raises doubts about attributing the observed difference to clarification.`));
    out.push(P(`The detector asked questions on ${G3.treatment_asks} of the ${G3.treatment_n} instances, but the simulated author provided a substantive answer in only ${word(fu.answered_total)} cases. Among the ${fu.floor_misses} instances misinterpreted at the floor, the detector asked about ${word(fu.detector_asked)} and recovered intent in ${fu.treatment_recovered === 0 ? "none" : word(fu.treatment_recovered)}. Of the ${word(dd.total)} discordant floor-treatment pairs, ${word(dd.not_asked)} came from instances where no question was asked. In those cases, the reviewer received identical input in both conditions, yet the outcomes differed in ${word(dd.not_asked_treatment_better)} cases in one direction and ${word(dd.not_asked_floor_better)} in the other. This pattern points to run-to-run variation in the reviewer rather than an effect of clarification.`));
    out.push(P(`Clarification also increased false alarms on golden patches, from ${word(Math.round(fg.floor * fg.n))} of ${fg.n} at the floor to ${word(Math.round(fg.treatment * fg.n))} of ${fg.n} in the treatment. Taken together, these results show why a single review per condition is insufficient to separate clarification effects from variation in model outputs. Repeated evaluations per condition or a deterministic reviewer would provide a stronger basis for attribution.`));
  }
  return out;
}

const discussion = [
  H("VI", "Discussion"),
  P("Adding a clarification step is straightforward. Deciding when to use it effectively is more difficult. When a question reached an author who could provide the missing information, clarification sometimes helped the reviewer recover the intended behaviour. Most opportunities for improvement were lost earlier, when the detector failed to identify a change that the reviewer would misunderstand. This shifts the central problem from generating good questions to identifying when a question is warranted, while keeping unnecessary interruptions manageable."),
  P("The detector results illustrate this trade-off. The heuristic detector was conservative and achieved high precision, but its recall was low. Sampling-based uncertainty distinguished the stripped and full-context conditions in the small evaluation, although its threshold needs to be calibrated on held-out data. Prompt perturbation did not separate the two conditions under the tested configuration. These results do not establish that any detector is ready for general deployment."),
  P("Golden patches also present a limitation for studying ambiguity. Well-written changes often explain their purpose through the code, comments, and docstrings they introduce. Removing only the linked issue therefore leaves substantial information available to the reviewer. Even after all natural-language statements of intent were removed, many changes remained understandable from the code itself. Future evaluations would benefit from benchmarks containing changes whose intended behaviour is genuinely under-specified."),
  P("Clarification is also constrained by the underlying reviewer's capabilities. In both the original experiment and the local replication, defect detection remained low even when full context was available. A reviewer that cannot reliably recognise an injected defect is unlikely to gain much from learning more about the author's intent. Stronger reviewers may be needed before the effect of clarification on defect detection can be meaningfully assessed."),
  P(`Across the two reviewers and judge configurations, the qualitative findings were similar: detector recall limits the opportunities for clarification, defect detection remains constrained by the reviewer, and the experiments do not establish a statistically significant improvement in intent recovery. However, the estimated effect size depends on the judge. In the original study, gap recovery was ${f2(IA.gap_recovery)} with the API judge (95% interval: ${ci(IA.gap_ci)}) and ${f2(V2A.tests.intent_all.gap_recovery)} with the agent judge (95% interval: ${ci(V2A.tests.intent_all.gap_ci)}). In the ${IA3.n}-instance replication, gap recovery was ${f2(IA3.gap_recovery)} with the agent judge (95% interval: ${ci(IA3.gap_ci)}). The evidence therefore does not establish a reliable positive effect across these evaluations, and the estimates should be interpreted alongside the judge and reviewer that produced them.`),
];

// Human-step results (labelling, judge validation, Study B). Each block exists only
// when collect.py found the matching result file; with none of them, every sentence
// below is exactly the text the paper had before those steps were run.
const HUM = N.human || {};
const HL = HUM.labelling?.available ? HUM.labelling : null;
const HT = HUM.thresholds?.available ? HUM.thresholds : null;
const HJ = HUM.judge_validation?.available ? HUM.judge_validation : null;
const HB = HUM.study_b?.available ? HUM.study_b : null;
const pf = x => (x === null || x === undefined || Number.isNaN(x)) ? "n/a" : (x < 0.001 ? "< 0.001" : Number(x).toFixed(3));
const joinList = xs => xs.length <= 2 ? xs.join(" and ") : xs.slice(0, -1).join(", ") + ", and " + xs[xs.length - 1];

function judgeSentence() {
  if (!HJ) return null;
  const M = HJ.metrics || {};
  const I = M.intent_recovered, Dc = M.defect_caught, Fa = M.false_alarm;
  if (!I && !Dc && !Fa) return null;
  const who = `${HJ.n_scorers} independent human scorer${HJ.n_scorers === 1 ? "" : "s"}`;
  let txt = `The judge was validated against ${who} on a stratified sample of ${(I || Dc || Fa).n} of its own reviews, shown without the judge's answers or the condition; blank cells were excluded, not counted as disagreement.`;
  if (Dc && Fa) {
    txt += ` On defects and false alarms it agreed with them almost perfectly (Cohen's κ ${cite("cohen")} ${f2(Dc.kappa_mean)} and ${f2(Fa.kappa_mean)}; ${pct(Dc.percent_agreement_mean)} and ${pct(Fa.percent_agreement_mean)} agreement).`;
  }
  if (I) {
    txt += ` On intent recovery it agreed on ${pct(I.percent_agreement_mean)} of reviews, but κ was ${f2(I.kappa_mean)}`;
    if (I.human_yes_rate !== undefined && I.judge_yes_rate < I.human_yes_rate) {
      txt += `: the humans judged intent recovered in ${pct(I.human_yes_rate)} of reviews and the judge in ${pct(I.judge_yes_rate)}, so the near-zero κ reflects one dominant answer rather than random agreement. The judge is the stricter of the two, so the intent recovery rates reported here are conservative rather than inflated.`;
    } else {
      txt += ".";
    }
  }
  return txt;
}

function humanParas() {
  const out = [];
  if (HL) {
    const thr = HT ? ` Thresholds were frozen on a development split of these labels (${HT.n_labels} labelled, ${HT.n_ambiguous} ambiguous) before any threshold-dependent evaluation; note that Study A itself ran with the default thresholds.` : "";
    out.push(P(`Human labelling. Two annotators independently labelled ${HL.n} pull requests as clear or unclear from the code change alone; Cohen's κ ${cite("cohen")} was ${f2(HL.kappa)} (${HL.reading}, observed agreement ${pct(HL.observed_agreement)}). ${HL.n_adjudicated_by_ai ? `The ${HL.n_disagree} disagreements were adjudicated by an AI model (${HL.adjudicated_by}) applying the same codebook, at the authors' request; these ${HL.n_adjudicated_by_ai} labels are therefore not human judgements.` : `The ${HL.n_disagree} disagreements were resolved by adjudication; adjudicators could consult an automatic heuristic suggestion, which is a weak aid and not a label.`}${thr}`));
  }
  if (HB) {
    const u = HB.usefulness || {}, t = HB.trust || {}, w = HB.would_act || {};
    const bit = (name, d) => d && d.n ? `${name} (n = ${d.n}; plain ${f2(d.mean_a)}, clarify ${f2(d.mean_b)}; Wilcoxon p = ${pf(d.p_value)}, rank-biserial r = ${f2(d.effect_size_r)})` : null;
    const act = (w.plain?.n && w.clarify?.n) ? ` The share who would act on the review was ${pct(w.plain.rate)} for plain and ${pct(w.clarify.rate)} for clarify.` : "";
    out.push(P(`Developer study. ${HB.participants} participants rated paired reviews blind to condition: ${joinList([bit("usefulness", u), bit("trust", t)].filter(Boolean))}.${act}`));
  }
  return out;
}

const threats = (() => {
  const M = HJ?.metrics || {}, I = M.intent_recovered, Dc = M.defect_caught, Fa = M.false_alarm;
  const out = [H("VII", "Threats to Validity")];
  out.push(P(`The original study includes only ${v2.complete_triples} instances, partly because of per-model daily quotas, resulting in wide confidence intervals.` + (HJ ? ` The judge was evaluated against ${word(HJ.n_scorers)} independent human scorers on a stratified sample of ${(I || Dc || Fa).n} of its reviews. The reviews were presented without the judge's answers or the experimental condition, and blank responses were excluded rather than counted as disagreements.` : "")));
  if (HJ && I && Dc && Fa) {
    out.push(P(`For defect detection and false alarms, agreement with the human scorers was high: Cohen's κ ${cite("cohen")} was ${f2(Dc.kappa_mean)} and ${f2(Fa.kappa_mean)}, respectively, with ${pct(Dc.percent_agreement_mean)} and ${pct(Fa.percent_agreement_mean)} observed agreement. For intent recovery, observed agreement was ${pct(I.percent_agreement_mean)}, but κ was ${f2(I.kappa_mean)}. The humans judged intent to have been recovered in ${pct(I.human_yes_rate)} of reviews, compared with ${pct(I.judge_yes_rate)} for the judge. The near-zero kappa therefore reflects the highly imbalanced distribution of judgements and does not, by itself, indicate that the observed agreement was random. The judge was stricter than the human scorers on intent recovery, so the reported rates may be conservative under this evaluation.`));
  }
  out.push(P("The simulated author was restricted to the withheld issue text and commit messages. However, possible information leakage still requires the manual audit supported by the evaluation tooling. We also report a protocol deviation from the first v2 run. The simulated author's token budget was consumed by the model's internal reasoning, resulting in empty answers. Its prompt also rejected questions phrased in terms of code it could not see. Both issues were addressed, and the treatment was rerun for the six affected instances. The floor and ceiling conditions were not rerun. Because the prompt was revised after the refusals were observed, this change may have influenced the treatment results; the revised prompt and each exchange are recorded in the study log."));
  out.push(P("All verified mutants came from SymPy, and the mutation operators introduced relatively simple defects. The findings may therefore not generalise to more complex defects or changes in other repositories. Finally, the original reviewer is a relatively small model. Stronger models may interpret intent and identify defects differently, so the results should not be assumed to apply to all LLM-based code reviewers."));
  out.push(P(`The replication introduces additional limitations. Both studies use relatively small samples: ${v2.complete_triples} instances in the original study and ${IA3.n} in the replication, resulting in wide intervals. The agent judge was selected after its agreement with the local judge had been examined, making this a post hoc choice. The question and oracle models are also small, and their identities are recorded in the oracle log but not for each database row. The studies differ in their instances, reviewer models, and judges, so their results are reported separately rather than pooled. Furthermore, a single review per condition cannot distinguish the effect of clarification from the reviewer's own run-to-run variation.`));
  out.push(P(`The live GitHub demonstration involved ${word(LD.n_prs)} constructed pull requests in the authors' sandbox repository, run from a laptop through a tunnel. It demonstrates that the interaction flow works, but provides no estimate of effectiveness. The system has not been evaluated live on real third-party pull requests, and the ${RP.n_prs} real pull requests collected so far remain unlabelled.`));
  if (HL) {
    out.push(P([R("Human labelling. ", { bold: true }),
      R(`Two annotators independently labelled ${HL.n} pull requests as clear or unclear based on the code change alone. Cohen's κ ${cite("cohen")} was ${f2(HL.kappa)}, with ${pct(HL.observed_agreement)} observed agreement. The ${word(HL.n_disagree)} disagreements were adjudicated using an AI model, ${HL.adjudicated_by.replace(/ \((.*), AI\)$/, " ($1)")}, applying the same codebook at the authors' request. These ${word(HL.n_adjudicated_by_ai)} labels therefore do not represent human judgements alone.` + (HT ? ` Detector thresholds were fixed using a development split of the labelled data, which contained only ${word(HT.n_ambiguous)} ambiguous cases in total, before any threshold-dependent evaluation. Study A itself used the default thresholds.` : ""))]));
  }
  if (HB) out.push(...humanParas().slice(HL ? 1 : 0));
  return out;
})();

const conclusion = [
  H("VIII", "Conclusion"),
  P("ClarifyReview adds a decision before code review feedback: when the intent behind a change cannot be determined from the available information, the system can ask the author for clarification. Evaluating this approach required removing all natural-language statements of intent, since golden patches often explain their purpose through the text they introduce."),
  P(`Under this manipulation, clarification recovered ${f2(IA.gap_recovery)} of the intent gap across ${v2.complete_triples} instances. The result was in the expected direction but was not statistically significant. Instance-level analysis showed that clarification could recover intent when the detector identified an opportunity to ask, while low detector recall limited how often this could happen.`),
  P(`The replication using a local reviewer also found no statistically significant improvement, with gap recovery of ${f2(IA3.gap_recovery)} (95% interval: ${ci(IA3.gap_ci)}; McNemar's p = ${f2(IA3.mcnemar_p)}). The upper bound rules out recovering more than approximately one-third of the gap under the reported interval. The estimated effect also varied depending on which judge evaluated the reviews, so the magnitude of the effect remains uncertain.`),
  P(`Future work will label the ${RP.n_prs} real pull requests already collected, conduct a paired developer study to assess usefulness and trust, host the bot permanently, and evaluate it on real third-party pull requests at scale. Further experiments should also repeat reviews under each condition to distinguish clarification effects from run-to-run variation and use a stronger reviewer to investigate whether clarification can improve defect detection.`),
];

const ack = [
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 120, after: 60 },
    children: [R("Acknowledgment", { sc: true })] }),
  P("The authors thank the School of Computer Science and Engineering at Vellore Institute of Technology for supporting this work."),
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
