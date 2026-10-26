"""Judge reviews with an EXTERNAL judge (Claude subagents, the Gemini web app).

Uses the same instructions (judge.SYSTEM), the same per-review context
(judge.build_judge_context) and the same output schema (judge.JudgeVerdict) as
the API judge, but the scoring happens outside this process.

    python -m experiments.external_judge export  --db data/study_v2.db --out-dir runs/external_judge/v2_all --batch-size 12
    python -m experiments.external_judge import  --db data/study_v2.db --out-dir runs/external_judge/v2_all --judge-label gemini-web
    python -m experiments.external_judge compare --db data/study_v2.db --a api --b gemini-web
    python -m experiments.external_judge analyze --db data/study_v2.db --judge-label gemini-web --out runs/report_gemini.json

Storage: the API judge's `judgements` table has run_id as PRIMARY KEY, so it can
hold one judge per run. External scores therefore go in a separate table,
`external_judgements` (PRIMARY KEY run_id + judge_label), created on import with
IF NOT EXISTS. The API rows are never touched. `export`, `compare` and `analyze`
open the database read-only.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import json
import random
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from experiments.judge import SYSTEM, JudgeVerdict, build_judge_context

FIELDS = ("intent_recovered", "defect_caught", "false_alarm")
DEFAULT_SEED = 20260831
API_LABEL = "api"


class ExternalVerdict(JudgeVerdict):
    """The judge's schema plus the opaque id used to map answers back."""

    item_id: str


def _schema() -> dict:
    return ExternalVerdict.model_json_schema()


def _ro(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{Path(db_path).resolve().as_posix()}?mode=ro", uri=True,
                           timeout=60)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (name,)).fetchone() is not None


# ------------------------------------------------------------------ export


