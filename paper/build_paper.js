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
    children: [R("ClarifyReview: Ambiguity-Aware Intent Clarification for LLM-Based Pull Request Code Review", { size: 22 })] }),
  ...[["Yashika Gupta", "Pratyaksh Gupta", "Arivoli A"]].map(names => new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { after: 20 },
    children: [R(names.join("        "), { size: 11 })] })),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 20 }, children: [
    R("School of Computer Science and Engineering", { size: 10, italics: true })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 240 }, children: [
    R("Vellore Institute of Technology, Vellore, India", { size: 10, italics: true })] }),
];

const abstractText =
  "An LLM-based PR reviewer would usually read a change, deduce its intent from that reading, and provide comments " +
  "based on that understanding. If the intent is not clear, the reviewer might misinterpret its meaning. We propose " +
  "ClarifyReview, a system that first infers whether the input context is adequate before generating feedback and, " +
  "if not, asks the author a targeted question to obtain more context. The single-pass baseline is the same pipeline " +
  "without clarification, which isolates the effect of this decision stage. ClarifyReview is tested in a two-by-three " +
  "ablation on SWE-bench Verified, which consists of correct patches and defective variants selected from " +
  `${verified} execution-verified mutants. Each instance is evaluated in three scenarios: intent withheld, intent ` +
  "withheld with clarification, and complete context. The first pilot revealed that removing just the linked issue " +
  "was not enough, since the patch itself often disclosed its intent. We therefore deleted all natural-language " +
  `statements of intent but kept the code. Across ${IA.n} instances, intent recovery was ${pct(IA.floor)} without ` +
  `clarification, ${pct(IA.treatment)} with clarification, and ${pct(IA.ceiling)} with full context. The resulting ` +
  `gap recovery was ${f2(IA.gap_recovery)} and the McNemar p-value was ${f2(IA.mcnemar_p)}. From an instance-level ` +
  "perspective, clarification could recover the intent when the detector decided to ask, but detector recall is a " +
  `significant challenge: only ${word(F.detector_asked)} of the ${word(F.floor_misses)} changes whose intent the ` +
  "reviewer misunderstood were flagged. Even with full context, defect detection was still low, suggesting that " +
  "performance is limited not just by a lack of intent but by the reviewer's ability to detect defects. Additionally, " +
  `we repeated the test on ${V3.complete_triples} instances with a local model, ${S3.reviewer_model_name}. Intent ` +
  `recovery was ${pct(IA3.floor)} without clarification, ${pct(IA3.treatment)} with clarification, and ` +
  `${pct(IA3.ceiling)} with full context. Gap recovery was ${f2(IA3.gap_recovery)} (95% interval: ` +
  `${f2(IA3.gap_ci[0])} to ${f2(IA3.gap_ci[1])}), which was not statistically significant. Re-scoring the original ` +
  "study with another judge did not alter the overall conclusion, but did alter the estimated effect. " +
  (G3 ? `Assessing the replication set with the original reviewer raised intent recovery from ${pct(G3.tests.intent_all.floor)} to ${pct(G3.tests.intent_all.treatment)}. However, in ${word(G3.discordant.not_asked)} of the ${word(G3.discordant.total)} instances whose outcome changed, no clarification question had been asked, which points to run-to-run variation of the reviewer rather than clarification. ` : "") +
  "The system is released together with the evaluation harness, the verified mutants and the study log.";

const abstract = [
  P([R("Abstract", { bold: true, italics: true, size: 9 }), R(": " + abstractText, { bold: true, size: 9 })], { noIndent: true }),
  P([R("Index Terms", { bold: true, italics: true, size: 9 }), R(": automated code review, large language models, intent clarification, ambiguity detection, mutation testing, empirical software engineering.", { bold: true, size: 9 })], { noIndent: true, after: 160 }),
];

// ---------------------------------------------------------------- sections

const intro = [
  H("I", "Introduction"),
  P(`A major hurdle in software development is code review, where much of a reviewer's time is dedicated to understanding the reason for a change ${cite("bacchelli", "sadowski")}. Current tools like CodeRabbit, Qodo, and Greptile leverage large language models (LLMs) to automatically review pull requests ${cite("industry")}. While these can give explanations for their results, they are all limited by the fact that they examine a pull request only once and give feedback based on their own interpretation of the author's intent, even when that interpretation is not clearly correct.`),
  P("Think about a change that removes a validation check, for which there is no related issue and whose commit message provides no description. A human reviewer would normally ask the author the reason for the removal of the check. Current auto-reviewers usually proceed with the information that is available. If they come up with a wrong interpretation, they might flag an intended change as a defect, or miss a defect that is real. Both results can erode the trust that developers put in automated review tools."),
  P(`Clarification has been studied in the code generation area ${cite("clarifygpt", "ticoder")} but not so much in the field of reviewing existing changes. The setting is different: if there is a mistake in code generation, the result may not be achieved, but if a review is incorrect, it costs the developer time and attention. So, a practical question is: will a reviewer that asks for clarification before commenting interpret changes and detect defects better than a reviewer that does not ask?`),
  P("This paper contributes to the literature in five ways:"),
  P("1) We present ClarifyReview, a four-stage review system that determines in its second stage whether a pull request requires clarification. The system has four interchangeable ambiguity detectors, and its baseline differs only at this decision stage.", { noIndent: true }),
  P(`2) We design an evaluation of intent-dependent code review on SWE-bench ${cite("swebench")}. It removes natural-language statements of intent without changing the code, and includes ${verified} defects that have been verified by execution.`, { noIndent: true }),
  P("3) We perform a two-by-three ablation and trace each instance to separate the value of the author's answer from the ability of the detector to detect the need for a question. One of the limitations identified in this analysis is detector recall.", { noIndent: true }),
  P("4) We report an initial pilot that resulted in a change in the evaluation design, together with a protocol deviation and the steps taken to deal with it.", { noIndent: true }),
  P("5) We compare the agreement of three AI judges and repeat the experiment with a local reviewer. The replication is reported separately from the original study.", { noIndent: true, after: 80 }),
];

