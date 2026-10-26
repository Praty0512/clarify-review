"""Cross-check built deliverables against paper/numbers.json.

    python docs/check_deliverables.py <dir-with-the-three-files> [--scaffold]

Dumps the paper, the report and the deck and checks:
  1. placeholder markers: with --scaffold every id in docs/prose_spec.py appears as
     "[[PROSE:id]]" exactly where expected; without it none may appear;
  2. forbidden strings from the plan ("131", "validated against human", "Gemini judge",
     "twelve files", "eleven of twelve", multi-language "out of scope");
  3. every percentage, fraction, two-decimal number (kappa, G, p, CI) and comma-grouped
     number in the text is explained by a value in numbers.json formatted the way the
     builders format it, or is on a short list of quoted CLI scores.
Exit status is non-zero when anything is unexplained.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import dump_text  # noqa: E402
import prose as P  # noqa: E402
import prose_spec as S  # noqa: E402

N = json.loads((ROOT / "paper/numbers.json").read_text(encoding="utf-8"))
# Scores quoted from CLI output in the demonstration (not in numbers.json) and fixed
# design constants stated in the text.
QUOTED = {"0.889", "0.296", "0.556", "0.50", "0.60", "0.5", "0.35", "0.1", "0.00", "1.00", "0.0",
          "22.04", "3.11", "3.9", "4,000", "95%"}   # versions, token budget, CI level
FILES = {"paper": "ClarifyReview_Conference_Paper.docx", "report": "ClarifyReview_Project_I_Report.docx",
         "deck": "ClarifyReview_Review3.pptx"}
FORBIDDEN = [r"\b131 (?:automated )?tests?\b", r"\b131 passed", r"(?<!not )validated against human",
             r"is validated against", r"Gemini judge", r"twelve files",
             r"Multi-language support[^.]*out of scope", r"166 offline"]


def leaves(x, out):
    if isinstance(x, bool) or x is None:
        return
    if isinstance(x, (int, float)):
        out.append(x)
    elif isinstance(x, dict):
        for v in x.values():
            leaves(v, out)
    elif isinstance(x, list):
        for v in x:
            leaves(v, out)


def allowed_sets():
    vals: list = []
    leaves(N, vals)
    pcts, decs, ints, fracs = set(), set(), set(), set()
    for v in vals:
        if isinstance(v, int) or float(v).is_integer():
            ints.add(int(v))
        pcts.add(P.fmt(v, "pct"))
        for f in ("f1", "f2", "f3"):
            decs.add(P.fmt(v, f))
    # k/n fractions: every tests block, every per_condition-style count
    def walk(d):
        if isinstance(d, dict):
            if {"n", "floor", "treatment", "ceiling"} <= set(d):
                for k in ("floor", "treatment", "ceiling"):
                    fracs.add(f"{round(d[k] * d['n'])}/{d['n']}")
            for v in d.values():
                walk(v)
        elif isinstance(d, list):
            for v in d:
                walk(v)
    walk(N)
    # simple counts the builders print as "k of n" or "k/n"
    for v in vals:
        pass
    return pcts, decs, ints, fracs


def main(argv) -> int:
    scaffold = "--scaffold" in argv
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        raise SystemExit(__doc__)
    d = Path(args[0])
    pcts, decs, ints, fracs = allowed_sets()
    bad = 0
    for doc, name in FILES.items():
        text = "\n".join(dump_text.dump(d / name))
        markers = re.findall(r"\[\[PROSE:([a-z0-9_.]+)\]\]", text)
        expected = {e["id"] for e in S.SPEC if e["doc"] == doc}
        if scaffold:
            for pid in sorted(expected - set(markers)):
                print(f"[{doc}] MISSING marker {pid}"); bad += 1
            for pid in sorted(set(markers) - expected):
                print(f"[{doc}] unexpected marker {pid}"); bad += 1
        elif markers:
            print(f"[{doc}] placeholder markers left: {sorted(set(markers))}"); bad += 1
        plain = re.sub(r"\[\[PROSE:[^\]]+\]\]", " ", text)
        plain = re.sub(r"(?m)^(?:\[[^\]]*\]\s*)?\d+\.\d+(?:\.\d+)?\s", " ", plain)  # headings
        plain = re.sub(r"(?m)(?:^|\|\s)\d+\.\d+(?:\.\d+)?(?= [A-Z])", " ", plain)   # TOC rows
        plain = re.sub(r"\(\d/\d\)", " ", plain)                      # slide titles "(1/3)"
        plain = re.sub(r"(?:Section|Table|Figure|Chapter|Listing)s? [\dA]+\.\d+(?:\.\d+)?", " ", plain)
        for rx in FORBIDDEN:
            for m in re.finditer(rx, plain):
                print(f"[{doc}] FORBIDDEN {rx!r}: ...{plain[max(0, m.start() - 40): m.end() + 40]!r}"); bad += 1
        unexplained = set()
        for m in re.finditer(r"(?<![\w.])(-?\d+%)", plain):
            if m.group(1) not in pcts and m.group(1).lstrip("-") not in pcts                     and m.group(1) not in QUOTED:
                unexplained.add(m.group(1))
        for m in re.finditer(r"(?<![\w./])(-?\d+\.\d{2,3})(?![\d.])", plain):
            s = m.group(1)
            if s not in decs and s.lstrip("-") not in decs and s not in QUOTED:
                unexplained.add(s)
        for m in re.finditer(r"(?<![\w./])(\d{1,3}/\d{1,3})(?![\d/])", plain):
            if m.group(1) not in fracs and not re.match(r"\d{1,2}/\d{1,2}$", m.group(1)) is None \
                    and m.group(1) not in {"28/10"}:
                unexplained.add(m.group(1))
        for m in re.finditer(r"(?<![\w.])(\d{1,3}(?:,\d{3})+)(?![\d])", plain):
            if int(m.group(1).replace(",", "")) not in ints and m.group(1) not in QUOTED:
                unexplained.add(m.group(1))
        status = "ok" if not unexplained else f"UNEXPLAINED {sorted(unexplained)}"
        print(f"[{doc}] {len(markers)} markers; numbers: {status}")
        bad += len(unexplained)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
