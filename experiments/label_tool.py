"""Human labelling for the classifier detector, and agreement for any two raters.

  sheet   write a labelling sheet of real SWE-bench PRs, shown as the detector
          sees them in the study: code change only, no issue, no description,
          comments and docstrings removed. Each annotator fills their column
          with 1 (intent unclear - a reviewer should ask) or 0 (clear enough).

  split   write one file per annotator (own column only), so neither sees the
          other's labels. `page` turns each into a self-contained HTML labeller.

  combine copy the two returned annotator files back into the master sheet.
          Never fills a blank it was not given; refuses conflicting values.

  agree   Cohen's kappa between any two columns of a CSV, plus the confusion
          table. With --to-jsonl, rows both annotators agree on (or that have an
          `adjudicated` value) become the classifier's training file. The diff
          comes from the sheet itself (offline) unless --diff-source swebench.

Used for the 300-PR labelling pass that trains detector (b).

A sheet built by `experiments.fetch_prs` (real merged PRs; has a `view` column) goes
through the same commands: split passes the title, description, issue and commit
columns through, page shows them above the diff with the full-context codebook, and
agree --diff-source cache --cache-dir data/cache/realpr writes them to the JSONL.
Code-only and full-context labels are never merged (split refuses a mixed sheet).

    python -m experiments.label_tool split runs/labelling_sheet.csv --out-dir runs/labelling
    python -m experiments.label_tool page --out-dir runs/labelling
    python -m experiments.label_tool combine runs/labelling_sheet.csv \\
        runs/labelling/annotator_1.csv runs/labelling/annotator_2.csv
    python -m experiments.label_tool agree runs/labelling_sheet.csv \\
        --a annotator_1 --b annotator_2 --to-jsonl data/labelled_prs.jsonl \\
        --report-json runs/labelling_agreement.json

(Judge-vs-human agreement is a different command:
    python -m experiments.analyze --judge-agreement ...)
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import random
import re
import sys
from pathlib import Path

csv.field_size_limit(10**8)

CODEBOOK = """\
CODEBOOK - label each pull request 1 or 0, independently, without discussing.
You see only the code change. There is no issue text and no description.

1 = UNCLEAR. A careful reviewer would need to ask the author before judging
    whether this change is correct. Typical signs: it removes or weakens a check,
    changes behaviour with no visible reason, could plausibly be either a fix or a
    regression, or alters a public interface without saying why.
0 = CLEAR. The purpose can be read off the code itself with reasonable
    confidence, even if you would still have review comments about it.

Label the INTENT, not the quality. A clear change can still be wrong.
When genuinely torn, choose 1 and say why in your notes column.
"""

CODEBOOK_FULL = """CODEBOOK - label each pull request 1 or 0, independently, without discussing.
You see what a reviewer sees when the PR is opened: title, description, linked
issue, commit messages and the diff.

1 = UNCLEAR. After reading all of it, a careful reviewer would still need to ask
    the author about intent before judging correctness. Signs: the stated purpose
    does not explain a behaviour change in the diff; the description and the code
    disagree; a check is removed or weakened with no stated reason; it could be a
    fix or a regression and nothing says which; a public interface changes
    without saying why.
0 = CLEAR. The purpose is stated or evident and the code is consistent with it.