const related = [
  H("II", "Related Work"),
  H2("A", "Automatic Code Review"),
  P(`Research at Microsoft and Google found that comprehending a proposed change is one of the most challenging aspects of code review ${cite("bacchelli", "sadowski")}. Learning-based reviewers produce comments based on past review information ${cite("tufano", "codereviewer")}, and deployed LLM-based tools have different ways of retrieving and utilizing repository context ${cite("industry")}. In general, these techniques yield feedback in a single pass. ClarifyReview introduces a decision point at which the system can ask for more information prior to evaluating the change.`),
  H2("B", "Clarification in Code Generation"),
  P(`ClarifyGPT identifies ambiguous requirements with a code-consistency check and asks a set of targeted questions before generating code, enhancing Pass@1 performance ${cite("clarifygpt")}. TiCoder uses generated tests to clarify user intent; in a study with fifteen participants, it improved correctness judgement and lessened cognitive load ${cite("ticoder")}. Both systems are based on creating new code rather than reviewing changes. Their conclusions also emphasize the need to ask a few targeted questions rather than many broad ones.`),
  H2("C", "Uncertainty Quantification"),
  P(`Self-consistency treats disagreement among multiple sampled outputs as a signal of uncertainty ${cite("selfconsistency")}. Semantic uncertainty groups responses by meaning before variation is measured ${cite("semantic")}. We adapt these ideas to measure how consistently a reviewer interprets the intent of a code change. The intention is to pinpoint the cases in which the reviewer's interpretation is not strong enough to stand without additional clarification.`),
  H2("D", "Benchmarks and Evaluation"),
  P(`SWE-bench connects actual software issues with the patches that fix them and the tests that those patches pass ${cite("swebench")}. Its Verified subset has been human validated ${cite("verified")}. Existing test suites can also be used to evaluate defective patch variants, since it is straightforward to check whether the original patch passes the relevant tests while the modified one fails them ${cite("mutation")}. Another approach to evaluating generated reviews is to use LLM-based judges, which can have biases such as favouring outputs from their own model family ${cite("judge")}. Therefore, our evaluation uses a judge from a different model family than the reviewer and separately measures agreement between judges.`),
];

const LD = N.live_demo, LP1 = LD.pr1, LP2 = LD.pr2;
const goldenOnly3 = D3.rows - 2 * D3.mutants_used;
const otherRepos3 = Object.keys(D3.repos).filter(r => !r.startsWith("sympy/")).length;

const system = [
  H("III", "ClarifyReview"),
  P(`There are four stages in ClarifyReview, as illustrated in Fig. 1. Stage 1 parses a diff and maps changed lines to the symbols they affect. It uses the Abstract Syntax Tree (AST) for Python and tree-sitter grammars for JavaScript, TypeScript/TSX, Java, C, C++ and Rust. The system then builds a bounded context in a deterministic order and derives its fingerprint. Python behaviour is the same as before. In Stage 2, the need for clarification is determined. If the detector elects to ask, Stage 3 generates at most two questions and passes them to the Responder. Vague questions like "please explain this PR" are not allowed: each question must name a file, line, or symbol. The findings in Stage 4 are structured and include severity, category, evidence, suggested fix and confidence.`),
  ...figure("fig2_architecture.png", "The four stages of ClarifyReview. Stage 2 decides whether clarification is necessary; if it is not, Stage 3 is omitted and the system goes straight to review."),
  H2("A", "Ambiguity Detectors"),
  P("The four detectors have a common interface which maps a context to a score s ∈ [0, 1]. When s ≥ τ, clarification is triggered by a shared decision rule, with the threshold τ fixed in the configuration. The heuristic detector combines fifteen diff features, such as no linked issue, a generic commit message, a removed guard, no accompanying test, public symbol changes, and the deletion ratio. The features contribute weighted evidence in the form s = Σᵢ wᵢfᵢ / Σᵢ wᵢ, where fᵢ is a feature and wᵢ its weight. The detector needs no model call. A logistic-regression classifier learns weights for the same features from labelled pull requests. The other two detectors estimate uncertainty by creating eight one-sentence hypotheses about the purpose of a change. One of these perturbs the prompt at a fixed temperature; the other uses temperature sampling. Both score the resulting hypotheses with mean pairwise embedding distance and semantic entropy."),
  H2("B", "One Pipeline, Two Conditions"),
  P("The single-pass baseline is not a separate implementation. It is the same pipeline, but without the clarification. An automatic test confirms that, if the detector is forced to proceed without asking, the two conditions produce byte-identical prompts."),
  P("Stage 3 provides a Responder interface for communicating with the author, with three implementations: a GitHub responder, which posts a comment on the pull request and waits for a response; a benchmark responder, which queries a simulated author; and a null responder. This design lets the experiment use the same interaction code that is deployed."),
  P(`It is implemented in Python and is deployed either as a GitHub App or via the command line. It stores each run in an SQLite database and is tested automatically with ${nTests} tests. There are three provider backends with a shared interface (Gemini, Anthropic, local Ollama). The Ollama backend runs on the user's machine without an API key, without sending model traffic to an external service, and without any monetary cost per call. Runs that are in progress are carried over through restarts, and a timeout mechanism publishes reviews when authors fail to respond. It also handles rate limits and checks signed webhooks. It passes offline end-to-end testing and has been tested in a sandbox repository on live GitHub.`),
  P([R("Sandbox demonstration, not an evaluation. ", { italics: true }),
     R(`We tested ${word(LD.n_prs)} constructed pull requests in the authors' sandbox repository. The first was reviewed from the command line, where the detector asked a question at a score of ${f2(LP1.score)}, above the threshold of ${f2(LP1.threshold)}. The author stated that removing the email check was intentional, and the reviewer's confidence rose from ${pct(LP1.without_answer.overall_confidence)} to ${pct(LP1.overall_confidence)}. The final decision was to approve the change.`)]),
  P(`The second case was an example of the webhook bot running behind a tunnel. The author's response established that removing the disabled-account check was not intended. The bot requested changes and reported ${word(LP2.n_findings)} major correctness finding. It also retried after ${word(LP2.facts.provider_retries)} transient provider errors. These demonstrations ran on a laptop with a free-tier quota and the heuristic detector. They establish that the interaction flow is functional, but they give no evidence of its effectiveness or error rates in general use.`),
];

