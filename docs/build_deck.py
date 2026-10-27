"""Fill the SCOPE Review 3 template with the ClarifyReview presentation.

Template slides are edited in place so they keep their layouts, fonts, footer
and slide numbers; extra slides (a second literature slide, a second results
slide and a demonstration slide) are copies of template slides. Text and
numbers come from report_content.py, so the deck and the report agree.

    python docs/build_deck.py --template "<Review 3 template.pptx>" \\
        --out ~/Downloads/ClarifyReview_Review3/ClarifyReview_Review3.pptx [--no-pdf]
"""

from __future__ import annotations

import argparse
import copy
import subprocess
import sys
from pathlib import Path

import pptx
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

sys.path.insert(0, str(Path(__file__).resolve().parent))
import report_content as C  # noqa: E402

FONT = "Times New Roman"
NAVY = RGBColor(0x1F, 0x38, 0x64)
HEADER = RGBColor(0x4F, 0x81, 0xBD)
BAND1, BAND2 = RGBColor(0xD0, 0xD8, 0xE8), RGBColor(0xE9, 0xED, 0xF4)
RED = RGBColor(0xC0, 0x00, 0x00)
IA, DM, FA, F = C.IA, C.DM, C.FA, C.F
prose, numword, fixed = C.prose, C.numword, C.fixed   # prose(): docs/prose_v3.json
V3, J, DV, RP, DET = C.V3, C.J, C.DV, C.RP, C.DET


# ---------------------------------------------------------------- helpers

def no_highlight(run) -> None:
    rpr = run._r.find(qn("a:rPr"))
    if rpr is not None:
        for h in rpr.findall(qn("a:highlight")):
            rpr.remove(h)


def style(run, size=None, bold=None, color=None, italic=None) -> None:
    run.font.name = FONT
    if size:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if italic is not None:
        run.font.italic = italic
    if color is not None:
        run.font.color.rgb = color
    no_highlight(run)


def shape(slide, name: str):
    return next(s for s in slide.shapes if s.name == name)


def content(slide):
    return next(s for s in slide.shapes if s.is_placeholder
                and s.placeholder_format.type in (7, 2) and s.has_text_frame)


def bullets(sh, items, size=18, gap=6) -> None:
    """Fill a placeholder with bullets; an item may be (bold lead, text)."""
    tf = sh.text_frame
    tf.word_wrap = True
    paras = list(tf.paragraphs)
    proto = copy.deepcopy(paras[0]._p)
    for p in paras:
        tf._txBody.remove(p._p)
    for item in items:
        el = copy.deepcopy(proto)
        for r in el.findall(qn("a:r")) + el.findall(qn("a:br")) + el.findall(qn("a:fld")):
            el.remove(r)
        tf._txBody.append(el)
        para = tf.paragraphs[-1]
        para.space_after = Pt(gap)
        para.line_spacing = 1.0
        level = 0
        if isinstance(item, tuple) and len(item) == 3:
            level, *item = item
            item = tuple(item)
        para.level = level
        lead, text = item if isinstance(item, tuple) else ("", item)
        if lead:
            style(para.add_run(), size - 2 * level, True)
            para.runs[-1].text = lead
        r = para.add_run()
        r.text = text
        style(r, size - 2 * level, False)


def resize(sh, left=None, top=None, width=None, height=None) -> None:
    """Move or resize a shape, writing all four values.

    A placeholder that inherits its position from the layout has no geometry
    of its own; setting only `top` would write a zero width and hide the text.
    """
    cur = (sh.left, sh.top, sh.width, sh.height)
    new = [cur[i] if v is None else v for i, v in enumerate((left, top, width, height))]
    sh.left, sh.top, sh.width, sh.height = (Emu(int(v)) for v in new)


