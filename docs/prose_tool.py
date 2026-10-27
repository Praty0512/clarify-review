"""Maintain docs/prose_v3.json and its brief.

    python docs/prose_tool.py sync     # add every spec id to prose_v3.json (existing text is kept)
    python docs/prose_tool.py brief    # write docs/prose_v3_brief.md
    python docs/prose_tool.py check    # ids in code == spec == json; lint the written text
    python docs/prose_tool.py lint     # lint only

`sync` never writes prose: new ids get an empty string, so a build fails loudly
until a writer fills them (or ALLOW_EMPTY_PROSE=1 for a scaffold build).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import prose as P  # noqa: E402
import prose_spec as S  # noqa: E402

SOURCES = [ROOT / "docs/report_content.py", ROOT / "docs/build_deck.py", ROOT / "docs/build_report.py",
           ROOT / "paper/build_paper.js"]
USE = re.compile(r'(?:PROSE|prose)\(\s*"([a-z0-9_.]+)"')
LABEL = re.compile(r"(?:Fig\.|Figs\.|Figure|Table|Tables|Section|Sections|Chapter)\s+[0-9IVX.\-]+[A-G]?"
                   r"(?:\s*(?:and|and Table|,)\s*[0-9IVX.\-]+)*")
TOKEN = P.TOKEN
FORBIDDEN = [
    (re.compile(r"\btrend(?:s|ing)? (?:toward|towards)\b|\btrending\b", re.I), "'trend toward' on a null result"),
    (re.compile(r"(?<!not )(?<!never )(?<!un)\bvalidat(?:ed|es|ion)\b(?! against humans? is)", re.I),
     "'validated/validation' (AI-vs-AI is agreement, never validation; negated use is "
     "'not validated')"),
    (re.compile(r"\bGemini (?:API )?judge\b", re.I), "the v2 API judge is gemma-4-31b-it, not 'Gemini'"),
    (re.compile(r"\b131\b"), "stale test count"),
    (re.compile(r"significant(?:ly)? (?:improv|better|effect)", re.I), "claims significance"),
    (re.compile(r"\bproves?\b|\bdemonstrates that\b", re.I), "overclaim"),
]
US = re.compile(r"\b(?:behavior|color|analyze[sd]?|recognize[sd]?|generalize[sd]?|organization|"
                r"favor(?:s|ed|ing)?|normalize[sd]?|emphasize[sd]?)\b", re.I)


def used_ids() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for src in SOURCES:
        for pid in USE.findall(src.read_text(encoding="utf-8")):
            out.setdefault(pid, []).append(src.name)
    return out


def sync() -> int:
    cur = json.loads(P.PROSE_JSON.read_text(encoding="utf-8")) if P.PROSE_JSON.exists() else {}
    new = {pid: cur.get(pid, "") for pid in S.IDS}
    stale = sorted(set(cur) - set(S.IDS))
    P.PROSE_JSON.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8", newline="\n")
    print(f"wrote {P.PROSE_JSON} ({len(new)} ids, {sum(1 for v in new.values() if v.strip())} filled)")
    if stale:
        print("dropped ids no longer in the spec:", ", ".join(stale))
    return 0


def lint_text(pid: str, text: str, allowed: set[str]) -> list[str]:
    errs = []
    stripped = TOKEN.sub("", text)
    stripped = LABEL.sub("", stripped)
    for m in re.finditer(r"\d", stripped):
        ctx = stripped[max(0, m.start() - 20): m.end() + 20].replace("\n", " ")
        errs.append(f"{pid}: digit outside a {{token}} or a Table/Figure/Section label: ...{ctx}...")
        break
    for m in TOKEN.finditer(text):
        path = m.group(1)
        if path not in allowed:
            errs.append(f"{pid}: token {{{path}}} is not in this placeholder's allowed list")
        try:
            P.fmt(P.lookup(path), m.group(2), path)
        except P.PlaceholderError as e:
            errs.append(f"{pid}: {e}")
    for rx, why in FORBIDDEN:
        if rx.search(stripped):
            errs.append(f"{pid}: {why}: '{rx.search(stripped).group(0)}'")
    if US.search(stripped):
        errs.append(f"{pid}: American spelling '{US.search(stripped).group(0)}' (use British)")
    if "—" in text or "–" in text:
        errs.append(f"{pid}: dash character (use a comma, colon or hyphen)")
    return errs


def lint() -> list[str]:
    data = json.loads(P.PROSE_JSON.read_text(encoding="utf-8"))
    spec = {e["id"]: e for e in S.SPEC}
    errs = []
    for pid, text in data.items():
        if not isinstance(text, str) or not text.strip() or pid not in spec:
            continue
        allowed = {t.split(":")[0] for t in spec[pid]["tokens"]}
        errs += lint_text(pid, text, allowed)
    return errs


def check() -> int:
    used = used_ids()
    spec_ids = set(S.IDS)
    data = json.loads(P.PROSE_JSON.read_text(encoding="utf-8")) if P.PROSE_JSON.exists() else {}
    problems = []
    for pid in sorted(set(used) - spec_ids):
        problems.append(f"used in {used[pid]} but missing from prose_spec: {pid}")
    for pid in sorted(spec_ids - set(used)):
        problems.append(f"in prose_spec but never used by a builder: {pid}")
    for pid in sorted(spec_ids - set(data)):
        problems.append(f"missing from prose_v3.json: {pid}")
    for pid in sorted(set(data) - spec_ids):
        problems.append(f"in prose_v3.json but not in prose_spec: {pid}")
    for e in S.SPEC:  # every allowed token must resolve in numbers.json
        for t in e["tokens"]:
            path, _, spec = t.partition(":")
            try:
                P.fmt(P.lookup(path), spec or None, path)
            except P.PlaceholderError as ex:
                problems.append(f"{e['id']}: spec token {t}: {ex}")
    problems += lint()
    empty = [pid for pid in S.IDS if not str(data.get(pid, "")).strip()]
    for p in problems:
        print("PROBLEM:", p)
    print(f"{len(S.IDS)} placeholders; {len(S.IDS) - len(empty)} filled, {len(empty)} empty")
    return 1 if problems else 0


# ---------------------------------------------------------------------- brief

BRIEF_HEAD = """\
# Prose brief for docs/prose_v3.json