const method = [
  H("IV", "Experimental Design"),
  P("The evaluation focuses on three research questions:"),
  P("RQ1: Does clarification restore intent that is lost when the author's stated intent is withheld?", { noIndent: true }),
  P("RQ2: Does clarification help detect defects or reduce false alarms?", { noIndent: true }),
  P("RQ3: How effective are the detectors at identifying changes for which clarification is required?", { noIndent: true, after: 80 }),
  H2("A", "Conditions"),
  P("Each instance is reviewed three times, with the same reviewer model and prompt template (Fig. 2). The first condition gives the whole context and is the upper limit, the ceiling. The second withholds intent and is the single-pass baseline, which is the floor. The third also withholds intent but enables ClarifyReview, the treatment condition. The floor and treatment contain byte-identical code, which is asserted for every instance."),
  P("Gap recovery, G = (treatment - floor) / (ceiling - floor), measures the proportion of the loss in intent recovery that clarification recovers. This is the portion of the gap between the floor and ceiling that the treatment is able to recover."),
  ...figure("fig11_design.png", "Two-by-three evaluation design. Golden patches measure intent recovery and false alarms, while verified mutants measure intent recovery and defect detection."),
  H2("B", "Withholding Intent"),
  P("In the first implementation, the linked issue, title, description, and commit messages were deleted. But the pilot demonstrated that the purpose of a patch could still show through the natural-language text added alongside the code. The second version therefore also removes all the comments, trailing comments and docstrings added by the patch, while leaving the code unchanged."),
  P("Docstring removal needed an additional safeguard. A docstring is only removed when the patch adds a line inside it. This rule was introduced after an earlier implementation removed actual code from a hunk that started within an existing docstring. The revised procedure was created to eliminate statements of intent while keeping the executable code the same."),
  H2("C", "Execution-Verified Defects"),
  P("Golden patches are correct by construction, so they can be used for measuring false alarms but not defect detection. For evaluating detection, we added defects to the lines of a golden patch using six mutation operators: invert a comparison, negate a condition, flip a constant, remove a guard, swap a Boolean operator and introduce an off-by-one error."),
  P(`A mutant is retained only if the repository's FAIL_TO_PASS tests pass with the original golden patch and fail with the mutant ${cite("mutation")}. A verified mutant was found in ${verified} of the ${mut.attempted} SymPy instances. No operator could be applied in ${mut.by_status.no_mutation_applies} cases, ${word(mut.by_status.every_mutant_survived)} cases produced only mutants that the tests failed to detect, and ${word(mut.by_status.environment_cannot_run_tests)} cases could not be executed in the available environment.`),
  H2("D", "Instances"),
  P(`There are ${N.v2_design.rows} rows in the original study. ${cap(word(N.v2_design.arms["mutant/mutant"]))} SymPy instances appear twice, once as the golden patch and once as the verified mutant. The other ${word(N.v2_design.arms["golden/golden"])} rows are golden patches from xarray, sphinx, astropy, django, pylint, pytest and scikit-learn.`),
  P("Instances were chosen in descending order of difficulty using SWE-bench's own difficulty annotations. The annotators of the benchmark decided on these annotations, not our detector, so selection did not depend on the behaviour of the system being evaluated."),
  H2("E", "Simulated Author, Judge, and Statistics"),
  P("If the treatment asks a question, a simulated author answers based only on the withheld issue text and commit messages. The simulated author cannot see the diff, the injected defect, or whether a defect exists. It must decline to answer if its notes do not provide the required information. All exchanges are recorded with the prompt version."),
  P(`Each review is judged by an LLM from a different model family than the reviewer against three criteria: did the reviewer recover the purpose of the change, did it find the injected defect, and did it raise a false alarm on correct code? We use McNemar's exact test ${cite("mcnemar")} for comparing paired outcomes and report a bootstrap 95% interval for gap recovery.`),
  P("The reviewer is gemini-3.5-flash-lite. The question generator, simulated author and judge use gemma-4-31b-it. All model calls were performed with free-tier access."),
  H2("F", "Second-Model Replication (v3)"),
  P(`The replication has ${D3.rows} rows: the original ${N.v2_design.rows} rows and ${D3.n_new_rows} additional rows. It contains all ${D3.mutants_used} verified mutants, evaluated in both arms, as well as ${goldenOnly3} golden-only rows from ${word(otherRepos3)} additional repositories. The reviewer is ${S3.reviewer_model_name}, served through Ollama, with the heuristic detector set to τ = ${f2(S3.threshold)}.`),
  P(`All ${V3.attempted * 3} runs (${V3.attempted} instances in three conditions) completed without failure in ${Math.round(S3.wall_minutes)} minutes on a laptop GPU. The question and oracle model identity was recorded in the oracle log, but was not stored per database row. The replication follows the same conditions of evaluation as the original study and is not pooled with the original results. The choice of judge for this replication is discussed in Section V-G.`),
];

