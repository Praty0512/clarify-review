"""Prose placeholders for the deliverables: text lives in docs/prose_v3.json.

The builders contain no new narrative. Wherever a sentence or paragraph is
wanted they call prose("<id>"), and the text comes from docs/prose_v3.json:

    {"report.s7_9.setup": "... {v3_setup.wall_minutes:int} minutes ... {v3_local.tests.intent_all.gap_recovery:f2} ..."}

A {key.path:fmt} token is replaced with the value found at that path in
paper/numbers.json, formatted by `fmt`. The same tokens and formats are read by
paper/prose.js, so the paper, the report and the deck cannot disagree.

Failure rules (this is deliberate):
  * an empty or missing placeholder raises PlaceholderError, so a build cannot
    ship with a hole in it;
  * an unknown or unformattable token raises PlaceholderError;
  * with ALLOW_EMPTY_PROSE=1 an empty placeholder renders the visible marker
    "[[PROSE:<id>]]" instead. Use that for scaffold builds into a scratch folder only.

Formats: pct (0.6667 -> "67%"), f1 f2 f3 (fixed decimals), p2 (p-value, "<0.01" when
tiny), int, k (thousands separators), word (0-20 spelled out), ci ([a, b] ->
"a to b", two decimals), str (as is). A bare token is allowed only for strings and
integers.

    python docs/prose.py check       # ids used in the code == spec == json; lint
"""

from __future__ import annotations

import json
import math
import os
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROSE_JSON = ROOT / "docs/prose_v3.json"
NUMBERS = ROOT / "paper/numbers.json"
TOKEN = re.compile(r"\{([A-Za-z0-9_.]+)(?::([a-z0-9]+))?\}")
WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
         "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
         "eighteen", "nineteen", "twenty"]


class PlaceholderError(RuntimeError):
    pass


def allow_empty() -> bool:
    return os.environ.get("ALLOW_EMPTY_PROSE", "") not in ("", "0")


def _half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def fixed(x: float, d: int) -> str:
    """Fixed decimals, ties away from zero, on the decimal text (matches paper/prose.js)."""
    q = Decimal(repr(float(x))).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP)
    return f"{q:.{d}f}"


def numword(n: int) -> str:
    return WORDS[n] if 0 <= n < len(WORDS) else str(n)


def _num(v, tok):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise PlaceholderError(f"token {{{tok}}}: not a number ({v!r})")
    return v


def fmt(value, spec: str | None, tok: str = "") -> str:
    if value is None:
        return "n/a"
    if spec in (None, "str"):
        if isinstance(value, bool) or isinstance(value, (list, dict)):
            raise PlaceholderError(f"token {{{tok}}}: needs a format for {type(value).__name__}")
        if isinstance(value, float):
            raise PlaceholderError(f"token {{{tok}}}: a float needs a format (pct, f2, ...)")
        return str(value)
    if spec == "pct":
        return f"{_half_up(_num(value, tok) * 100)}%"
    if spec in ("f1", "f2", "f3"):
        return fixed(_num(value, tok), int(spec[1]))
    if spec == "p2":
        v = _num(value, tok)
        return "<0.01" if v < 0.005 else fixed(v, 2)
    if spec == "int":
        return str(_half_up(_num(value, tok)))
    if spec == "k":
        return f"{_half_up(_num(value, tok)):,}"
    if spec == "word":
        return numword(_half_up(_num(value, tok)))
    if spec == "ci":
        if not (isinstance(value, list) and len(value) == 2):
            raise PlaceholderError(f"token {{{tok}}}: ci needs a two-element list")
        return f"{fixed(_num(value[0], tok), 2)} to {fixed(_num(value[1], tok), 2)}"
    raise PlaceholderError(f"token {{{tok}}}: unknown format {spec!r}")


_N: dict | None = None


def numbers() -> dict:
    global _N
    if _N is None:
        _N = json.loads(NUMBERS.read_text(encoding="utf-8"))
    return _N


def lookup(path: str, nums: dict | None = None):
    cur = numbers() if nums is None else nums
    for seg in path.split("."):
        if isinstance(cur, dict) and seg in cur:
            cur = cur[seg]
        elif isinstance(cur, list) and seg.isdigit() and int(seg) < len(cur):
            cur = cur[int(seg)]
        else:
            raise PlaceholderError(f"unknown key path {path!r} (stopped at {seg!r})")
    return cur


def render(text: str, nums: dict | None = None) -> str:
    def sub(m):
        tok = m.group(1) + (":" + m.group(2) if m.group(2) else "")
        return fmt(lookup(m.group(1), nums), m.group(2), tok)

    return TOKEN.sub(sub, text)


_CACHE: dict | None = None
USED: set[str] = set()


def _load() -> dict:
    global _CACHE
    if _CACHE is None:
        try:
            _CACHE = json.loads(PROSE_JSON.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise PlaceholderError(f"cannot read {PROSE_JSON}: {e}") from e
    return _CACHE


def prose(pid: str, nums: dict | None = None) -> str:
    """The text for placeholder `pid`, with tokens resolved. Raises when empty."""
    USED.add(pid)
    data = _load()
    if pid not in data:
        raise PlaceholderError(f"placeholder {pid!r} is not in {PROSE_JSON.name}")
    text = data[pid]
    if not isinstance(text, str) or not text.strip():
        if allow_empty():
            return f"[[PROSE:{pid}]]"
        raise PlaceholderError(
            f"placeholder {pid!r} is empty in {PROSE_JSON.name} "
            "(set ALLOW_EMPTY_PROSE=1 for a scaffold build)")
    return render(text.strip(), nums)


def reload() -> None:
    global _CACHE, _N
    _CACHE = None
    _N = None


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import prose_tool

    raise SystemExit(prose_tool.main(sys.argv[1:]))