You write **only** `docs/prose_v3.json`: one string per placeholder id, nothing else.
The builders (`paper/build_paper.js`, `docs/build_report.py`, `docs/build_deck.py`) fail
if any placeholder is empty. Check your work with `python docs/prose_tool.py check`.

## How numbers work

* Never type a digit. Every number comes from a token written `{key.path:fmt}`, which
  the builders replace from `paper/numbers.json`. The lint rejects any digit outside a
  token, except in labels such as `Table III`, `Fig. 6`, `Figure 7.4`, `Section V-G`,
  `Section 7.9`, `Chapter 7`.
* Use only the tokens listed under each id (the lint checks this). The list shows the
  value each token has today, so you can write sentences that are true.
* Formats: `pct` (0.6667 -> 67%), `f2` (two decimals), `int`, `k` (thousands separator),
  `word` (7 -> seven, 0 to 20), `ci` ([a, b] -> "a to b", two decimals), none for text.
  A float needs a format. `gap_points` and similar `derived.*` values are integers.
* Braces in the "Framing notes" (for example {n_new_rows}) are shorthand for the tokens in the table below them.
* A token resolves only to a number or a name that exists in `numbers.json`; if you need a
  number that is not listed, say so rather than writing it.

## Honesty rules (from the plan)

1. A null result is reported **with a bound**: "not significant", never "trend toward".
2. AI judges give **AI-vs-AI agreement**, never "validation". Human validation of the
   judge has not been done; say so wherever the judge is discussed.
3. The v3 agent-judge choice was made **after seeing agreement** with the local judge: disclose
   it as a post hoc choice.