function results() {
  const out = [H("V", "Results")];
  const pt = pilot.tests?.intent_all;
  out.push(H2("A", "Pilot (Manipulation v1)"));
  out.push(P(`The pilot covered ${word(pilot.attempted)} instances from ten repositories, of which only ${word(pilot.complete_triples)} completed all three conditions before the daily quota was reached. The ceiling, floor and treatment conditions all had ${pct(pt?.ceiling)} intent recovery. Since the floor already equalled the ceiling, there was nothing for clarification to recover. The comments and docstrings added by the patches often explained their purpose, so removing the issue information was not enough to obscure the intent of the patch. Based on this finding, the revised manipulation (v2), the addition of the mutant arm and selection by benchmark difficulty were introduced.`));

  out.push(H2("B", "RQ1: Intent Recovery"));
  out.push(P(`All ${v2.complete_triples} instances were completed under the three evaluation conditions, and all ${v2.judged} reviews were judged (Table I, Fig. 3). Removing all natural-language statements of intent led to a drop in recovery from ${pct(IA.ceiling)} (with full context) to ${pct(IA.floor)} (without clarification). Clarification resulted in ${pct(IA.treatment)} recovery. This gives a gap recovery of ${f2(IA.gap_recovery)} (95% CI: ${ci(IA.gap_ci)}); ${word(IA.discordant_treatment_better)} discordant pair favoured the treatment and ${IA.discordant_floor_better === 0 ? "none" : word(IA.discordant_floor_better)} favoured the floor (McNemar's p = ${f2(IA.mcnemar_p)}).`));
  out.push(P("Results were in the predicted direction, but not statistically significant. The evidence for an effect is weak because of the small number of cases. Further, clarification can change an outcome only when the detector poses a question and the answer changes the reviewer's interpretation."));
  const row = (label, t, n) => [label, fr(t.floor, n), fr(t.treatment, n), fr(t.ceiling, n), f2(t.mcnemar_p)];
  out.push(...table(["Measure", "Floor", "Treat.", "Ceiling", "p"], [
    row("Intent, all", IA, IA.n), row("Intent, golden", T.intent_golden, T.intent_golden.n), row("Intent, mutant", T.intent_mutant, T.intent_mutant.n),
    row("Defect caught", DM, DM.n), row("False alarm", FA, FA.n)],
    [1500, 760, 760, 760, 560], "Judged outcomes under manipulation v2"));
  out.push(...figure("fig7_results.png", "Results for the three conditions. Bars indicate proportions; counts are given as labels."));

  out.push(H2("C", "Where the Effect Is Lost"));
  out.push(P(`For clarification to improve on the floor, three things need to occur: the reviewer needs to misunderstand the change, the detector needs to detect the need to ask, and the author needs to give a useful answer (Fig. 4). The floor missed ${word(F.floor_misses)} changes. The detector asked about ${word(F.detector_asked)} of these, the simulated author supplied a meaningful answer in ${word(F.author_answered)} of them, and that answer led to recovery of the intended meaning.`));
  out.push(P(`The other flagged case did not receive a useful answer, as the question was about a parameter not stated in the issue. Of the ${word(F.asked_total)} questions the detector asked overall, ${word(F.asked_total - F.detector_asked)} were about changes whose intent the floor had already recovered. Answers to those questions could not increase the intent-recovery score.`));
  out.push(P("These traces indicate that clarification can be useful when the system recognises a true need for further information. The number of eligible cases was small, however, making it difficult to estimate the success rate accurately. The more immediate constraint was detecting the changes that the reviewer would likely misinterpret."));
  out.push(...figure("fig8_funnel.png", "Per-instance trace showing how many initial intent errors were detected, answered by the author, and successfully recovered."));
  out.push(P("In the recovered case, sympy-12481, the patch enables the Permutation constructor to take non-disjoint cycles. The floor described the change as a \"cleanup of permutation instantiation logic\", missing its intended behaviour. The detector gave the stripped change a score of 0.556 and asked whether removing the specialised error was intended. The author clarified that non-disjoint cycles need to be applied left to right. This information yielded a summary consistent with the full-context condition."));

  out.push(H2("D", "RQ2: Defects and False Alarms"));
  out.push(P(`The reviewer caught ${word(Math.round(DM.floor * DM.n))} of the ${word(DM.n)} injected defects under both the floor and treatment conditions, and ${word(Math.round(DM.ceiling * DM.n))} under full context. The full-context result is especially noteworthy: even with the issue available, the reviewer accepted ${word(DV.v2_defect_ceiling_missed)} of the ${word(DM.n)} faulty patches. For this model, knowing the intended behaviour was not sufficient to have the code reviewed properly. Its ability to detect defects was a major limitation.`));
  out.push(P("One mutant was caught without the issue information but approved with it. This was an isolated occurrence, but it is consistent with stated intent sometimes leading a reviewer to accept a change without fully considering its correctness."));
  out.push(P(`The false alarm rate on correct patches was low under all three conditions, with ${fr(FA.floor, FA.n)} false alarms in the floor reviews, ${fr(FA.treatment, FA.n)} in the treatment reviews and ${fr(FA.ceiling, FA.n)} in the ceiling reviews. The experiment thus fails to demonstrate that clarification decreased false alarms.`));

  out.push(H2("E", "RQ3: Detectors"));
  out.push(P("The labels in this analysis were constructed so that a context with intent removed was ambiguous and its full-context counterpart was clear. Table II and Fig. 5 compare the behaviour of the detectors on these labels. This configuration favours detectors that respond to missing issue information, so the recall figures should be read with the construction of the labels in mind."));
  const dn = ["heuristic", "sampling", "perturbation"].filter(n => det[n]);
  out.push(...table(["Detector", "n", "Ask", "Prec.", "Rec.", "Score s / f"],
    dn.map(n => [n[0].toUpperCase() + n.slice(1), String(det[n].n_decisions), pct(det[n].ask_rate), f2(det[n].precision), f2(det[n].recall),
      `${f2(det[n].mean_score_stripped)} / ${f2(det[n].mean_score_full)}`]),
    [1080, 380, 520, 520, 480, 1060], "Detector performance on constructed labels"));
  out.push(...figure("fig9_detectors.png", "Mean detector scores with intent withheld and with full context. Dashed lines represent the default thresholds."));
  if (det.sampling && det.perturbation) {
    out.push(P(`The heuristic detector did not request clarification on any full-context instance, but found only ${pct(det.heuristic.recall)} of the stripped instances. This low recall helps explain why there were limited opportunities for clarification to help the reviewer.`));
    out.push(P(`The two uncertainty-based detectors needed eight model calls per decision and were tested on ${word(det.sampling.n_decisions / 2)} instances each. At their default thresholds, both asked on every decision. Sampling-based uncertainty differentiated the two contexts, with a mean score of ${f2(det.sampling.mean_score_stripped)} for the stripped context and ${f2(det.sampling.mean_score_full)} for the full context. Re-examining the recorded scores indicates that a threshold of around 0.60 would separate them. We treat this as a diagnostic observation and do not adopt the threshold, because it was derived from scores in the study set. Prompt perturbation showed no difference between conditions, with a mean score of ${f2(det.perturbation.mean_score_stripped)} in both.`));
    out.push(P("The results reveal a balance between asking often and knowing when a question is necessary. The heuristic was too conservative and missed many ambiguous changes, while the uncertainty-based detectors asked too often at their default thresholds."));
  }

  // ---- V-F: the same ablation on a local reviewer. Never pooled with v2.
  const F3 = V3.funnel, IG3 = T3.intent_golden, IM3 = T3.intent_mutant;
  out.push(H2("F", "Replication on a Local Reviewer"));
  out.push(P(`Table III shows the results of the replication with the local reviewer, ${S3.reviewer_model_name}, served through Ollama. The results were judged by the Claude agent judge, ${V3.judge_label}. As discussed in Section V-G, this judge was chosen after examining its agreement with the local judge. The replication is not pooled with the original experiment but is reported separately.`));
  const row3 = (label, t) => [label, fr(t.floor, t.n), fr(t.treatment, t.n), fr(t.ceiling, t.n), f2(t.mcnemar_p)];
  out.push(...table(["Measure", "Floor", "Treat.", "Ceiling", "p"], [
    row3("Intent, all", IA3), row3("Intent, golden", IG3), row3("Intent, mutant", IM3),
    row3("Defect caught", DM3), row3("False alarm", FA3)],
    [1500, 760, 760, 760, 560], "Judged outcomes for the local replication (v3)"));
  out.push(...figure("fig15_v3_results.png", "Results by condition in the local replication. Counts indicate instances; the figure reports gap recovery, its 95% interval and the McNemar p-value."));
  out.push(P(`Clarification produced no significant improvement in intent recovery in the replication. Across ${IA3.n} instances, recovery went up from ${pct(IA3.floor)} to ${pct(IA3.treatment)} with clarification; with full context, it was ${pct(IA3.ceiling)}. Gap recovery was ${f2(IA3.gap_recovery)} (95% interval: ${ci(IA3.gap_ci)}; McNemar's p = ${f2(IA3.mcnemar_p)}). The interval contains zero, so no positive effect is established. Its upper bound also rules out recovering more than about one-third of the gap.`));
  out.push(P(`Withholding intent cost ${Math.round((IA3.ceiling - IA3.floor) * 100)} percentage points of recovery, and clarification restored ${word(Math.round((IA3.treatment - IA3.floor) * 100))} of them. The results were also inconclusive for the separate subsets: gap recovery was ${f2(IG3.gap_recovery)} (p = ${f2(IG3.mcnemar_p)}) for golden instances and ${f2(IM3.gap_recovery)} (p = ${f2(IM3.mcnemar_p)}) for mutant instances.`));
  out.push(P(`As in the original study, detector recall was one of the limitations. The detector asked questions in ${V3.treatment_asks} of the ${V3.treatment_n} treatment reviews. Of the ${F3.floor_misses} changes whose intent the reviewer missed without clarification, it asked about ${word(F3.detector_asked)} and missed ${DV.v3_detector_missed}. The simulated author answered ${word(F3.author_answered)} of these ${word(F3.detector_asked)} questions, and the treatment recovered intent in ${word(F3.treatment_recovered)} of the ${F3.floor_misses} initially misinterpreted changes.`));
  out.push(P(`Not all of the impact was positive. Clarification helped on ${IA3.discordant_treatment_better} instances and hurt on ${word(IA3.discordant_floor_better)}. Of the ${word(F3.author_answered)} cases where the simulated author answered a question about a change the floor had misinterpreted, the treatment recovered intent in ${word(F3.treatment_recovered)}. The findings indicate that the primary obstacle is not just getting an answer, but knowing when a question is worth asking. Detector recall is one of the main limitations.`));
  out.push(P(`Defect detection was still low even with full context. The reviewer detected ${word(Math.round(DM3.floor * DM3.n))} of ${DM3.n} injected defects without clarification (${pct(DM3.floor)}), ${word(Math.round(DM3.treatment * DM3.n))} with clarification (${pct(DM3.treatment)}), and ${word(Math.round(DM3.ceiling * DM3.n))} with full context (${pct(DM3.ceiling)}). The difference was not significant (McNemar's p = ${f2(DM3.mcnemar_p)}). As in the original experiment, the local reviewer's limited ability to recognise defects remained a constraint.`));
  const fa3 = x => { const k = Math.round(x * FA3.n); return k === 1 ? "once" : `${word(k)} times`; };
  out.push(P(`Of the ${FA3.n} golden instances, false alarms occurred ${fa3(FA3.floor)} without clarification, ${fa3(FA3.treatment)} with clarification, and ${fa3(FA3.ceiling)} with full context. These differences were also not significant (p = ${f2(FA3.mcnemar_p)}). The replication does not demonstrate that clarification benefits defect detection or reduces false alarms.`));

  // ---- V-G: agreement between AI judges. AI-vs-AI; not validation against humans.
  out.push(H2("G", "Judge Calibration"));
  out.push(P(`The three AI judges were the API judge ${J.models.api_v2}, the Claude Sonnet agent (${V3.judge_label}), and ${J.models.gemini_web.replace(/ \(web app\)$/, "")} through the web application. The API judge and the agent each judged all ${J.v2_pairs.api_vs_agent.intent_recovered.n} original reviews, while the web-application judge judged a stratified sample of ${J.gemini_sample.n} runs selected across conditions and patch variants. Table IV gives the agreement between each pair of judges as a percentage, Cohen's kappa, and sample size.`));
  out.push(P("These measurements refer to agreement between AI judges. None of them is a sign of agreement with human reviewers, which is assessed separately."));
  const cell = c => `${pct(c.percent_agreement)} / ${kap(c.kappa)} / ${c.n}`;
  const jrow = (label, pr) => [label, cell(pr.intent_recovered), cell(pr.defect_caught), cell(pr.false_alarm)];
  out.push(...table(["Judge pair", "Intent", "Defect", "False alarm"], [
    jrow(`V2: ${J.models.api_v2} vs. agent`, J.v2_pairs.api_vs_agent),
    jrow("V2: Gemini web vs. agent", J.v2_pairs.gemini_vs_agent),
    jrow(`V2: Gemini web vs. ${J.models.api_v2}`, J.v2_pairs.gemini_vs_api),
    jrow(`V3: ${J.models.api_v3} vs. agent`, J.v3_pairs.llama_vs_agent)],
    [1500, 760, 760, 760], "Agreement between AI judges (% agreement / Cohen's kappa / n)"));
  out.push(...figure("fig16_judges.png", "Pairwise Cohen's kappa between AI judges. These values compare AI judges only, not human judges."));
  const pAA = J.v2_pairs.api_vs_agent, pGA = J.v2_pairs.gemini_vs_agent, pLA = J.v3_pairs.llama_vs_agent;
  const VA = V2A.tests.intent_all, LJ = N.v3_local_llama_judge.tests.intent_all, ND = N.v3_local_llama_judge.no_defect_claim_mutant;
  out.push(P(`The API judge showed high agreement with the agent judge on defect detection (κ = ${kap(pAA.defect_caught.kappa)}, n = ${pAA.defect_caught.n}, ${pct(pAA.defect_caught.percent_agreement)} agreement) and false alarms (κ = ${kap(pAA.false_alarm.kappa)}). There was less agreement on intent recovery (κ = ${kap(pAA.intent_recovered.kappa)}, ${pct(pAA.intent_recovered.percent_agreement)} agreement). For intent recovery, the Gemini web judge reached κ = ${kap(pGA.intent_recovered.kappa)} against the agent judge, and all three judges agreed on intent recovery in ${J.v2_three_way_intent.all_agree} of the ${J.v2_three_way_intent.n} sampled runs.`));
  out.push(P(`When the original study was rescored with the agent judge, intent was recovered at ${pct(VA.floor)}, ${pct(VA.treatment)} and ${pct(VA.ceiling)} in the floor, treatment and ceiling conditions respectively. Gap recovery increased to ${f2(VA.gap_recovery)} (95% interval: ${ci(VA.gap_ci)}; McNemar's p = ${f2(VA.mcnemar_p)}). The conclusion was the same: there was no statistical significance. The estimated magnitude, however, differed from the API judge's result (${f2(IA.gap_recovery)}, 95% interval: ${ci(IA.gap_ci)}). These comparisons reflect agreement among the AI judges and are not a statement of agreement with human evaluations.`));
  out.push(P(`The local judge, ${J.models.api_v3}, performed poorly in the replication. Its agreement with the agent judge was ${pct(pLA.intent_recovered.percent_agreement)} for intent recovery (κ = ${kap(pLA.intent_recovered.kappa)}, n = ${pLA.intent_recovered.n}), ${pct(pLA.defect_caught.percent_agreement)} for defect detection (κ = ${kap(pLA.defect_caught.kappa)}), and ${pct(pLA.false_alarm.percent_agreement)} for false alarms (κ = ${kap(pLA.false_alarm.kappa)}). Although the percentage agreement was high for false alarms, the kappa value shows that this agreement was no better than expected from the marginal distributions. The local judge never marked a false alarm and claimed that no defect had been injected in ${ND.k} of the ${ND.n} mutant rows (${pct(ND.k / ND.n)}).`));
  out.push(P(`We therefore used ${V3.judge_label} as the primary judge for the replication. The decision was taken post hoc, after looking at the agreement results. For reference, the local judge's own estimate of gap recovery is ${f2(LJ.gap_recovery)} (95% interval: ${ci(LJ.gap_ci)}), with floor, treatment and ceiling recovery rates of ${pct(LJ.floor)}, ${pct(LJ.treatment)} and ${pct(LJ.ceiling)} respectively. These comparisons are still AI-to-AI. Only the API judge from the original study was checked against human scorers; the judges used for the replication were not.`));

  // ---- V-H: the full v3 rows on the original (v2) reviewer, question, oracle and judge models.
  if (G3) {
    const t = G3.tests, ia = t.intent_all, dd = G3.discordant, fu = G3.funnel, fg = t.false_alarm_golden;
    out.push(H2("H", "Replication Set on the Original Reviewer"));
    out.push(P(`The results of Sections V-B and V-F differ both in the instances tested and in the reviewer model used. To investigate the impact of the reviewer model on its own, we ran all ${D3.rows} replication instances through the original reviewer, ${G3.review_models.join(", ")}, with the original question, author and judge models (${G3.judge_model}).`));
    out.push(P(`Three conditions were completed for ${G3.complete_triples} instances. In the other ${word(D3.rows - G3.complete_triples)} cases, the question model returned a server error on every attempt.`));
    out.push(...table(["Measure", "Floor", "Treat.", "Ceiling", "p"], [
      row3("Intent, all", ia), row3("Intent, golden", t.intent_golden), row3("Intent, mutant", t.intent_mutant),
      row3("Defect caught", t.defect_mutant), row3("False alarm", fg)],
      [1500, 760, 760, 760, 560], "Judged outcomes for the replication set on the original reviewer"));
    out.push(P(`Intent recovery was ${pct(ia.floor)} with intent withheld, ${pct(ia.treatment)} with clarification, and ${pct(ia.ceiling)} with full context. Gap recovery was ${f2(ia.gap_recovery)} (95% interval: ${ci(ia.gap_ci)}; McNemar's p = ${f2(ia.mcnemar_p)}). The interval excludes zero, but the paired test does not reach the conventional cut-off for statistical significance. The instance-level trace also casts doubt on attributing the observed difference to clarification.`));
    out.push(P(`The detector asked questions on ${G3.treatment_asks} of ${G3.treatment_n} instances, and the simulated author gave a substantive answer in only ${word(fu.answered_total)} of them. Of the ${fu.floor_misses} instances misinterpreted at the floor, the detector asked about ${word(fu.detector_asked)} and recovered intent in ${fu.treatment_recovered === 0 ? "none" : word(fu.treatment_recovered)}. ${cap(word(dd.not_asked))} of the ${word(dd.total)} discordant floor-treatment pairs came from cases where no question was posed. In those cases the reviewer received the same input in both conditions, yet the results differed, ${word(dd.not_asked_treatment_better)} times in one direction and ${word(dd.not_asked_floor_better)} in the other. This pattern suggests run-to-run variation in the reviewer, not an effect of clarification.`));
    out.push(P(`Clarification also increased false alarms on golden patches, from ${word(Math.round(fg.floor * fg.n))} of ${fg.n} at the floor to ${word(Math.round(fg.treatment * fg.n))} of ${fg.n} in the treatment. Together, these results indicate that a single review per condition is not enough to distinguish the effects of clarification from changes in model outputs. Multiple evaluations per condition, or a deterministic reviewer, would give a stronger basis for attribution.`));
  }
  return out;
}