def select_rows(db_path: Path, *, run_ids: list[int] | None = None,
                only_unjudged_by: str | None = None, sample: int = 0,
                seed: int = DEFAULT_SEED,
                stratify: list[str] | None = None) -> list[dict]:
    """Judgeable runs (error IS NULL, as the API judge) joined with their instance."""
    with _ro(db_path) as conn:
        rows = [dict(r) for r in conn.execute(
            """SELECT r.*, i.variant, i.has_defect, i.mutation_op, i.mutation_target,
                      i.problem_statement
               FROM runs r JOIN instances i ON i.pr_id = r.pr_id
               WHERE r.error IS NULL ORDER BY r.id""")]
        if only_unjudged_by:
            if only_unjudged_by == API_LABEL:
                have = ({r[0] for r in conn.execute("SELECT run_id FROM judgements")}
                        if _table_exists(conn, "judgements") else set())
            elif _table_exists(conn, "external_judgements"):
                have = {r[0] for r in conn.execute(
                    "SELECT run_id FROM external_judgements WHERE judge_label=?",
                    (only_unjudged_by,))}
            else:
                have = set()
            rows = [r for r in rows if r["id"] not in have]
    if run_ids:
        wanted = set(run_ids)
        rows = [r for r in rows if r["id"] in wanted]
    if sample and sample < len(rows):
        keys = stratify or []
        strata: dict[tuple, list[dict]] = {}
        for r in rows:
            strata.setdefault(tuple(str(r.get(k)) for k in keys), []).append(r)
        rng = random.Random(seed)
        order = sorted(strata)
        pools = {k: rng.sample(strata[k], len(strata[k])) for k in order}
        picked: list[dict] = []
        remaining = sample
        # Equal quota per stratum; what small strata cannot fill goes to the others.
        while remaining > 0 and any(pools.values()):
            live = [k for k in order if pools[k]]
            q = max(1, remaining // len(live))
            for k in live:
                take = pools[k][:min(q, remaining)]
                pools[k] = pools[k][len(take):]
                picked.extend(take)
                remaining -= len(take)
                if remaining <= 0:
                    break
        rows = sorted(picked, key=lambda r: r["id"])
    return rows


OUTPUT_FORMAT = """\
## Output format

Return ONLY a JSON array (no prose, no markdown fences) with exactly one object \
per item above, in any order. Each object must have exactly these keys:

{
  "item_id": string,
  "intent_recovered": true|false,
  "intent_reason": string,
  "defect_caught": true|false,
  "defect_reason": string,
  "false_alarm": true|false,
  "false_alarm_reason": string
}

`item_id` is the id shown in the item header (e.g. "J0001"). The three boolean \
fields are JSON true/false; each *_reason is one sentence. Judge every item \
independently, applying the instructions above to that item alone.
"""


def render_prompt(items: list[dict]) -> str:
    parts = ["# Instructions\n\n", SYSTEM, "\n\n# Items to score\n\n",
             f"There are {len(items)} items. Score each one.\n"]
    for it in items:
        parts.append(f"\n=== ITEM {it['item_id']} BEGIN ===\n{it['judge_context']}"
                     f"=== ITEM {it['item_id']} END ===\n")
    parts.append("\n" + OUTPUT_FORMAT)
    return "".join(parts)


README = """\
External judging - {n_items} items in {n_batches} batches
=========================================================

NEVER paste, upload or share key.csv. It maps the opaque item ids back to run ids,
conditions and variants; the judge must stay blind to all of that.

A) Gemini web app (gemini.google.com), one batch at a time
  1. Open a FRESH chat for every batch. Reusing a chat leaks earlier items into
     later ones.
  2. Turn off anything that adds context: personal context / "Personal
     Intelligence", memory / past-chat recall, Gems, and extensions/apps
     (Workspace, Drive, Gmail, YouTube...). Use a plain model with no extra
     tools; note which model you used.
  3. Open batch_XXX.prompt.md, copy the ENTIRE file and paste it as one message.
  4. Wait for the full reply: a single JSON array. If it is cut off, do not
     continue the chat; rerun the batch in a new chat.
  5. Copy the full JSON reply (code fences or a sentence around it are fine) into
     batch_XXX.response.json in this folder.
  6. Repeat for every batch, then import:
       python -m experiments.external_judge import --db <db> --out-dir <this folder> --judge-label gemini-web --model-name "<model you used>"

B) Claude subagents
  Give each agent one batch_XXX.items.jsonl (one JSON object per line: item_id,
  judge_context, schema) plus the judge instructions at the top of
  batch_XXX.prompt.md. The agent writes batch_XXX.response.json (a JSON array of
  objects matching `schema`, one per item). Do not give agents key.csv or the db.
  Import with --judge-label claude-sonnet-agent (or similar).

Then compare judges:
  python -m experiments.external_judge compare --db <db> --a api --b gemini-web
"""


def export(db_path: Path, out_dir: Path, *, batch_size: int = 10, sample: int = 0,
           seed: int = DEFAULT_SEED, stratify: list[str] | None = None,
           only_unjudged_by: str | None = None,
           run_ids: list[int] | None = None) -> dict:
    rows = select_rows(db_path, run_ids=run_ids, only_unjudged_by=only_unjudged_by,
                       sample=sample, seed=seed, stratify=stratify)
    rows = sorted(rows, key=lambda r: r["id"])
    random.Random(f"{seed}|order").shuffle(rows)
    schema = _schema()
    items = [{"item_id": f"J{n:04d}", "run": r,
              "judge_context": build_judge_context(r, r)} for n, r in enumerate(rows, 1)]

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    size = max(1, batch_size)
    batches = [items[i:i + size] for i in range(0, len(items), size)]
    for b, chunk in enumerate(batches, 1):
        stem = out_dir / f"batch_{b:03d}"
        public = [{"item_id": it["item_id"], "judge_context": it["judge_context"]}
                  for it in chunk]
        Path(f"{stem}.prompt.md").write_text(render_prompt(public), encoding="utf-8",
                                             newline="\n")
        with open(f"{stem}.items.jsonl", "w", encoding="utf-8", newline="\n") as fh:
            for p in public:
                fh.write(json.dumps({**p, "schema": schema}, ensure_ascii=False) + "\n")
    with open(out_dir / "key.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["item_id", "batch", "run_id", "condition", "variant"])
        for b, chunk in enumerate(batches, 1):
            for it in chunk:
                w.writerow([it["item_id"], b, it["run"]["id"], it["run"]["condition"],
                            it["run"]["variant"]])
    (out_dir / "README.txt").write_text(
        README.format(n_items=len(items), n_batches=len(batches)),
        encoding="utf-8", newline="\n")
    return {"items": len(items), "batches": len(batches), "out_dir": str(out_dir)}


# ------------------------------------------------------------------ import

_FENCE = re.compile(r"```(?:json|JSON)?\s*\n?(.*?)```", re.S)


def _flatten(v) -> list:
    if isinstance(v, list):
        return [x for e in v for x in _flatten(e)]
    if isinstance(v, dict) and "item_id" not in v:  # wrapper such as {"results": [...]}
        inner = [x for e in v.values() if isinstance(e, (list, dict)) for x in _flatten(e)]
        if inner:
            return inner
    return [v]


def extract_objects(text: str) -> list:
    """All JSON objects in a model reply, tolerating fences and surrounding prose."""
    for cand in [text.strip()] + [m.strip() for m in _FENCE.findall(text)]:
        try:
            return _flatten(json.loads(cand))
        except ValueError:
            pass
    dec = json.JSONDecoder()
    for opener in "[{":
        out, pos = [], 0
        while True:
            i = text.find(opener, pos)
            if i < 0:
                break
            try:
                v, end = dec.raw_decode(text, i)
            except ValueError:
                pos = i + 1
                continue
            out.extend(_flatten(v))
            pos = end
        if out:
            return out
    return []


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS external_judgements (
            run_id             INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            judge_label        TEXT    NOT NULL,
            intent_recovered   INTEGER,
            defect_caught      INTEGER,
            false_alarm        INTEGER,
            intent_reason      TEXT,
            defect_reason      TEXT,
            false_alarm_reason TEXT,
            judge_model        TEXT,
            imported_at        TEXT,
            PRIMARY KEY (run_id, judge_label)
        )""")


def import_responses(db_path: Path, out_dir: Path, judge_label: str,
                     model_name: str | None = None) -> dict:
    out_dir = Path(out_dir)
    key: dict[str, int] = {}
    with open(out_dir / "key.csv", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            key[r["item_id"]] = int(r["run_id"])

    expected: dict[str, str] = {}  # item_id -> batch stem
    for p in sorted(out_dir.glob("batch_*.items.jsonl")):
        stem = p.name.split(".")[0]
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                expected[json.loads(line)["item_id"]] = stem

    good: dict[str, ExternalVerdict] = {}
    invalid: list[dict] = []
    duplicates: list[str] = []
    unknown: list[str] = []
    files_read, unparsable = [], []
    for p in sorted(out_dir.glob("batch_*.response.json")):
        files_read.append(p.name)
        objs = extract_objects(p.read_text(encoding="utf-8-sig"))
        if not objs:
            unparsable.append(p.name)
            continue
        stem = p.name.split(".")[0]
        for o in objs:
            iid = o.get("item_id") if isinstance(o, dict) else None
            try:
                if not isinstance(o, dict):
                    raise ValueError("not a JSON object")
                for f in FIELDS:  # reject "yes"/2 style values pydantic would coerce
                    if not isinstance(o.get(f), bool):
                        raise ValueError(f"{f} must be a JSON boolean")
                v = ExternalVerdict.model_validate(o)
            except (ValidationError, ValueError) as e:
                invalid.append({"item_id": iid, "file": p.name, "error": str(e)[:200]})
                continue
            if v.item_id not in key:
                unknown.append(v.item_id)
            elif expected.get(v.item_id) != stem:
                unknown.append(f"{v.item_id} (in wrong batch file {p.name})")
            elif v.item_id in good:
                duplicates.append(v.item_id)  # first occurrence wins
            else:
                good[v.item_id] = v

    missing = sorted(set(expected) - set(good))
    stored = 0
    if good:
        conn = sqlite3.connect(db_path, timeout=60)
        try:
            _ensure_table(conn)
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            for iid, v in good.items():
                conn.execute(
                    """INSERT OR REPLACE INTO external_judgements
                       (run_id, judge_label, intent_recovered, defect_caught, false_alarm,
                        intent_reason, defect_reason, false_alarm_reason, judge_model,
                        imported_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (key[iid], judge_label, int(v.intent_recovered), int(v.defect_caught),
                     int(v.false_alarm), v.intent_reason, v.defect_reason,
                     v.false_alarm_reason, model_name or judge_label, now))
                stored += 1
            conn.commit()
        finally:
            conn.close()
    return {"judge_label": judge_label, "stored": stored, "expected": len(expected),
            "missing": missing, "duplicates": sorted(set(duplicates)),
            "invalid": invalid, "unknown_ids": unknown,
            "response_files": files_read, "unparsable_files": unparsable}


# ----------------------------------------------------------------- compare


def load_judge(conn: sqlite3.Connection, label: str) -> tuple[dict[int, dict], set[str]]:
    """run_id -> scores for a label ('api' = the existing judgements table)."""
    if label == API_LABEL:
        if not _table_exists(conn, "judgements"):
            return {}, set()
        q, args = "SELECT * FROM judgements", ()
    else:
        if not _table_exists(conn, "external_judgements"):
            return {}, set()
        q, args = "SELECT * FROM external_judgements WHERE judge_label=?", (label,)
    rows = {r["run_id"]: dict(r) for r in conn.execute(q, args)}
    return rows, {r["judge_model"] for r in rows.values() if r["judge_model"]}


def compare(db_path: Path, a: str, b: str) -> dict:
    from experiments.analyze import _agreement

    with _ro(db_path) as conn:
        ra, ma = load_judge(conn, a)
        rb, mb = load_judge(conn, b)
    shared = sorted(set(ra) & set(rb))
    out: dict = {"a": {"label": a, "models": sorted(ma), "n_runs": len(ra)},
                 "b": {"label": b, "models": sorted(mb), "n_runs": len(rb)},
                 "n_shared_runs": len(shared), "fields": {}}
    for f in FIELDS:
        ids = [i for i in shared if ra[i][f] is not None and rb[i][f] is not None]
        out["fields"][f] = _agreement([int(ra[i][f]) for i in ids],
                                      [int(rb[i][f]) for i in ids])
    return out


# ----------------------------------------------------------------- analyze


@contextlib.contextmanager
def judged_copy(db_path: Path, label: str):
    """Yield a temporary copy of the db whose `judgements` hold `label`'s scores.

    `label` 'api' leaves the existing judgements as they are. The source db is
    opened read-only and is never modified; the copy is deleted on exit.
    """
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "copy.db"
        with _ro(db_path) as src:
            dst = sqlite3.connect(tmp)
            src.backup(dst)
            dst.close()
        conn = sqlite3.connect(tmp)
        try:
            conn.execute("PRAGMA foreign_keys = OFF")
            if label != API_LABEL:
                conn.execute("DROP TABLE IF EXISTS judgements")
                conn.execute(
                    """CREATE TABLE judgements (
                        run_id INTEGER PRIMARY KEY, intent_recovered INTEGER,
                        defect_caught INTEGER, false_alarm INTEGER, intent_reason TEXT,
                        defect_reason TEXT, false_alarm_reason TEXT, judge_model TEXT)""")
                if _table_exists(conn, "external_judgements"):
                    conn.execute(
                        """INSERT INTO judgements SELECT run_id, intent_recovered,
                           defect_caught, false_alarm, intent_reason, defect_reason,
                           false_alarm_reason, judge_model FROM external_judgements
                           WHERE judge_label=?""", (label,))
            conn.commit()
        finally:
            conn.close()
        yield tmp


def analyze_with_label(db_path: Path, label: str, out: Path) -> dict:
    """Study A report using `label`'s scores, computed on a temporary db copy."""
    from experiments import analyze

    with judged_copy(db_path, label) as tmp:
        conn = sqlite3.connect(tmp)
        try:
            n = conn.execute("SELECT COUNT(*) FROM judgements").fetchone()[0]
        finally:
            conn.close()
        report = analyze.study_a_report(tmp)
    report["judge"] = {"label": label, "n_judged_runs": n}
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


# --------------------------------------------------------------------- cli


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("export", help="write prompts/items/key for external judging")
    e.add_argument("--db", required=True)
    e.add_argument("--out-dir", required=True)
    e.add_argument("--batch-size", type=int, default=10)
    e.add_argument("--sample", type=int, default=0)
    e.add_argument("--seed", type=int, default=DEFAULT_SEED)
    e.add_argument("--stratify", default="", help="comma list, e.g. condition,variant")
    e.add_argument("--only-unjudged-by", default=None, metavar="LABEL")
    e.add_argument("--run-ids", nargs="+", type=int, default=None)

    i = sub.add_parser("import", help="read batch_XXX.response.json files into the db")
    i.add_argument("--db", required=True)
    i.add_argument("--out-dir", required=True)
    i.add_argument("--judge-label", required=True)
    i.add_argument("--model-name", default=None)

    c = sub.add_parser("compare", help="per-field agreement between two judges")
    c.add_argument("--db", required=True)
    c.add_argument("--a", required=True)
    c.add_argument("--b", required=True)

    a = sub.add_parser("analyze", help="Study A report using one judge's scores")
    a.add_argument("--db", required=True)
    a.add_argument("--judge-label", required=True)
    a.add_argument("--out", required=True)

    args = ap.parse_args(argv)
    if args.cmd == "export":
        res = export(Path(args.db), Path(args.out_dir), batch_size=args.batch_size,
                     sample=args.sample, seed=args.seed,
                     stratify=[s for s in args.stratify.split(",") if s],
                     only_unjudged_by=args.only_unjudged_by, run_ids=args.run_ids)
        print(json.dumps(res, indent=2))
    elif args.cmd == "import":
        res = import_responses(Path(args.db), Path(args.out_dir), args.judge_label,
                               args.model_name)
        print(json.dumps(res, indent=2))
        return 1 if (res["missing"] or res["invalid"] or res["duplicates"]
                     or res["unknown_ids"]) else 0
    elif args.cmd == "compare":
        print(json.dumps(compare(Path(args.db), args.a, args.b), indent=2))
    else:
        rep = analyze_with_label(Path(args.db), args.judge_label, Path(args.out))
        print(json.dumps(rep, indent=2, sort_keys=True))
        print(f"\nwritten to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
