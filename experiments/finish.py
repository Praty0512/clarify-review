"""Finish the project from the human-filled data, in one command.

Everything here reads files that people filled in and runs the offline analysis
that turns them into the paper's numbers. It never invents a label, a rating or a
response: a step whose human input is missing or incomplete is reported as blocked
with the exact counts, and nothing downstream of it runs.

    python -m experiments.finish --status           # read-only table, writes nothing
    python -m experiments.finish                     # run every step that is ready
    python -m experiments.finish --allow-partial     # interim kappa only, no JSONL/training
    python -m experiments.finish --paper never       # skip numbers.json / the .docx
    python -m experiments.finish --labelling-set realpr --status   # the real-PR sheet

Steps, in order: labelling -> training -> judge -> study_b -> paper.

--labelling-set realpr runs labelling and training for the real-PR sheet
(runs/realpr/labelling_sheet.csv) into its own JSONL, model and thresholds files and
skips the judge/study/paper steps; it never writes the study's model or thresholds.

Never called from here: label_tool sheet, judge --sample-for-humans,
study.build_study (all would replace the material people already worked from),
and anything that calls an LLM API. Re-running Study A with the frozen thresholds
is an API step and is left to you.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from experiments import analyze, label_tool, train_classifier
from paper import collect
from study import build_study, merge_responses

ROOT = Path(__file__).resolve().parents[1]

DONE, BLOCKED, SKIPPED, FAILED = "done", "blocked", "skipped", "failed"
STEP_ORDER = ["labelling", "training", "judge", "study_b", "paper"]


@dataclass
class StepResult:
    """status is done | blocked | skipped | failed. In --status mode a step that
    could run is reported as skipped with "ready" in its detail."""
    name: str
    status: str
    detail: str = ""
    outputs: list[str] = field(default_factory=list)
    needs: str = ""          # what a person still has to do, when blocked


@dataclass(frozen=True)
class LabelSet:
    """Where one labelling pass lives. SWEBENCH is the study's and the default."""
    name: str
    sheet: str
    label_dir: str
    jsonl: str
    agreement: str
    model: str
    thresholds: str
    sweep: str
    diff_source: str
    study_steps: bool          # judge / study_b / paper belong to the study only


SWEBENCH = LabelSet("swebench", "runs/labelling_sheet.csv", "runs/labelling",
                    "data/labelled_prs.jsonl", "runs/labelling_agreement.json",
                    "data/models/ambiguity_clf.joblib", "data/thresholds.json",
                    "runs/threshold_sweep.json", "sheet", True)
REALPR = LabelSet("realpr", "runs/realpr/labelling_sheet.csv", "runs/realpr/labelling",
                  "data/labelled_prs.realpr.jsonl", "runs/realpr/labelling_agreement.json",
                  "data/models/ambiguity_clf.realpr.joblib", "data/thresholds.realpr.json",
                  "runs/realpr/threshold_sweep.json", "cache", False)
LABEL_SETS = {"swebench": SWEBENCH, "realpr": REALPR}


# ------------------------------------------------------------------ plumbing