const discussion = [
  H("VI", "Discussion"),
  P("The addition of a clarification step is easy. Using it effectively is more challenging, because it requires deciding when to use it. When a question reached an author who could supply the missing information, clarification sometimes helped the reviewer recover the intended behaviour. Most opportunities for improvement were missed earlier, because the detector did not identify a change that the reviewer would misinterpret. This moves the central problem from generating good questions to knowing when a question is appropriate, without causing unnecessary interruptions."),
  P("The detector results demonstrate this trade-off. The heuristic detector was conservative, with high precision and low recall. Sampling-based uncertainty distinguished the stripped and full-context conditions in the small evaluation, but its threshold must be calibrated on held-out data. In the tested configuration, prompt perturbation could not distinguish between the two conditions. These results do not prove that any detector is ready for general use."),
  P("Another drawback of golden patches is that it is difficult to study ambiguity in them. Well-written changes often document their intent in the comments, docstrings and code they add. If only the linked issue is deleted, a lot of information remains available to the reviewer. Even after discarding all natural-language statements of intent, many changes were still understandable from the code. Benchmarks with changes whose behaviour is truly under-specified would be useful in future evaluations."),
  P("The ability of the underlying reviewer is also a limitation on clarification. Defects were still difficult to detect when all context was available, both in the original experiment and in the local replication. A reviewer that cannot accurately identify a defect is unlikely to gain much from learning what the author was trying to achieve. A stronger reviewer may be necessary before the impact of clarification on defect detection can be measured."),
  P(`The qualitative results were comparable across both reviewers and judge setups: opportunities for clarification were limited by detector recall, defect detection was limited by the reviewer, and the experiments failed to yield a statistically significant improvement in intent recovery. The estimated effect size still depends on the judge, however. In the original study, gap recovery was ${f2(IA.gap_recovery)} with the API judge (95% interval: ${ci(IA.gap_ci)}) and ${f2(V2A.tests.intent_all.gap_recovery)} with the agent judge (95% interval: ${ci(V2A.tests.intent_all.gap_ci)}). In the ${IA3.n}-instance replication, gap recovery was ${f2(IA3.gap_recovery)} (95% interval: ${ci(IA3.gap_ci)}) with the agent judge. The evidence therefore does not support a reliable positive effect across these evaluations, and the estimates should be read together with the judge and reviewer that generated them.`),
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
  out.push(P(`The original study only has ${v2.complete_triples} instances because of a per-model daily cap, which leads to large confidence intervals.` + (HJ ? ` A stratified sample of ${(I || Dc || Fa).n} of the judge's reviews was used to compare the judge with ${word(HJ.n_scorers)} independent human scorers. The reviews were shown without the judge's answers or the experimental condition, and blank responses were excluded rather than counted as disagreements.` : "")));
  if (HJ && I && Dc && Fa) {
    out.push(P(`For defect detection and false alarms, Cohen's κ ${cite("cohen")} was ${f2(Dc.kappa_mean)} and ${f2(Fa.kappa_mean)}, with ${pct(Dc.percent_agreement_mean)} and ${pct(Fa.percent_agreement_mean)} observed agreement respectively. For intent recovery, observed agreement was ${pct(I.percent_agreement_mean)} and κ was ${f2(I.kappa_mean)}. The humans judged intent recovered in ${pct(I.human_yes_rate)} of reviews, compared with ${pct(I.judge_yes_rate)} for the judge. This very skewed distribution of judgements likely explains the near-zero kappa, and does not necessarily imply that the observed agreement was random. Because the judge was stricter on intent recovery, the reported rates are likely to be on the conservative side under this evaluation.`));
  }
  out.push(P("The simulated author was limited to the withheld issue text and commit messages. However, potential leakage of information remains, and a manual audit, assisted by the evaluation tooling, is still needed. We also report a protocol deviation in the first v2 run. The model used up the simulated author's token budget in its reasoning and had no tokens left to answer. Its prompt also refused questions phrased in terms of code it could not see. Both were fixed and the treatment was rerun for the six affected instances. The floor and ceiling conditions were not rerun. The prompt was changed after the refusals were observed, so this change could have affected the treatment results; the revised prompt and each exchange are documented in the study log."));
  out.push(P("All verified mutants came from SymPy, and the mutation operators introduced simple defects. The conclusions may therefore not extend to more complicated defects or to changes in other repositories. Lastly, the original reviewer is a fairly small model. Stronger models may interpret intent and identify defects differently, so the results should not be assumed to apply to every LLM-based code review tool."));
  out.push(P(`The replication adds further restrictions. Both studies are small (${v2.complete_triples} and ${IA3.n} instances) and have rather large intervals. The agent judge was chosen after a review of its agreement with the local judge, which is a post hoc choice. The question and oracle models are also small, and their identities are noted only in the oracle log, not for each database row. The studies differ in instances, reviewer models and judges, so their results are not pooled. Additionally, a single review per condition cannot separate the effect of clarification from the reviewer's run-to-run variation.`));
  out.push(P(`${cap(word(LD.n_prs))} constructed pull requests were demonstrated live on GitHub in the authors' sandbox repository, run from a laptop through a tunnel. This shows that the interaction flow is functional but gives no idea of effectiveness. The system has not been tested on real third-party pull requests, and the ${RP.n_prs} real pull requests collected so far have not been labelled.`));
  if (HL) {
    out.push(P([R("Human labelling. ", { bold: true }),
      R(`Two annotators independently labelled ${HL.n} pull requests as clear or unclear, using just the code change. Cohen's κ ${cite("cohen")} was ${f2(HL.kappa)}, with ${pct(HL.observed_agreement)} observed agreement. The ${word(HL.n_disagree)} disagreements were adjudicated by an AI model, ${HL.adjudicated_by.replace(/ \((.*), AI\)$/, " ($1)")}, applying the same codebook, at the authors' request. These ${word(HL.n_adjudicated_by_ai)} labels are therefore not purely human judgements.` + (HT ? ` Detector thresholds were set on a development split of the labelled data, which contained only ${word(HT.n_ambiguous)} ambiguous cases altogether, before any threshold-dependent evaluation. The default thresholds were used in Study A.` : ""))]));
  }
  if (HB) out.push(...humanParas().slice(HL ? 1 : 0));
  return out;
})();