Label intent, not quality. A long description that does not explain the risky
part is still 1. A missing description alone is not 1 if the code explains
itself. Do NOT open the PR on GitHub: the review discussion is the clarification
the bot is meant to replace. Ignore author identity and merge status.
When genuinely torn, choose 1 and say why in your notes column.
"""

HUMAN_COLS = ("annotator_1", "annotator_2", "adjudicated", "notes")
MASTER_ONLY_COLS = ("url", "merged_at")
FULL_VIEW = "full_context"          # also matches full_context_opened


def _view_of(rows: list[dict]) -> str:
    """"" for a code-only sheet, else the single `view` value. Mixed views are an error."""
    views = {(r.get("view") or "").strip() for r in rows}
    if len(views) > 1:
        raise ValueError(f"sheet mixes views {sorted(views)}; code-only and full-context "
                         "labels must never be merged")
    return views.pop() if views else ""


def codebook_for(rows: list[dict]) -> str:
    return CODEBOOK_FULL if _view_of(rows).startswith(FULL_VIEW) else CODEBOOK


# ----------------------------------------------------------------- csv helpers


def _read_rows(path) -> list[dict]:
    """Read a CSV that may have come back through Excel: BOM, or cp1252 not utf-8."""
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    return list(csv.DictReader(io.StringIO(text, newline="")))


_TRUE = {"1", "1.0", "1.00", "true", "yes", "y", "t"}
_FALSE = {"0", "0.0", "0.00", "false", "no", "n", "f"}


def _norm(v) -> str:
    """Normalise a label cell: "1.0"/"TRUE"/"yes" -> "1", "0.0"/"FALSE" -> "0", blank -> ""."""
    t = str(v if v is not None else "").strip().lower()
    if t in _TRUE:
        return "1"
    if t in _FALSE:
        return "0"
    return t


def _write_rows(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _has_human_cells(path: Path, cols: list[str]) -> bool:
    if not path.exists():
        return False
    return any(str(r.get(c) or "").strip() for r in _read_rows(path) for c in cols)


# ------------------------------------------------------------------- commands


def cmd_sheet(args) -> int:
    from datasets import load_dataset

    from .strip import strip_prose_from_diff

    exclude = set()
    for f in args.exclude:
        if Path(f).exists():
            exclude |= {json.loads(l)["pr_id"].split("::")[0]
                        for l in Path(f).read_text().splitlines() if l.strip()}
    rows = [dict(r) for r in load_dataset("princeton-nlp/SWE-bench_Verified", split="test")
            if r["instance_id"] not in exclude]
    rng = random.Random(args.seed)
    rng.shuffle(rows)
    rows = rows[: args.n]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["pr_id", "repo", "code_change", "annotator_1", "annotator_2",
                    "adjudicated", "notes"])
        for r in rows:
            w.writerow([r["instance_id"], r["repo"],
                        strip_prose_from_diff(r["patch"])[:30000], "", "", "", ""])
    Path(out.with_suffix(".codebook.txt")).write_text(CODEBOOK)
    print(f"wrote {len(rows)} PRs to {out}\ncodebook: {out.with_suffix('.codebook.txt')}")
    print(f"excluded {len(exclude)} instances used in the ablation")
    return 0


def cmd_split(args) -> int:
    rows = _read_rows(args.sheet)
    try:
        codebook = codebook_for(rows)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    out_dir = Path(args.out_dir)
    targets = {n: out_dir / f"annotator_{n}.csv" for n in (1, 2)}
    for n, path in targets.items():
        if _has_human_cells(path, [f"annotator_{n}", "notes"]):
            print(f"refusing to overwrite {path}: it already contains labels or notes",
                  file=sys.stderr)
            return 2
    # Every sheet column except the human ones passes through (a code-only sheet
    # therefore still yields exactly pr_id, repo, code_change, annotator_N, notes).
    # url and merged_at stay in the master only: the codebook forbids opening the PR
    # and merge status must not influence a label.
    base = [c for c in (list(rows[0].keys()) if rows else ["pr_id", "repo", "code_change"])
            if c not in HUMAN_COLS and c not in MASTER_ONLY_COLS]
    for n, path in targets.items():
        col = f"annotator_{n}"
        _write_rows(path, base + [col, "notes"],
                    [{**{c: r.get(c, "") for c in base}, col: "", "notes": ""} for r in rows])
    (out_dir / "codebook.txt").write_text(codebook, encoding="utf-8")
    print(f"wrote {len(rows)} PRs each to {targets[1]} and {targets[2]} (+ codebook.txt)")
    return 0


def cmd_combine(args) -> int:
    sheet = Path(args.sheet)
    rows = _read_rows(sheet)
    by_id = {r["pr_id"]: r for r in rows}
    fields = list(rows[0].keys()) if rows else []
    problems: list[str] = []
    updates: list[tuple[dict, str, str, str, str]] = []   # row, column, value, note, tag
    for path in args.files:
        part = _read_rows(path)
        header = list(part[0].keys()) if part else []
        cols = [c for c in header if c in ("annotator_1", "annotator_2")]
        if len(cols) != 1:
            problems.append(f"{path}: expected exactly one annotator_1/annotator_2 column")
            continue
        col = cols[0]
        tag = f"[a{col[-1]}]"
        for r in part:
            row = by_id.get(r["pr_id"])
            if row is None:
                problems.append(f"{path}: unknown pr_id {r['pr_id']}")
                continue
            val = _norm(r.get(col, ""))
            if val not in ("", "0", "1"):
                problems.append(f"{path}: {r['pr_id']} has non-binary value {val!r}")
                continue
            have = _norm(row.get(col, ""))
            if val and have and have != val:
                problems.append(f"{path}: {r['pr_id']} conflicts with the master "
                                f"({col}: master {have}, file {val})")
                continue
            updates.append((row, col, val, (r.get("notes") or "").strip(), tag))
    if problems:
        print("combine aborted, nothing written:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 2
    changed = 0
    for row, col, val, note, tag in updates:
        if val and not _norm(row.get(col, "")):
            row[col] = val
            changed += 1
        if note:
            line = f"{tag} {note}"
            old = row.get("notes") or ""
            if line not in old:
                row["notes"] = f"{old} | {line}" if old else line
    _write_rows(sheet, fields, rows)
    print(f"combined {len(args.files)} files into {sheet}: {changed} labels copied")
    return 0


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Labelling - annotator /*N*/</title>
<style>
:root{--ink:#16181D;--muted:#5C6270;--line:#D7DBE2;--bg:#F4F5F7;--card:#FFF;--acc:#1F3864}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.55 Georgia,"Times New Roman",serif;padding:0 16px 60px}
main{max-width:980px;margin:0 auto}h1{font:700 24px/1.2 Arial,sans-serif;margin:28px 0 6px}
.muted{color:var(--muted)}.card{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:14px 18px;margin:14px 0}
pre{background:#1A1D23;color:#E3E6EC;padding:12px;border-radius:5px;overflow:auto;font-size:12.5px;line-height:1.5;max-height:65vh}
button{font:600 15px Arial,sans-serif;background:var(--acc);color:#fff;border:0;border-radius:5px;padding:10px 18px;margin:4px 6px 4px 0;cursor:pointer}
button.alt{background:#fff;color:var(--acc);border:1px solid var(--acc)}
button:focus-visible,textarea:focus-visible{outline:2px solid #A96C12;outline-offset:2px}
textarea{width:100%;min-height:50px;font:inherit}.sel{box-shadow:0 0 0 3px #A96C12}
pre.codebook{max-height:none;white-space:pre-wrap}
</style></head><body><main>
<h1>Labelling - annotator /*N*/</h1>
<details class="card"><summary>Codebook (read first)</summary><pre class="codebook" id="cb"></pre></details>
<div class="card"><span id="pos"></span> <span class="muted" id="repo"></span>
<span class="muted"> &middot; keys: 1 = unclear, 0 = clear, arrows = move</span></div>
<pre id="diff"></pre>
<div class="card">
<button id="b1">1 - UNCLEAR (ask)</button><button id="b0">0 - CLEAR</button>
<button class="alt" id="prev">Prev</button><button class="alt" id="next">Next</button>
<button class="alt" id="skip">Next unlabelled</button>
<p><label>Notes (say why if torn)<br><textarea id="notes"></textarea></label></p>
</div>
<div class="card"><span id="count"></span>
<button id="dl">Download my labels (CSV)</button>
<span class="muted">Progress is saved in this browser automatically. Send the downloaded file back unchanged.</span></div>
<script>
const COL="annotator_/*N*/", KEY="cr_label_/*N*/", ITEMS=/*ITEMS*/[], CODEBOOK=/*CODEBOOK*/"";
document.getElementById("cb").textContent=CODEBOOK;
let st={};try{st=JSON.parse(localStorage.getItem(KEY)||"{}")}catch(e){}
let i=0;const $=id=>document.getElementById(id);
const save=()=>{try{localStorage.setItem(KEY,JSON.stringify(st))}catch(e){}};
function cur(){return st[ITEMS[i].pr_id]||(st[ITEMS[i].pr_id]={label:"",notes:""})}
function show(){
  const it=ITEMS[i],c=cur();
  $("pos").textContent=`${i+1} / ${ITEMS.length}  ${it.pr_id}`;$("repo").textContent=it.repo;
  $("diff").textContent=it.code_change;$("notes").value=c.notes;
  $("b1").classList.toggle("sel",c.label==="1");$("b0").classList.toggle("sel",c.label==="0");
  const done=ITEMS.filter(x=>st[x.pr_id]&&st[x.pr_id].label!=="").length;
  $("count").textContent=`${done} of ${ITEMS.length} labelled. `;
}
function setLabel(v){cur().label=v;save();show()}
function go(d){if(i+d>=0&&i+d<ITEMS.length){i+=d;show();window.scrollTo(0,0)}}
$("b1").onclick=()=>setLabel("1");$("b0").onclick=()=>setLabel("0");
$("prev").onclick=()=>go(-1);$("next").onclick=()=>go(1);
$("skip").onclick=()=>{for(let k=1;k<=ITEMS.length;k++){const j=(i+k)%ITEMS.length;
  if(!(st[ITEMS[j].pr_id]&&st[ITEMS[j].pr_id].label!=="")){i=j;show();return}}};
$("notes").oninput=e=>{cur().notes=e.target.value;save()};
document.addEventListener("keydown",e=>{if(e.target.tagName==="TEXTAREA")return;
  if(e.key==="1")setLabel("1");else if(e.key==="0")setLabel("0");
  else if(e.key==="ArrowRight")go(1);else if(e.key==="ArrowLeft")go(-1)});
const q=s=>'"'+String(s).replace(/"/g,'""')+'"';
$("dl").onclick=()=>{
  const lines=["pr_id,"+COL+",notes"];
  for(const it of ITEMS){const c=st[it.pr_id]||{label:"",notes:""};lines.push([q(it.pr_id),c.label,q(c.notes)].join(","))}
  const b=new Blob(["\ufeff"+lines.join("\r\n")+"\r\n"],{type:"text/csv"}),a=document.createElement("a");
  a.href=URL.createObjectURL(b);a.download=COL+"_labels.csv";a.click()};
show();
</script></main></body></html>
"""