def picture(slide, file: str, left, top, max_w, max_h):
    from PIL import Image

    with Image.open(C.FIG / file) as im:
        w, h = im.size
    scale = min(max_w / w, max_h / h)
    pw, ph = int(w * scale), int(h * scale)
    return slide.shapes.add_picture(str(C.FIG / file), Emu(left + (max_w - pw) // 2),
                                    Emu(top), Emu(pw), Emu(ph))


def textbox(slide, left, top, width, height, lines, size=14, align=PP_ALIGN.LEFT,
            color=None, bold_first=False):
    tb = slide.shapes.add_textbox(Emu(left), Emu(top), Emu(width), Emu(height))
    tf = tb.text_frame
    tf.word_wrap = True
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        lead, text = line if isinstance(line, tuple) else ("", line)
        if lead:
            r = p.add_run()
            r.text = lead
            style(r, size, True, color)
        r = p.add_run()
        r.text = text
        style(r, size, bold_first and i == 0, color)
    return tb


def table(slide, left, top, width, header, rows, col_w, size=11, row_h=None, header_h=None):
    nrows, ncols = len(rows) + 1, len(header)
    gf = slide.shapes.add_table(nrows, ncols, Emu(left), Emu(top), Emu(width),
                                Emu((row_h or 320000) * nrows))
    t = gf.table
    if header_h:
        t.rows[0].height = Emu(header_h)
        for r in list(t.rows)[1:]:
            r.height = Emu(row_h)
    total = sum(col_w)
    for i, w in enumerate(col_w):
        t.columns[i].width = Emu(int(width * w / total))
    for r_i, values in enumerate([header] + rows):
        for c_i, v in enumerate(values):
            cell = t.cell(r_i, c_i)
            cell.fill.solid()
            cell.fill.fore_color.rgb = HEADER if r_i == 0 else (BAND1 if r_i % 2 else BAND2)
            cell.margin_left = cell.margin_right = Emu(50000)
            cell.margin_top = cell.margin_bottom = Emu(25000)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            tf = cell.text_frame
            tf.word_wrap = True
            tf.paragraphs[0].text = ""
            r = tf.paragraphs[0].add_run()
            r.text = str(v)
            style(r, size + (1 if r_i == 0 else 0), r_i == 0,
                  RGBColor(0xFF, 0xFF, 0xFF) if r_i == 0 else RGBColor(0, 0, 0))
    return gf


def outline(slide, left, top, width, height, color=RED, weight=2.5):
    from pptx.enum.shapes import MSO_SHAPE
    s = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(left), Emu(top), Emu(width),
                               Emu(height))
    s.fill.background()
    s.line.color.rgb = color
    s.line.width = Pt(weight)
    s.shadow.inherit = False
    return s


def duplicate(pres, src_index: int, insert_at: int):
    src = pres.slides[src_index]
    new = pres.slides.add_slide(src.slide_layout)
    for sh in list(new.shapes):
        sh._element.getparent().remove(sh._element)
    # Pictures refer to their image by relationship id, which is per slide, so
    # each one is re-related on the new slide and the reference rewritten.
    remap = {}
    for rid, rel in src.part.rels.items():
        if "image" in rel.reltype:
            remap[rid] = new.part.relate_to(rel._target, rel.reltype)
    for sh in src.shapes:
        el = copy.deepcopy(sh._element)
        for blip in el.iter(qn("a:blip")):
            old = blip.get(qn("r:embed"))
            if old in remap:
                blip.set(qn("r:embed"), remap[old])
        new.shapes._spTree.append(el)
    ids = pres.slides._sldIdLst
    el = ids[-1]
    ids.remove(el)
    ids.insert(insert_at, el)
    return new


def set_title(slide, text: str) -> None:
    t = next(s for s in slide.shapes if s.is_placeholder
             and s.placeholder_format.type in (1, 3))
    p = t.text_frame.paragraphs[0]
    for r in p.runs[1:]:
        r._r.getparent().remove(r._r)
    p.runs[0].text = text


def remove_shape(sh) -> None:
    sh._element.getparent().remove(sh._element)


# ------------------------------------------------------------------ slides

