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