4. Every not-done item is stated as not done (human judge validation, real-PR labelling,
   permanent hosting and runs on real third-party PRs at scale, the 300-PR classifier training,
   Study B).
5. v2 and v3 are **never pooled**. v3 is a separate study with a different reviewer, a different
   question/oracle model and different rows.
6. "Gemini" names only the v2 reviewer (gemini-3.5-flash-lite) and the web-app judge. The v2 API
   judge is **gemma-4-31b-it**.
7. The bot **has been run on live GitHub**, but only as a demonstration: two constructed PRs in
   the authors' own sandbox repository (`live_demo.*`), the command-line tool and the webhook bot
   from a laptop behind a tunnel. It is not an evaluation, estimates no rate, and says nothing
   about third-party PRs. It also passes offline end-to-end tests.
8. Voice: IEEE, terse, British spelling (behaviour, analyse, recognise), no em dashes, no
   exclamation, no marketing. Match the existing text around each placeholder.

## Numbering of things you may refer to

Paper: Table I (v2 outcomes), II (detectors), III (v3 outcomes), IV (judge pairs); Fig. 3 (v2
results), 4 (funnel), 5 (detectors), 6 (v3 results), 7 (judge kappa heatmap); sections V-F
(local replication) and V-G (judge calibration); IV-F (v3 design).
Report: Table 7.4 (v3 outcomes), 7.5 (judge pairs); Figure 7.4 (v3 results), 7.5 (v3 funnel),
7.6 (judge kappa heatmap), 7.7 (G under each judge); Sections 7.8 (local replication), 7.9
(judge calibration), 7.10 (threats), 5.2.7 (v3 design), 5.1.5 (bot). Note: the plan numbered
the new sections 7.9 to 7.11; the builder numbers them contiguously (7.8 to 7.10) because 7.8
was the old threats section.
Deck: slide 14 is the new "Experiments and Results (3/3)" slide with Fig. v3 results and the
judge heatmap.

## Placeholders
"""


def _value(path: str, spec: str):
    try:
        v = P.lookup(path)
    except P.PlaceholderError as e:
        return f"!! {e}"
    try:
        return P.fmt(v, spec or None, path)
    except P.PlaceholderError:
        return json.dumps(v)


def brief() -> int:
    lines = [BRIEF_HEAD]
    by_doc: dict[str, list[dict]] = {}
    for e in S.SPEC:
        by_doc.setdefault(e["doc"], []).append(e)
    lines.append("Index: " + "; ".join(f"{d}: {len(v)}" for d, v in by_doc.items())
                 + f"; total {len(S.SPEC)}.\n")
    for doc in ("paper", "report", "deck"):
        lines.append(f"\n---\n\n## {doc.capitalize()}\n")
        for e in by_doc.get(doc, []):
            lines.append(f"### `{e['id']}`\n")
            lines.append(f"* **Appears in:** {doc}, {e['where']}")
            lines.append(f"* **Kind / target length:** {e['kind']}; {e['words']} words")
            if e["replaces"]:
                lines.append(f"* **Replaces this existing text:** \"{e['replaces']}\"")
            lines.append(f"* **Framing notes:** {e['notes']}")
            if e["tokens"]:
                lines.append("* **Allowed tokens (current value):**\n")
                lines.append("  | token | value now |")
                lines.append("  |---|---|")
                for t in e["tokens"]:
                    path, _, spec = t.partition(":")
                    tok = "{" + path + (":" + spec if spec else "") + "}"
                    lines.append(f"  | `{tok}` | {_value(path, spec)} |")
            else:
                lines.append("* **Allowed tokens:** none (no number may appear)")
            lines.append("")
    out = ROOT / "docs/prose_v3_brief.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {out} ({len(S.SPEC)} placeholders)")
    return 0


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "check"
    if cmd == "sync":
        return sync()
    if cmd == "brief":
        return brief()
    if cmd == "lint":
        errs = lint()
        print("\n".join(errs) or "lint clean")
        return 1 if errs else 0
    if cmd == "check":
        return check()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