def _call(fn, argv: list[str]) -> tuple[int, str]:
    """Run a tool's main(argv), capturing what it prints; returns (exit code, output)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            rc = fn(argv)
        except SystemExit as e:                      # argparse errors
            rc = e.code if isinstance(e.code, int) else 2
    return int(rc or 0), buf.getvalue().strip()


def _tail(text: str, n: int = 3) -> str:
    lines = [l for l in text.splitlines() if l.strip()]
    return " / ".join(lines[-n:])


# Seams the tests replace; each is the only place that is slow, needs a network
# or needs node.
def _train(argv: list[str]) -> int:
    return train_classifier.main(argv)


def _collect(root: Path) -> int:
    return collect.main(root)


def _run_node(root: Path) -> tuple[int, str]:
    node = shutil.which("node")
    if not node:
        return 1, "node is not on PATH"
    res = subprocess.run([node, "paper/build_paper.js"], cwd=root, capture_output=True, text=True)
    return res.returncode, (res.stdout + res.stderr).strip()


# ----------------------------------------------------------------- labelling

LABELS = ("0", "1")


def _label_files(root: Path, ls: LabelSet = SWEBENCH) -> dict[str, list[Path]]:
    """Per-annotator files that actually contain at least one label."""
    d = root / ls.label_dir
    found: dict[str, list[Path]] = {}
    for n in (1, 2):
        col = f"annotator_{n}"
        for p in (d / f"{col}_labels.csv", d / f"{col}.csv"):
            if not p.exists():
                continue
            try:
                rows = label_tool._read_rows(p)
            except Exception:
                continue
            if any(label_tool._norm(r.get(col, "")) in LABELS for r in rows):
                found.setdefault(col, []).append(p)
    return found


def _labelling_state(rows: list[dict]) -> dict:
    a = [label_tool._norm(r.get("annotator_1", "")) for r in rows]
    b = [label_tool._norm(r.get("annotator_2", "")) for r in rows]
    adj = [label_tool._norm(r.get("adjudicated", "")) for r in rows]
    both = [i for i in range(len(rows)) if a[i] in LABELS and b[i] in LABELS]
    dis = [i for i in both if a[i] != b[i]]
    st = {
        "n": len(rows),
        "missing_a1": sum(1 for x in a if x not in LABELS),
        "missing_a2": sum(1 for x in b if x not in LABELS),
        "both": len(both),
        "disagree": len(dis),
        "unadjudicated": sum(1 for i in dis if adj[i] not in LABELS),
    }
    st["ready"] = bool(rows) and not st["missing_a1"] and not st["missing_a2"] \
        and not st["unadjudicated"]
    return st


def _overlay(rows: list[dict], files: dict[str, list[Path]]) -> list[dict]:
    """The master as combine would leave it (in memory), for --status."""
    rows = [dict(r) for r in rows]
    by_id = {r["pr_id"]: r for r in rows}
    for col, paths in files.items():
        for p in paths:
            for r in label_tool._read_rows(p):
                tgt = by_id.get(r.get("pr_id"))
                v = label_tool._norm(r.get(col, ""))
                if tgt is not None and v in LABELS and label_tool._norm(tgt.get(col, "")) not in LABELS:
                    tgt[col] = v
    return rows


def _describe(st: dict) -> str:
    return (f"{st['n']} rows; annotator_1 missing {st['missing_a1']}, annotator_2 missing "
            f"{st['missing_a2']}, {st['disagree']} disagreements of which "
            f"{st['unadjudicated']} unadjudicated")


def step_labelling(root: Path, dry: bool, allow_partial: bool,
                   ls: LabelSet = SWEBENCH) -> StepResult:
    sheet = root / ls.sheet
    report = root / ls.agreement
    jsonl = root / ls.jsonl
    r = StepResult("labelling", BLOCKED)
    if not sheet.exists():
        r.detail = f"{sheet.relative_to(root)} does not exist"
        r.needs = ("create the labelling sheet (python -m experiments.fetch_prs --repos ...)"
                   if ls is not SWEBENCH
                   else "create the labelling sheet (python -m experiments.label_tool sheet)")
        return r
    files = _label_files(root, ls)
    if dry:
        rows = _overlay(label_tool._read_rows(sheet), files)
    else:
        if files:
            argv = ["combine", str(sheet)] + [str(p) for ps in files.values() for p in ps]
            rc, out = _call(label_tool.main, argv)
            if rc != 0:
                return StepResult("labelling", FAILED, f"combine failed: {_tail(out, 6)}")
        rows = label_tool._read_rows(sheet)
    st = _labelling_state(rows)
    people = (f"both annotators label every row ({ls.label_dir}/annotator_N.html or .csv), then the "
              f"disagreements are adjudicated in {ls.sheet}")
    if not st["ready"]:
        r.detail = _describe(st)
        r.needs = people
        if allow_partial and st["both"]:
            a = [label_tool._norm(x.get("annotator_1", "")) for x in rows]
            b = [label_tool._norm(x.get("annotator_2", "")) for x in rows]
            k, info = label_tool.kappa(a, b)
            r.detail += f"; interim kappa {k:.3f} on {info['n']} rows (not written anywhere)"
        elif allow_partial:
            r.detail += "; no row has both labels yet"
        return r
    if dry:
        r.status, r.detail = SKIPPED, f"ready to run: {_describe(st)}"
        return r
    tmp = (root / "runs/.labelled_prs.tmp.jsonl" if ls is SWEBENCH
           else jsonl.with_name(".labelled_prs.realpr.tmp.jsonl"))
    tmp.parent.mkdir(parents=True, exist_ok=True)
    argv = ["agree", str(sheet), "--a", "annotator_1", "--b", "annotator_2",
            "--to-jsonl", str(tmp), "--diff-source", ls.diff_source, "--report-json", str(report)]
    if ls.diff_source == "cache":
        argv += ["--cache-dir", str(root / "data/cache/realpr")]
    rc, out = _call(label_tool.main, argv)
    if rc != 0:
        tmp.unlink(missing_ok=True)
        return StepResult("labelling", FAILED, f"agree failed: {_tail(out, 6)}")
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    if jsonl.exists() and jsonl.read_bytes() == tmp.read_bytes():
        tmp.unlink()                                  # unchanged: keep mtime, no retrain needed
    else:
        tmp.replace(jsonl)
    r.status = DONE
    r.detail = _describe(st) + f"; {_tail(out, 1)}"
    r.outputs = [str(report.relative_to(root)), str(jsonl.relative_to(root))]
    return r


# ------------------------------------------------------------------ training


def step_training(root: Path, dry: bool, allow_partial: bool, labelling: StepResult,
                  ls: LabelSet = SWEBENCH) -> StepResult:
    jsonl = root / ls.jsonl
    report = root / ls.sweep
    thr = root / ls.thresholds
    r = StepResult("training", BLOCKED)
    if allow_partial:
        r.status, r.detail = SKIPPED, "--allow-partial: no JSONL, no training"
        return r
    if labelling.status in (FAILED, BLOCKED):
        r.detail = "labelling is not finished"
        r.needs = "finish labelling first"
        return r
    if not jsonl.exists():                            # dry run, labelling ready but not yet run
        r.status, r.detail = SKIPPED, "ready once the labelling step has run"
        return r
    current = report.exists() and thr.exists() and report.stat().st_mtime >= jsonl.stat().st_mtime
    if dry:
        r.status = DONE if current else SKIPPED
        r.detail = "frozen thresholds are current" if current else "ready to run"
        return r
    if current:
        r.status, r.detail = DONE, "frozen thresholds already current for the labelled set"
        r.outputs = [str(report.relative_to(root)), str(thr.relative_to(root))]
        return r
    rc = _train([
        "--labels", str(jsonl), "--out", str(root / ls.model),
        "--sweep-thresholds", "--thresholds-out", str(thr), "--report-out", str(report)])
    if rc != 0:
        return StepResult("training", FAILED, f"train_classifier exited {rc}")
    r.status = DONE
    r.detail = ("heuristic and classifier thresholds frozen on the dev split. WARNING: Study A used "
                "the DEFAULT thresholds; re-running it with these is an API step and was NOT run"
                if ls is SWEBENCH else
                f"classifier and thresholds for the real-PR set written to {ls.model} and "
                f"{ls.thresholds}; the study's model and thresholds were not touched")
    r.outputs = [str(report.relative_to(root)), str(thr.relative_to(root))]
    return r


# --------------------------------------------------------------------- judge


def _judge_fill(path: Path) -> tuple[int, int]:
    """(rows, rows still missing a required human_* cell)."""
    rows = label_tool._read_rows(path)
    missing = 0
    for r in rows:
        need = ["human_intent_recovered"]
        need.append("human_defect_caught" if label_tool._norm(r.get("has_defect", "")) == "1"
                    else "human_false_alarm")
        if any(label_tool._norm(r.get(c, "")) not in LABELS for c in need):
            missing += 1
    return len(rows), missing


def step_judge(root: Path, dry: bool) -> StepResult:
    d = root / "runs/judge_validation"
    out = root / "runs/judge_agreement.json"
    files = sorted(p for p in d.glob("*.csv") if p.stem.upper() != "INSTRUCTIONS") if d.exists() else []
    r = StepResult("judge", BLOCKED)
    if not files:
        r.detail = "no blind copies in runs/judge_validation/"
        r.needs = "make blind copies (judge --blind-copies NAME NAME) and have two people score them"
        return r
    filled: list[Path] = []
    notes: list[str] = []
    for p in files:
        try:
            n, missing = _judge_fill(p)
        except Exception as e:                        # unreadable file is a result, not a crash
            notes.append(f"{p.name}: unreadable ({e})")
            continue
        if n and not missing:
            filled.append(p)
        else:
            notes.append(f"{p.name}: {missing} of {n} rows incomplete")
    if len(filled) < 2:
        r.detail = f"{len(filled)} of {len(files)} blind copies fully scored (need 2)"
        if notes:
            r.detail += "; " + "; ".join(notes)
        r.needs = "two scorers fill human_* in runs/judge_validation/<name>.csv independently"
        return r
    if dry:
        r.status, r.detail = SKIPPED, f"ready to run on {len(filled)} fully scored copies"
        return r
    argv = ["--judge-agreement", *[str(p) for p in filled],
            "--reference", str(root / "runs/judge_validation_sample.csv"), "--out", str(out)]
    rc, text = _call(analyze.main, argv)
    if rc != 0 or not out.exists():
        return StepResult("judge", FAILED, f"analyze exited {rc}: {_tail(text)}")
    r.status, r.detail = DONE, f"agreement from {', '.join(p.stem for p in filled)}"
    r.outputs = [str(out.relative_to(root))]
    return r


# ------------------------------------------------------------------- study B


def _participants(files: list[Path]) -> set[str]:
    seen: set[str] = set()
    for f in files:
        try:
            with f.open(newline="", encoding="utf-8-sig") as fh:
                for row in csv.DictReader(fh):
                    if row.get("usefulness") and row.get("trust") and row.get("participant"):
                        seen.add(row["participant"].strip().lower())
        except Exception:
            continue
    return seen


def step_study_b(root: Path, dry: bool, min_participants: int) -> StepResult:
    resp = root / "study/responses"
    html = root / "study/study.html"
    merged = root / "runs/study_b.csv"
    report = root / "runs/study_b_report.json"
    r = StepResult("study_b", BLOCKED)
    files = merge_responses.expand([str(resp)]) if resp.exists() else []
    people = _participants(files)
    html_note = ""
    try:
        cur = build_study.is_current(root / "data/study_v2.db", root / "data/instances.v2.jsonl", html)
        html_note = " study.html is current." if cur else " WARNING: study.html is STALE vs the database."
    except Exception:
        html_note = " (could not check whether study.html is current)"
    if len(people) < min_participants:
        r.detail = f"{len(people)} participants returned, need {min_participants}.{html_note}"
        r.needs = f"collect returned CSVs from {min_participants} participants into study/responses/"
        return r
    warn = f" WARNING: fewer than 12 participants ({len(people)})." if len(people) < 12 else ""
    if dry:
        r.status, r.detail = SKIPPED, f"ready to run on {len(people)} participants.{warn}{html_note}"
        return r
    res = merge_responses.merge([str(resp)], merged, html if html.exists() else None)
    msg = f"{res['ratings']} ratings from {res['participants']} participants"
    if res["duplicates_dropped"]:
        msg += f", {res['duplicates_dropped']} duplicate rows dropped"
    if res["unknown_items"]:
        msg += f", {len(res['unknown_items'])} item ids not in study.html"
    rc, text = _call(analyze.main, ["--study-b", str(merged), "--out", str(report)])
    if rc != 0 or not report.exists():
        return StepResult("study_b", FAILED, f"analyze exited {rc}: {_tail(text)}")
    r.status, r.detail = DONE, f"{msg}.{warn}{html_note}"
    r.outputs = [str(merged.relative_to(root)), str(report.relative_to(root))]
    return r


# --------------------------------------------------------------------- paper


def step_paper(root: Path, dry: bool, mode: str, upstream: list[StepResult]) -> StepResult:
    r = StepResult("paper", SKIPPED)
    if mode == "never":
        r.detail = "--paper never"
        return r
    ran = any(u.status == DONE for u in upstream)
    if mode == "auto" and not ran:
        r.detail = "no upstream step finished, so nothing new for the paper"
        return r
    if dry:
        r.detail = "would run collect then build_paper.js" + ("" if (root / "paper/node_modules/docx").exists()
                                                           else " (node_modules missing: cd paper; npm install)")
        return r
    rc = _collect(root)
    if rc != 0:
        return StepResult("paper", FAILED, f"collect exited {rc}")
    r.outputs = ["paper/numbers.json"]
    if not (root / "paper/node_modules/docx").exists():
        r.status = BLOCKED
        r.detail = "numbers.json updated; the .docx was not rebuilt (paper/node_modules missing)"
        r.needs = "cd paper; npm install; then node paper/build_paper.js"
        return r
    rc, text = _run_node(root)
    if rc != 0:
        return StepResult("paper", FAILED, f"build_paper.js failed: {_tail(text)}")
    r.status, r.detail = DONE, "numbers.json and ClarifyReview_Paper_Draft.docx rebuilt"
    r.outputs.append("paper/ClarifyReview_Paper_Draft.docx")
    return r


# ---------------------------------------------------------------------- main


def run(root: Path = ROOT, *, status_only: bool = False, allow_partial: bool = False,
        min_participants: int = 6, paper: str = "auto",
        labelling_set: str = "swebench") -> list[StepResult]:
    root = Path(root)
    csv.field_size_limit(10**8)
    ls = LABEL_SETS[labelling_set]
    lab = step_labelling(root, status_only, allow_partial, ls)
    trn = step_training(root, status_only, allow_partial, lab, ls)
    if not ls.study_steps:
        why = f"not part of the {ls.name} labelling set"
        return [lab, trn] + [StepResult(n, SKIPPED, why) for n in ("judge", "study_b", "paper")]
    jud = step_judge(root, status_only)
    stb = step_study_b(root, status_only, min_participants)
    pap = step_paper(root, status_only, paper, [lab, trn, jud, stb])
    return [lab, trn, jud, stb, pap]


def render(results: list[StepResult]) -> str:
    out = [f"{'step':<10} {'status':<8} detail", "-" * 78]
    for r in results:
        out.append(f"{r.name:<10} {r.status:<8} {r.detail}")
        for o in r.outputs:
            out.append(f"{'':<19}-> {o}")
    needs = [f"  - {r.name}: {r.needs}" for r in results if r.needs]
    if needs:
        out += ["", "Still needs people:"] + needs
    return "\n".join(out)


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--status", action="store_true", help="print the table; write nothing")
    ap.add_argument("--allow-partial", action="store_true",
                    help="labelling: interim kappa only; no JSONL, no training")
    ap.add_argument("--min-participants", type=int, default=6,
                    help="Study B needs this many distinct participants (default 6; "
                         "a warning is printed below 12)")
    ap.add_argument("--paper", choices=["auto", "always", "never"], default="auto")
    ap.add_argument("--labelling-set", choices=sorted(LABEL_SETS), default="swebench",
                    help="swebench (default, the study's code-only sheet) or realpr "
                         "(runs/realpr/*, its own model and thresholds; judge/study/paper skipped)")
    args = ap.parse_args(argv)
    results = run(root, status_only=args.status, allow_partial=args.allow_partial,
                  min_participants=args.min_participants, paper=args.paper,
                  labelling_set=args.labelling_set)
    print(render(results))
    return 1 if any(r.status == FAILED for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