def _js(obj) -> str:
    """JSON that is safe inside a <script> block."""
    return (json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


_FULL_CSS = """
#ctx .card pre{max-height:30vh;white-space:pre-wrap;background:#fff;color:var(--ink);border:1px solid var(--line)}
#ctx strong{font:700 14px Arial,sans-serif}
"""
_FULL_JS = r"""function renderCtx(it){const box=$("ctx");box.textContent="";
 const add=(h,t,empty)=>{const d=document.createElement("div");d.className="card";
  const hd=document.createElement("strong");hd.textContent=h;d.appendChild(hd);
  const has=t&&String(t).trim();const b=document.createElement("pre");
  b.textContent=has?t:empty;if(!has)b.className="muted";d.appendChild(b);box.appendChild(d)};
 add("Title",it.title,"(no title)");add("Description",it.body,"(no description)");
 if(it.issue_title||it.issue_body)add("Linked issue #"+(it.issue_number||"")+": "+(it.issue_title||""),it.issue_body,"(empty)");
 let cm=[];try{cm=JSON.parse(it.commit_messages||"[]")}catch(e){}
 add("Commit messages",cm.join("\n---\n"),"(none)")}
"""


def _page_html(n: int, items: list[dict], codebook: str, full: bool) -> str:
    page = PAGE
    if full:
        for anchor, repl in [
            ("</style>", _FULL_CSS + "</style>"),
            ('<pre id="diff"></pre>', '<div id="ctx"></div>\n<pre id="diff"></pre>'),
            ('KEY="cr_label_/*N*/"', 'KEY="cr_label_full_/*N*/"'),
            ("function show(){", _FULL_JS + "function show(){"),
            ('$("diff").textContent=it.code_change;', '$("diff").textContent=it.code_change;renderCtx(it);'),
        ]:
            assert page.count(anchor) == 1, anchor
            page = page.replace(anchor, repl)
    return (page.replace("/*N*/", str(n)).replace("/*ITEMS*/[]", _js(items))
            .replace('/*CODEBOOK*/""', _js(codebook)))


_CONTEXT_FIELDS = ("title", "body", "issue_number", "issue_title", "issue_body", "commit_messages")


def cmd_page(args) -> int:
    out_dir = Path(args.out_dir)
    made = 0
    for n in (1, 2):
        src = out_dir / f"annotator_{n}.csv"
        if not src.exists():
            print(f"skipping annotator {n}: {src} not found (run `split` first)")
            continue
        rows = _read_rows(src)
        try:
            codebook = codebook_for(rows)
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 2
        full = codebook is CODEBOOK_FULL
        items = [{"pr_id": r["pr_id"], "repo": r.get("repo", ""), "code_change": r["code_change"],
                  **({k: r.get(k, "") for k in _CONTEXT_FIELDS} if full else {})}
                 for r in rows]
        dest = out_dir / f"annotator_{n}.html"
        dest.write_text(_page_html(n, items, codebook, full), encoding="utf-8")
        print(f"wrote {dest} ({len(items)} PRs)")
        made += 1
    return 0 if made else 1


def kappa(a: list[str], b: list[str]) -> tuple[float, dict]:
    pairs = [(x, y) for x, y in zip(a, b) if x != "" and y != ""]
    n = len(pairs)
    if n == 0:
        return float("nan"), {}
    cats = sorted({x for x, _ in pairs} | {y for _, y in pairs})
    table = {(x, y): sum(1 for p in pairs if p == (x, y)) for x in cats for y in cats}
    po = sum(table[(c, c)] for c in cats) / n
    pe = sum((sum(1 for x, _ in pairs if x == c) / n) * (sum(1 for _, y in pairs if y == c) / n)
             for c in cats)
    k = 1.0 if pe == 1 else (po - pe) / (1 - pe)
    return k, {"n": n, "observed_agreement": round(po, 4), "kappa": round(k, 4),
               "table": {f"{x}|{y}": v for (x, y), v in table.items()}}


def interpret(k: float) -> str:
    # Landis and Koch (1977), the conventional reading of kappa.
    for bound, word in [(0.0, "poor"), (0.2, "slight"), (0.4, "fair"), (0.6, "moderate"),
                        (0.8, "substantial"), (1.01, "almost perfect")]:
        if k < bound:
            return word
    return "almost perfect"


_PR_ID = re.compile(r"^(.+?)/(.+?)#(\d+)$")


def _cached_diff(cache_root: Path, row: dict) -> str:
    """The full diff fetch_prs cached for a real-PR row ("" when not cached)."""
    m = _PR_ID.match(row.get("pr_id", ""))
    if not m:
        return ""
    suffix = "_opened" if (row.get("view") or "").endswith("_opened") else ""
    f = cache_root / f"{m.group(1)}__{m.group(2)}" / f"full_{m.group(3)}{suffix}.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")).get("diff") or ""
    except (OSError, ValueError):
        return ""