const conclusion = [
  H("VIII", "Conclusion"),
  P("In ClarifyReview, code review feedback is preceded by a decision: if the intention of a change is not clear from the available information, the system can ask the author for clarification. To assess this method, every natural-language statement of intent had to be removed, as golden patches frequently communicate their intent through the text they add."),
  P(`Under this manipulation, ${f2(IA.gap_recovery)} of the intent gap was recovered across ${v2.complete_triples} instances. This result was in the expected direction but not statistically significant. Instance-level analysis revealed that intent could be recovered through clarification when the detector identified an opportunity to ask, but this was limited by the detector's low recall.`),
  P(`In the replication with a local reviewer, gap recovery was ${f2(IA3.gap_recovery)} (95% interval: ${ci(IA3.gap_ci)}; McNemar's p = ${f2(IA3.mcnemar_p)}), which was not statistically significant. The upper bound rules out a recovery of more than about one-third of the gap. The estimated effect also differed between the judges who assessed the reviews, which leaves the size of the effect uncertain.`),
  P(`Future work will involve labelling the ${RP.n_prs} real pull requests already collected, a paired developer study of usefulness and trust, hosting the bot permanently, and scaling its evaluation to real third-party pull requests. In addition, further experiments should repeat the review for each condition to separate the effects of clarification from run-to-run variation, and use a stronger reviewer to check whether clarification can improve defect detection.`),
];

const ack = [
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 120, after: 60 },
    children: [R("Acknowledgment", { sc: true })] }),
  P("The authors are thankful to the School of Computer Science and Engineering, Vellore Institute of Technology, for supporting this work."),
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
  title: "ClarifyReview: Ambiguity-Aware Intent Clarification for LLM-Based Pull Request Code Review",
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
