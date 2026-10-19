"""Apply corrections and v2 results to the delivered documents, in place.

The documents were built by scripts that lived in a temporary directory and are
gone, so this edits the delivered .docx and .pptx files directly. Editing in
place keeps every untouched paragraph, table and figure byte-identical. New
paragraphs are cloned from existing ones of the same kind, so they inherit the
documents' formatting without needing to know their style names.

    python docs/update_deliverables.py --dir ~/Downloads/ClarifyReview_Review2_Deliverables
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

import docx
import pptx
from docx.shared import Pt, RGBColor
from docx.text.paragraph import Paragraph
from docx.text.run import Run

ROOT = Path(__file__).resolve().parents[1]

# The September documents said tests carry intent. They cannot in SWE-bench: the
# benchmark keeps tests in a separate test_patch, so the reviewed diffs held none.
CORRECTIONS = {
    "ClarifyReview_ProjectI_Report.docx": [(
        "since test files, docstrings and error-message strings all carry intent and "
        "all survive the current procedure.",
        "since the comments and docstrings a patch adds carry intent and survive the "
        "current procedure. (Tests are not a factor: SWE-bench keeps them in a separate "
        "test patch, so the reviewed diffs contained none. Error-message strings are "
        "code and must be left in place.)")],
    "ClarifyReview_Run_Report.docx": [(
        "test files, docstrings and error-message strings all carry intent and all "
        "survive the current stripping.",
        "the comments and docstrings a patch adds carry intent and survive the current "
        "stripping. (Tests are not a factor: SWE-bench keeps them in a separate test "
        "patch. Error-message strings are code and are left in place.)")],
    "ClarifyReview_Presentation_Guide.docx": [
        ("because tests, docstrings and error strings all carry intent.",
         "because the comments and docstrings a patch adds carry intent too."),
        ("And strip tests and docstrings as well as the issue text, because those "
         "carry intent too.",
         "And strip the comments and docstrings a patch adds as well as the issue "
         "text, because those carry intent too."),
    ],
    "ClarifyReview_Review2.pptx": [(
        "tests, docstrings and error strings all carry intent.",
        "the comments and docstrings a patch adds carry intent.")],
}


def replace_in_runs(runs, old: str, new: str) -> int:
    n = 0
    for r in runs:
        if old in r.text:
            r.text = r.text.replace(old, new)
            n += 1
    return n


def correct_docx(path: Path, fixes) -> int:
    d = docx.Document(path)
    n = 0
    for old, new in fixes:
        for p in d.paragraphs:
            n += replace_in_runs(p.runs, old, new)
        for t in d.tables:
            for row in t.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        n += replace_in_runs(p.runs, old, new)
    d.save(path)
    return n


def correct_pptx(path: Path, fixes) -> int:
    pres = pptx.Presentation(path)
    n = 0
    for old, new in fixes:
        for slide in pres.slides:
            for sh in slide.shapes:
                if sh.has_text_frame:
                    for p in sh.text_frame.paragraphs:
                        n += replace_in_runs(p.runs, old, new)
    pres.save(path)
    return n


# ------------------------------------------------------------ docx editing

def _set_text(p_el, text: str, bold_prefix: str = "") -> None:
    """Replace a paragraph's runs with `text`, keeping the first run's format.

    A bold lead-in ("Finding.") is written as a second run cloned from the
    first, so it inherits font, size and colour and differs only in weight.
    """
    from docx.oxml.ns import qn

    runs = p_el.findall(qn("w:r"))
    if not runs:
        raise ValueError("template paragraph has no run to inherit formatting from")
    proto = copy.deepcopy(runs[0])
    for r in p_el.findall(qn("w:r")) + p_el.findall(qn("w:hyperlink")):
        p_el.remove(r)

    def add(t: str, bold: bool | None) -> None:
        r = copy.deepcopy(proto)
        for child in list(r):
            if child.tag != qn("w:rPr"):
                r.remove(child)
        rpr = r.find(qn("w:rPr"))
        if rpr is not None:
            for b in rpr.findall(qn("w:b")) + rpr.findall(qn("w:bCs")):
                rpr.remove(b)
        run = Run(r, None)
        run.text = t
        if bold:
            run.bold = True
        p_el.append(r)

    if bold_prefix:
        add(bold_prefix, True)
    add(text, None)


def insert_paragraph_after(anchor_el, template: Paragraph, text: str,
                           bold_prefix: str = ""):
    el = copy.deepcopy(template._p)
    _set_text(el, text, bold_prefix)
    anchor_el.addnext(el)
    return el


def insert_table_after(anchor_el, template_tbl, rows: list[list[str]]):
    """Clone a table, resize its body rows to fit `rows`, and fill it.

    The template must have the same column count. Header formatting comes from
    the template's first row and body formatting from its second.
    """
    from docx.table import Table

    el = copy.deepcopy(template_tbl._tbl)
    anchor_el.addnext(el)
    t = Table(el, template_tbl._parent)
    body_proto = copy.deepcopy(t.rows[1]._tr)
    for r in list(t.rows)[1:]:
        el.remove(r._tr)
    for _ in rows[1:]:
        el.append(copy.deepcopy(body_proto))
    for r_i, values in enumerate(rows):
        for c_i, v in enumerate(values):
            cell = t.rows[r_i].cells[c_i]
            ps = cell.paragraphs
            for extra in ps[1:]:
                extra._p.getparent().remove(extra._p)
            _set_text(ps[0]._p, v)
    return el


def find_para(d, startswith: str) -> Paragraph:
    for p in d.paragraphs:
        if p.text.strip().startswith(startswith):
            return p
    raise KeyError(startswith)


# ------------------------------------------------------------ pptx editing

def duplicate_slide(pres, src_index: int, insert_at: int):
    """Copy slide `src_index` (0-based) to position `insert_at`.

    python-pptx has no slide copy. The shapes are deep-copied onto a new slide
    with the same layout, which carries their geometry and formatting exactly;
    the placeholders the layout adds are removed first so nothing is doubled.
    """
    src = pres.slides[src_index]
    new = pres.slides.add_slide(src.slide_layout)
    for sh in list(new.shapes):
        sh._element.getparent().remove(sh._element)
    for sh in src.shapes:
        new.shapes._spTree.append(copy.deepcopy(sh._element))
    ids = pres.slides._sldIdLst
    el = ids[-1]
    ids.remove(el)
    ids.insert(insert_at, el)
    return new


def set_shape_text(shape, lines: list[str]) -> None:
    """Rewrite a text frame paragraph by paragraph, keeping each one's runs' format.

    Line i takes the format of paragraph i when it exists, otherwise of the
    last paragraph, so a bold heading line followed by plain body lines keeps
    that pattern.
    """
    tf = shape.text_frame
    paras = list(tf.paragraphs)
    protos = [copy.deepcopy(p._p) for p in paras]
    body = tf._txBody
    for p in paras:
        body.remove(p._p)
    for i, line in enumerate(lines):
        el = copy.deepcopy(protos[min(i, len(protos) - 1)])
        body.append(el)
        from pptx.text.text import _Paragraph
        para = _Paragraph(el, tf)
        runs = para.runs
        if runs:
            runs[0].text = line
            for r in runs[1:]:
                r._r.getparent().remove(r._r)
        else:
            para.text = line


def set_table(shape, rows: list[list[str]]) -> None:
    """Fill a pptx table, cloning the last body row to add rows as needed."""
    tbl = shape.table
    tbl_el = tbl._tbl
    trs = tbl_el.tr_lst
    proto = copy.deepcopy(trs[-1])
    for tr in trs[1:]:
        tbl_el.remove(tr)
    for _ in rows[1:]:
        tbl_el.append(copy.deepcopy(proto))
    for r_i, values in enumerate(rows):
        for c_i, v in enumerate(values):
            tf = tbl.cell(r_i, c_i).text_frame
            p = tf.paragraphs[0]
            if p.runs:
                p.runs[0].text = v
                for r in p.runs[1:]:
                    r._r.getparent().remove(r._r)
            else:
                p.text = v
            for extra in list(tf.paragraphs)[1:]:
                extra._p.getparent().remove(extra._p)


def apply_corrections(folder: Path) -> None:
    for name, fixes in CORRECTIONS.items():
        path = folder / name
        if not path.exists():
            print(f"  missing: {name}")
            continue
        n = correct_pptx(path, fixes) if name.endswith(".pptx") else correct_docx(path, fixes)
        status = "ok" if n == len(fixes) else f"EXPECTED {len(fixes)}"
        print(f"  {name:<42} {n} correction(s) applied  [{status}]")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(Path.home() / "Downloads/ClarifyReview_Review2_Deliverables"))
    ap.add_argument("--corrections-only", action="store_true")
    args = ap.parse_args(argv)
    folder = Path(args.dir).expanduser()
    print("corrections:")
    apply_corrections(folder)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