def build(template: Path, out: Path) -> None:
    pres = pptx.Presentation(template)
    S = pres.slides
    W = pres.slide_width

    # Extra slides first, so indices below refer to the final order.
    duplicate(pres, 4, 5)            # Literature Review (2/2)
    # Slides now: 0 title,1 mail,2 aim,3 abstract,4 lit1,5 lit2,6 gap,7 obj,8 arch,
    # 9 FR,10 modules,11 results,12 conclusion,13 outcome,14 refs
    duplicate(pres, 11, 12)          # Results (2/2)
    duplicate(pres, 11, 13)          # Project Demonstration
    duplicate(pres, 11, 13)          # Results (3/3): local replication, ahead of the demo
    S = pres.slides
    title_s, mail, aim, abstract, lit1, lit2, gap, obj, arch, fr, mods, res1, res2, res3, \
        demo, concl, outcome, refs = list(S)

    # 1. Title -----------------------------------------------------------
    t = shape(title_s, "Title 6")
    runs = t.text_frame.paragraphs[0].runs
    for r in runs:
        r.text = ""
        no_highlight(r)
    runs[0].text = "B.Tech. BCSE497J – Project I"
    style(runs[0], 20, True)
    runs[-1].text = C.TITLE_CASE
    style(runs[-1], 26, True)
    resize(t, top=1834141, height=1300000)
    box = shape(title_s, "object 3")
    paras = box.text_frame.paragraphs
    for para, (reg, name) in zip((paras[2], paras[3]), C.STUDENTS):
        rs = para.runs
        rs[0].text = f"{name.title()}\t({reg})"
        pPr = para._p.get_or_add_pPr()
        for old in pPr.findall(qn("a:tabLst")):
            pPr.remove(old)
        tabs = pPr.makeelement(qn("a:tabLst"), {})
        tabs.append(tabs.makeelement(qn("a:tab"), {"pos": "3200000", "algn": "l"}))
        pPr.append(tabs)
        for r in rs[1:]:
            r.text = ""
    rs = paras[6].runs
    rs[0].text = f"{C.GUIDE}, {C.DESIGNATION}, SCOPE"
    for r in rs[1:]:
        r.text = ""

    # 2. Approval mail: left exactly as the template has it; the guide's mail
    # screenshot is pasted in by the team.

    # 3. Aim -----------------------------------------------------------------
    bullets(content(aim), [
        "To build and evaluate ClarifyReview, an LLM-based pull request reviewer that decides "
        "before critiquing whether it understands what a change is for - and asks the author "
        "one targeted question when it does not.",
        "To measure, on SWE-bench Verified with execution-verified defects, whether asking "
        "first changes what the reviewer understands and detects, compared with single-pass "
        "review of the same change.",
    ], size=22, gap=14)

    # 4. Abstract --------------------------------------------------------
    bullets(content(abstract), [
        ("Problem. ", "CodeRabbit, Qodo, Greptile review in a single pass: they guess the "
                      "author's intent and comment on the guess - false alarms on deliberate "
                      "changes, missed defects on unintended ones."),
        ("System. ", "A four-stage pipeline - ingest, decide, ask, review - with four "
                     "interchangeable ambiguity detectors; the baseline is the same pipeline "
                     "with a detector that never asks. GitHub bot + benchmark harness, "
                     f"{C.N_TESTS} tests."),
        ("Study. ", f"2 x 3 ablation on SWE-bench Verified: {C.MUT['by_status']['verified']} "
                    "execution-verified mutants; intent withheld (floor), withheld + "
                    "clarification (treatment), full context (ceiling)."),
        ("Result. ", f"Intent recovered {C.pct(IA['floor'])} → {C.pct(IA['treatment'])} → "
                     f"{C.pct(IA['ceiling'])}; gap recovery {IA['gap_recovery']:.2f} (p = "
                     f"{IA['mcnemar_p']:.2f}). Clarification worked where it got the chance; "
                     "the limit is the detector's recall. " + prose("deck.abstract.v3")),
    ], size=18, gap=10)

    # 5-6. Literature review -------------------------------------------
    for slide, rows, part in ((lit1, C.LITERATURE[:4], "1/2"), (lit2, C.LITERATURE[4:], "2/2")):
        set_title(slide, f"Literature Review ({part})")
        for sh in list(slide.shapes):
            if sh.shape_type == 13 or (sh.is_placeholder and sh.placeholder_format.idx == 1):
                remove_shape(sh)
        table(slide, 560000, 1330000, W - 1120000,
              ["Paper", "Objective", "Methodology", "Pros / Cons", "Findings"],
              [list(r) for r in rows], [1.3, 1.4, 1.6, 1.6, 1.5], size=12, row_h=1000000,
              header_h=420000)

    # 7. Research gap ----------------------------------------------------
    bullets(content(gap), [
        ("Clarification is proven - for generation. ", "ClarifyGPT and TiCoder show asking "
         "first improves generated code; no work applies it to reviewing an existing change."),
        ("Review tools never ask. ", "Every deployed reviewer is single-pass; none treats "
         "ambiguous intent as something to resolve before commenting."),
        ("The stakes differ. ", "A wrong guess in generation costs a compiler cycle; in review "
         "it costs a human's attention and the tool's credibility."),
        ("Evaluation is weak. ", "Lexical overlap and fixed/won't-fix labels are poor ground "
         "truth; execution-verified defects are needed."),
        ("Research question. ", "Does asking before reviewing improve intent recovery and "
         "defect detection over single-pass review of the same change?"),
    ], size=17, gap=8)

    # 8. Objectives + SDG / TRL / outcome ---------------------------------
    ob = content(obj)
    resize(ob, top=1300000, height=3050000)
    bullets(ob, [
        ("O1 ", "Design and compare ambiguity detectors (heuristic, classifier, sampling, "
                "perturbation)"),
        ("O2 ", "Build a four-stage clarify-then-review pipeline deployable as a GitHub bot"),
        ("O3 ", "Construct a SWE-bench Verified set with execution-verified defects"),
        ("O4 ", "Run a 2 x 3 ablation and report the gap clarification recovers"),
        ("O5 ", "Prepare a paired blind developer study of usefulness and trust"),
        ("O6 ", "Deliver a TRL 4 prototype and a Scopus-indexed conference paper"),
    ], size=17, gap=4)
    box = shape(obj, "TextBox 6")
    p0, p1 = box.text_frame.paragraphs[0], box.text_frame.paragraphs[1]
    p0.runs[0].text = "Identified:   Sustainable Development Goals\t|\t\t\t| "
    p0.runs[1].text = "Outcome: "
    p0.runs[2].text = "Conference (Scopus)"
    style(p0.runs[2], 16, True)
    p1.runs[0].text = ""
    sdg, trl = shape(obj, "Picture 7"), shape(obj, "Picture 8")
    sx, sy = sdg.width / 499, sdg.height / 400          # SDG image is 499 x 400 px
    for col in (2, 3):                                    # SDG 8 and SDG 9 tiles
        outline(obj, int(sdg.left + col * 100 * sx), int(sdg.top + 100 * sy),
                int(96 * sx), int(96 * sy))
    tx, ty = trl.width / 468, trl.height / 427           # TRL image is 468 x 427 px
    outline(obj, int(trl.left + 44 * tx), int(trl.top + 247 * ty), int(382 * tx),
            int(34 * ty))
    textbox(obj, trl.left + trl.width + 250000, 4800000, 3900000, 1500000, [
        ("SDG 9 ", "- Industry, Innovation and Infrastructure"),
        ("SDG 8 ", "- Decent Work and Economic Growth"),
        ("TRL 4 ", "- technology validated in lab"),
        ("Outcome ", "- conference paper prepared"),
    ], size=14)

    # 9. Architecture ----------------------------------------------------
    set_title(arch, "Framework / Architecture")
    ab = content(arch)
    resize(ab, top=4500000, height=1700000)
    bullets(ab, [
        ("Stage 2 is the contribution: ", "ask or proceed, with a score, threshold and reason."),
        ("Baseline = same pipeline ", "with a detector that never asks - prompts asserted "
                                      "byte-identical by a test."),
        ("Production vs benchmark ", "differ only in the Responder: GitHub comment, or "
                                     "simulated author."),
    ], size=16, gap=4)
    picture(arch, "fig2_architecture.png", 700000, 1250000, W - 1400000, 3150000)

    # 10. Functional requirements -----------------------------------------
    bullets(content(fr), [
        ("FR1 Ingestion - ", "diff, commits and linked issue via webhook or local diff"),
        ("FR2 Semantic diffing - ", "changed lines resolved to functions, methods, classes"),
        ("FR3 Context assembly - ", "bounded, deterministic, fingerprinted"),
        ("FR4 Ambiguity detection - ", "ask/proceed with score, threshold, reason"),
        ("FR5 Selective questioning - ", "at most two questions, each naming a file/line/symbol"),
        ("FR6 Clarification loop - ", "post, wait, fall back to a flagged review on timeout"),
        ("FR7 Review generation - ", "structured findings with severity, evidence, fix, "
                                     "confidence"),
        ("FR8-FR10 - ", "publish to the PR; log every run; evaluation harness and statistics"),
    ], size=19, gap=6)

    # 11. Modules --------------------------------------------------------
    mb = content(mods)
    remove_shape(mb)
    table(mods, 700000, 1350000, W - 1400000, ["Module", "What it does"], [
        ["Ingestion (ingest/)", "Diff parser, AST / multi-language symbol resolution, "
                                "deterministic context"],
        ["Detection (detect/)", "Heuristic (15 features), classifier, sampling and "
                                "perturbation uncertainty"],
        ["Clarification (clarify/)", "Targeted questions; Responder: GitHub / simulated "
                                     "author / none"],
        ["Review (review/)", "Structured findings, markdown rendering"],
        ["LLM layer (llm/)", "Gemini, Anthropic, Ollama backends; retries, timeouts, quota, "
                             "JSON recovery"],
        ["GitHub bot (gh/), CLI", "Webhook app; ingest, detect, review, replay, serve"],
        ["Benchmark (experiments/)", "Intent stripping, mutation + execution verification, "
                                     "2 x 3 runner, judge, statistics"],
        ["Studies and reporting", "Labelling and agreement tools, blind study page, paper "
                                  "and figure generators"],
    ], [1.3, 3.2], size=14, row_h=480000)

    # 12. Results (1/2) ------------------------------------------------------
    set_title(res1, "Experiments and Results (1/3)")
    rb = content(res1)
    resize(rb, top=4150000, height=2100000)
    bullets(rb, [
        f"{C.V2['complete_triples']} SWE-bench Verified instances x 3 conditions = "
        f"{C.V2['runs_ok']} reviews, all judged; 0 failed runs; US$ 0 on the free tier.",
        f"Withholding all written intent opened a gap: {C.pct(IA['ceiling'])} → "
        f"{C.pct(IA['floor'])}. Clarification closed {IA['gap_recovery']:.2f} of it "
        f"(95% CI {IA['gap_ci'][0]:.2f}-{IA['gap_ci'][1]:.2f}, McNemar p = "
        f"{IA['mcnemar_p']:.2f}) - right direction, not significant at n = {IA['n']}.",
        f"Defects caught: {C.frac(DM['floor'], DM['n'])} / {C.frac(DM['treatment'], DM['n'])} / "
        f"{C.frac(DM['ceiling'], DM['n'])} - even with full context the reviewer approved "
        f"{DV['v2_defect_ceiling_missed']} of {DM['n']} broken patches.",
    ], size=15, gap=4)
    picture(res1, "fig7_results.png", 700000, 1200000, W - 1400000, 2900000)

    # 13. Results (2/2) ------------------------------------------------------
    set_title(res2, "Experiments and Results (2/3)")
    rb = content(res2)
    resize(rb, left=700000, top=4300000, width=W - 1400000, height=2000000)
    bullets(rb, [
        f"Floor missed intent {F['floor_misses']}x → detector asked on {F['detector_asked']} → "
        f"author answered {F['author_answered']} → treatment recovered {F['treatment_recovered']}"
        ": clarification worked where it got the chance.",
        f"The limit is detector recall: the heuristic is perfectly precise "
        f"({fixed(DET['heuristic']['precision'], 2)}) but finds "
        f"{C.pct(DET['heuristic']['recall'])} of ambiguous cases; sampling uncertainty "
        "separates the contexts and needs a higher threshold.",
    ], size=15, gap=4)
    picture(res2, "fig8_funnel.png", 500000, 1250000, (W - 1200000) // 2, 2950000)
    picture(res2, "fig9_detectors.png", 600000 + (W - 1200000) // 2, 1250000,
            (W - 1200000) // 2, 2950000)

    # 13b. Results (3/3): local replication and judge check ------------------
    set_title(res3, "Experiments and Results (3/3): local replication and judge check")
    for r in next(sh for sh in res3.shapes if sh.is_placeholder
                  and sh.placeholder_format.type in (1, 3)).text_frame.paragraphs[0].runs:
        r.font.size = Pt(24)          # the long title must stay on one line
    rb = content(res3)
    resize(rb, left=700000, top=4300000, width=W - 1400000, height=2000000)
    bullets(rb, [
        prose("deck.v3.replication"),
        prose("deck.v3.judges"),
        prose("deck.v3.limits"),
    ], size=15, gap=4)
    picture(res3, "fig15_v3_results.png", 500000, 1250000, (W - 1200000) // 2, 2950000)
    picture(res3, "fig16_judges.png", 600000 + (W - 1200000) // 2, 1250000,
            (W - 1200000) // 2, 2950000)

    # 14. Project demonstration ---------------------------------------------
    set_title(demo, "Project Demonstration")
    remove_shape(content(demo))
    picture(demo, "fig12_demo_detect.png", 450000, 1250000, (W - 1100000) // 2, 3650000)
    picture(demo, "fig13_demo_replay.png", 650000 + (W - 1100000) // 2, 1250000,
            (W - 1100000) // 2, 3650000)
    textbox(demo, 450000, 4950000, W - 900000, 1300000, [
        ("$ ./demo.sh  |  > .\\demo.ps1  ", "- Stage 2 asks (0.889) on an ambiguous PR and proceeds (0.296) on a "
                         "clear one; then sympy-12481 is replayed: the floor misreads it, "
                         "ClarifyReview asks, gets the answer, and matches the full-context "
                         "review."),
        ("Live on GitHub: ", prose("deck.demo.live"))], size=12)

    # 15. Conclusion and future work ----------------------------------------
    bullets(content(concl), [
        ("Built: ", f"four-stage reviewer, four detectors, three LLM backends (Gemini, "
                    f"Anthropic, Ollama), GitHub bot, benchmark harness; {C.N_TESTS} tests; "
                    "TRL 4."),
        ("Found: ", "golden patches document their own intent - the pilot caught this and "
                    "the design was corrected before the main run."),
        ("Found: ", f"clarification recovered {IA['gap_recovery']:.2f} of the intent gap; it "
                    "succeeded where asked, and detector recall is the bottleneck."),
        ("Found: ", "defect detection is limited by the reviewer model, not by missing intent."),
        ("Found: ", prose("deck.conclusion.v3")),
    ] + ([("Found: ", f"on the original reviewer, {C.G3['discordant']['not_asked']} of "
                      f"{C.G3['discordant']['total']} changed outcomes had no question asked: "
                      "reviewer variation is as large as the effect.")] if C.G3.get("discordant") else []) + [
        ("Future work: ", f"label the {RP['n_prs']} collected real PRs; repeat reviews per "
                          "condition; run the developer study; host the bot permanently and run it on third-party PRs; "
                          "scale up with a stronger reviewer."),
    ], size=14 if C.G3.get("discordant") else 15, gap=5)

    # 16. Outcome ------------------------------------------------------------
    ob = next(s for s in outcome.shapes if s.is_placeholder and s.placeholder_format.idx == 1)
    bullets(ob, [
        ("International Conference Paper - ", f"manuscript prepared: \"{C.TITLE_CASE}\" "
         "(IEEE format); to be submitted to a Scopus-indexed conference."),
        ("Others - working prototype (TRL 4): ", "ClarifyReview GitHub bot and CLI, "
         f"benchmark harness, {C.MUT['by_status']['verified']} execution-verified mutants and the "
         "full study log, released "
         "with the code."),
    ], size=18, gap=12)

    # 17. References -----------------------------------------------------------
    rb = next(s for s in refs.shapes if s.is_placeholder and s.placeholder_format.idx == 1)
    resize(rb, top=1300000, height=5000000)
    picks = [0, 1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 14]
    bullets(rb, [f"[{i + 1}] {C.REFERENCES[k]}" for i, k in enumerate(picks)], size=11, gap=2)
    for p in rb.text_frame.paragraphs:
        # a:buNone must follow the spacing elements in a:pPr, or PowerPoint
        # rejects the file.
        pPr = p._p.get_or_add_pPr()
        # bullets() may already have added one; a second a:buNone is invalid, and
        # PowerPoint 2013 refuses the whole file (newer versions repair it silently).
        if pPr.find(qn("a:buNone")) is None:
            bu = pPr.makeelement(qn("a:buNone"), {})
            spacing = [c for c in pPr if c.tag in (qn("a:lnSpc"), qn("a:spcBef"), qn("a:spcAft"))]
            if spacing:
                spacing[-1].addnext(bu)
            else:
                pPr.insert(0, bu)
        pPr.set("marL", "0")
        pPr.set("indent", "0")

    for slide in pres.slides:
        for sh in slide.shapes:
            if sh.is_placeholder and sh.placeholder_format.type == 16 and sh.has_text_frame:
                p = sh.text_frame.paragraphs[0]
                if p.runs:
                    p.runs[0].text = "28/10/26"
                    for r in p.runs[1:]:
                        r.text = ""

    out.parent.mkdir(parents=True, exist_ok=True)
    pres.save(out)


def export_pdf(path: Path) -> Path | None:
    if sys.platform == "win32":
        from office_pdf import export_pdf_windows

        return export_pdf_windows(path)
    pdf = path.with_suffix(".pdf")
    script = f'''
    tell application "Microsoft PowerPoint"
      open POSIX file "{path}"
      delay 3
      set p to active presentation
      save p in POSIX file "{pdf}" as save as PDF
      try
        close p saving no
      end try
    end tell'''
    subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
    return pdf


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-pdf", action="store_true")
    args = ap.parse_args(argv)
    out = Path(args.out).expanduser()
    build(Path(args.template).expanduser(), out)
    print("wrote", out)
    if not args.no_pdf:
        pdf = export_pdf(out)
        if pdf:
            print("wrote", pdf)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