def _context_fields(r: dict) -> dict:
    try:
        commits = json.loads(r.get("commit_messages") or "[]")
    except ValueError:
        commits = []
    num = (r.get("issue_number") or "").strip()
    return {"title": r.get("title", ""), "body": r.get("body", ""),
            "commit_messages": commits if isinstance(commits, list) else [],
            "issue_number": int(num) if num.isdigit() else 0,
            "issue_title": r.get("issue_title", ""), "issue_body": r.get("issue_body", ""),
            "view": r.get("view", "")}


def cmd_agree(args) -> int:
    rows = _read_rows(args.csv)
    a = [_norm(r.get(args.a, "")) for r in rows]
    b = [_norm(r.get(args.b, "")) for r in rows]
    k, info = kappa(a, b)
    if not info:
        print("no rows have both columns filled")
        return 1
    print(json.dumps(info, indent=2))
    print(f"Cohen's kappa = {k:.3f} ({interpret(k)} agreement, n={info['n']})")

    adj = [_norm(r.get("adjudicated", "")) for r in rows]
    both = [i for i, (x, y) in enumerate(zip(a, b)) if x != "" and y != ""]
    disagree = [i for i in both if a[i] != b[i]]
    n_written = 0

    if args.to_jsonl:
        patches: dict[str, str] = {}
        cache_root = Path(args.cache_dir)
        if args.diff_source == "swebench":
            try:
                from datasets import load_dataset
            except ImportError:
                print("the `datasets` package is not installed: pip install -e .[bench]",
                      file=sys.stderr)
                return 1
            patches = {r["instance_id"]: r["patch"]
                       for r in load_dataset("princeton-nlp/SWE-bench_Verified", split="test")}
        Path(args.to_jsonl).parent.mkdir(parents=True, exist_ok=True)
        n_no_diff = 0
        with open(args.to_jsonl, "w", encoding="utf-8") as fh:
            for r, x, y, d in zip(rows, a, b, adj):
                label = d if d in ("0", "1") else (x if x == y and x in ("0", "1") else None)
                if label is None:
                    continue
                if args.diff_source == "sheet":
                    diff = r.get("code_change", "")
                elif args.diff_source == "cache":
                    diff = _cached_diff(cache_root, r)
                else:
                    diff = patches.get(r["pr_id"])
                if not diff:
                    n_no_diff += 1
                    continue
                rec = {"pr_id": r["pr_id"], "repo": r.get("repo", ""),
                       "diff": diff, "title": "", "body": "",
                       "commit_messages": [], "issue_body": "", "label": int(label),
                       "diff_source": args.diff_source}
                if (r.get("view") or "").startswith(FULL_VIEW):
                    rec.update(_context_fields(r))
                fh.write(json.dumps(rec) + "\n")
                n_written += 1
        print(f"wrote {n_written} labelled PRs to {args.to_jsonl} "
              f"(agreed or adjudicated; disagreements without adjudication dropped; "
              f"diffs from {args.diff_source})")
        if n_no_diff:
            print(f"{n_no_diff} labelled rows dropped: no diff from {args.diff_source}")

    if args.report_json:
        report = {
            **info, "reading": interpret(k), "n_rows": len(rows),
            "n_agreed": len(both) - len(disagree), "n_disagree": len(disagree),
            "n_adjudicated": sum(1 for d in adj if d in ("0", "1")),
            "n_disagree_unadjudicated": sum(1 for i in disagree if adj[i] not in ("0", "1")),
            "n_written": n_written, "diff_source": args.diff_source,
        }
        Path(args.report_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report_json).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"wrote report to {args.report_json}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sheet")
    s.add_argument("--n", type=int, default=300)
    s.add_argument("--out", default="runs/labelling_sheet.csv")
    s.add_argument("--seed", type=int, default=20261019)
    s.add_argument("--exclude", nargs="*",
                   default=["data/instances.v2.jsonl", "data/archive/instances.pilot.jsonl"])
    s.set_defaults(func=cmd_sheet)
    sp = sub.add_parser("split")
    sp.add_argument("sheet")
    sp.add_argument("--out-dir", default="runs/labelling")
    sp.set_defaults(func=cmd_split)
    cb = sub.add_parser("combine")
    cb.add_argument("sheet")
    cb.add_argument("files", nargs="+")
    cb.set_defaults(func=cmd_combine)
    pg = sub.add_parser("page")
    pg.add_argument("--out-dir", default="runs/labelling")
    pg.set_defaults(func=cmd_page)
    g = sub.add_parser("agree")
    g.add_argument("csv")
    g.add_argument("--a", required=True)
    g.add_argument("--b", required=True)
    g.add_argument("--to-jsonl")
    g.add_argument("--diff-source", choices=["sheet", "swebench", "cache"], default="sheet",
                   help="sheet: the diff the annotators saw (offline, default); "
                        "swebench: the full original patch (needs `datasets`); "
                        "cache: the full diff fetch_prs cached (real-PR sheets)")
    g.add_argument("--cache-dir", default="data/cache/realpr",
                   help="fetch_prs cache, used with --diff-source cache")
    g.add_argument("--report-json")
    g.set_defaults(func=cmd_agree)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
