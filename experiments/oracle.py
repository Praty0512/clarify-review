"""The simulated developer, deliberately kept ignorant.

This is the single largest threat to Study A's validity. An oracle that can see
the diff and knows what the study is testing will volunteer "note that line 42
looks wrong", ClarifyReview will look brilliant, and the result will be oracle
leakage rather than an effect. So the oracle is bounded three ways:

  1. Its context is the withheld text only - the issue statement, the original
     commit message, the PR body. It never sees the diff, the mutation, or
     whether the patch under review is the golden one or a mutant.
  2. Its system prompt forbids volunteering, speculating, or reviewing.
  3. Every exchange is logged verbatim, so leakage can be audited afterwards.
     `audit_sample` pulls a random sample for the hand-check that Study A reports.

If the oracle cannot answer from what it was given, it says so. A refusal is a
valid outcome and gets recorded as one - a made-up answer is far worse than none.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from clarifyreview.config import oracle_model
from clarifyreview.types import ClarifyingQuestions, PRContext

from .strip import Withheld

SYSTEM = """\
You are standing in for the author of a pull request, answering a reviewer's \
question about it.

You know only what is written in the AUTHOR'S NOTES below. You have not been shown \
the code. You are not reviewing anything.

Answer the question that was asked, in one or two sentences, using only what the \
notes contain. Speak in the first person, the way a developer answers a reviewer.

The reviewer can see the code and you cannot, so questions will often be phrased \
around code ("are you intentionally removing X?", "is the goal of this change Y?"). \
Those are questions about intent, and the notes are a statement of intent: answer \
them by saying what problem you were fixing and what behaviour you wanted, as the \
notes describe it. You do not need to have seen the code to say what it was for.

Hard rules:
- Do not mention specific line numbers, function bodies, or code you were not told \
  about. You have not seen the diff.
- Do not point out bugs, risks, or things the reviewer should check. That is the \
  reviewer's job, not yours.
- Do not volunteer anything beyond what the question asks.
- Only if the notes say nothing about the intent being asked about, say exactly: "I'm not sure, I don't have \
  that context to hand." Do not guess, and do not fill the gap with a plausible \
  reason.\
"""


ORACLE_MAX_TOKENS = 4000

# Bumped whenever SYSTEM changes, and logged with every exchange, so an audit can
# tell which wording produced which answer.
#   v1  original; refused any question phrased around code (2 of 6 refused)
#   v2  answers intent questions from the notes; refusal only when the notes are
#       silent on the intent asked about
PROMPT_VERSION = "v2"


class Oracle:
    """Answers clarifying questions from the withheld text and nothing else."""

    def __init__(self, llm=None, model: str | None = None, log_path: Path | None = None):
        self._llm = llm
        self._model = model
        self.log_path = log_path or Path("runs/oracle_log.jsonl")
        self.cost_usd = 0.0

    @property
    def model(self) -> str:
        return self._model or oracle_model()

    @property
    def llm(self):
        if self._llm is None:
            from clarifyreview.llm.client import LLM

            self._llm = LLM()
        return self._llm

    def answer(
        self, pr_id: str, questions: ClarifyingQuestions, withheld: Withheld
    ) -> str | None:
        if withheld.is_empty():
            self._log(pr_id, questions, None, "no withheld context to answer from")
            return None

        notes = self._notes(withheld)
        asked = "\n".join(
            f"{i + 1}. [{q.target}] {q.question}"
            for i, q in enumerate(questions.questions)
        )
        result = self.llm.text(
            model=self.model,
            system=SYSTEM,
            cached_context=f"AUTHOR'S NOTES\n{notes}",
            instruction=f"The reviewer asks:\n{asked}\n\nAnswer as the author.",
            # Generous on purpose. Gemma reasons internally whether or not
            # thinking is requested, and those hidden tokens count against this
            # limit: at 400 every answer was truncated to an empty string before
            # a word of it was written, which silently turned the treatment
            # condition into a second floor.
            max_tokens=ORACLE_MAX_TOKENS,
            thinking=False,
        )
        self.cost_usd += result.usage.cost_usd
        answer = result.value.strip()
        self._log(pr_id, questions, answer, None if answer else "empty response")
        return answer or None

    @staticmethod
    def _notes(withheld: Withheld) -> str:
        parts = []
        if withheld.issue_title:
            parts.append(f"Issue title: {withheld.issue_title}")
        if withheld.problem_statement.strip():
            parts.append(f"Issue description:\n{withheld.problem_statement.strip()}")
        if withheld.pr_body.strip():
            parts.append(f"What I wrote on the PR:\n{withheld.pr_body.strip()}")
        if withheld.commit_messages:
            joined = "\n".join(f"- {m}" for m in withheld.commit_messages)
            parts.append(f"My commit messages:\n{joined}")
        return "\n\n".join(parts)

    def _log(self, pr_id: str, questions: ClarifyingQuestions, answer, note) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "pr_id": pr_id,
                        "questions": [q.model_dump() for q in questions.questions],
                        "answer": answer,
                        "note": note,
                        "prompt_version": PROMPT_VERSION,
                        "model": self.model,
                    },
                    sort_keys=True,
                )
                + "\n"
            )


class OracleResponder:
    """Adapts the oracle to the `Responder` protocol the clarification loop uses.

    This is why Study A and the GitHub bot run the same Stage 3 code: swapping
    `GitHubResponder` for this one is the entire difference between production and
    the benchmark.
    """

    name = "oracle"

    def __init__(self, oracle: Oracle, withheld: Withheld) -> None:
        self.oracle = oracle
        self.withheld = withheld

    def ask(self, ctx: PRContext, questions: ClarifyingQuestions) -> str | None:
        return self.oracle.answer(ctx.pr_id, questions, self.withheld)


# ------------------------------------------------------------------- audit


LEAK_MARKERS = (
    "line ",
    "should check",
    "you should",
    "might want to",
    "there's a bug",
    "looks wrong",
    "be careful",
    "note that",
)


def audit_sample(log_path: Path, n: int = 20, seed: int = 20260831) -> list[dict]:
    """Pull a random sample of exchanges for the hand-check Study A reports.

    `suspected_leak` is a coarse keyword flag, not a verdict. It exists to bias
    the sample toward exchanges worth reading closely; the reported number comes
    from two people reading them, not from this heuristic.
    """
    if not log_path.exists():
        return []
    rows = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    rng = random.Random(seed)
    sample = rng.sample(rows, min(n, len(rows)))
    for row in sample:
        answer = (row.get("answer") or "").lower()
        row["suspected_leak"] = any(m in answer for m in LEAK_MARKERS)
    return sample


def exchange_summary(log_path: Path) -> dict:
    """Outcome counts per prompt version: answered, refused, empty.

    Entries written before versioning was added carry no `prompt_version` and
    are counted as v1, which is what produced them.
    """
    if not log_path.exists():
        return {}
    out: dict[str, dict[str, int]] = {}
    for line in log_path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        bucket = out.setdefault(row.get("prompt_version", "v1"),
                                {"exchanges": 0, "answered": 0, "refused": 0, "empty": 0})
        bucket["exchanges"] += 1
        answer = (row.get("answer") or "").strip()
        if not answer:
            bucket["empty"] += 1
        elif answer.startswith("I'm not sure"):
            bucket["refused"] += 1
        else:
            bucket["answered"] += 1
    return out


def write_audit_sheet(log_path: Path, out: Path, n: int = 20,
                      prompt_version: str | None = PROMPT_VERSION,
                      seed: int = 20260831) -> int:
    """Write the leakage hand-check as a CSV for both team members to fill.

    Only substantive answers are sampled: an empty reply or a refusal cannot
    leak, so including them would only dilute the check. Each scorer marks
    `leak_<name>` 1 when the answer mentions code, lines, bugs or anything the
    author's notes did not contain, and agreement is computed with
    `experiments.label_tool agree`-style kappa afterwards.
    """
    import csv

    if not log_path.exists():
        return 0
    rows = []
    for line in log_path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if prompt_version and row.get("prompt_version", "v1") != prompt_version:
            continue
        answer = (row.get("answer") or "").strip()
        if answer and not answer.startswith("I'm not sure"):
            rows.append(row)

    rng = random.Random(seed)
    sample = rng.sample(rows, min(n, len(rows)))
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "pr_id", "prompt_version", "questions", "answer", "suspected_leak",
            "leak_scorer_1", "leak_scorer_2", "notes"])
        w.writeheader()
        for row in sample:
            answer = row["answer"].strip()
            w.writerow({
                "pr_id": row["pr_id"],
                "prompt_version": row.get("prompt_version", "v1"),
                "questions": " | ".join(q.get("question", "") for q in row.get("questions", [])),
                "answer": answer,
                "suspected_leak": int(any(m in answer.lower() for m in LEAK_MARKERS)),
                "leak_scorer_1": "", "leak_scorer_2": "", "notes": "",
            })
    return len(sample)


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Audit the simulated author for leakage")
    ap.add_argument("--log", default="runs/oracle_log.jsonl")
    ap.add_argument("--summary", action="store_true",
                    help="print answered/refused/empty counts per prompt version")
    ap.add_argument("--audit", type=int, default=0, metavar="N",
                    help="write a hand-check sheet of N substantive answers")
    ap.add_argument("--prompt-version", default=PROMPT_VERSION,
                    help="sample only this prompt version; 'all' for every version")
    ap.add_argument("--out", default="runs/oracle_audit.csv")
    args = ap.parse_args(argv)

    log_path = Path(args.log)
    if args.summary or not args.audit:
        print(json.dumps(exchange_summary(log_path), indent=2))
    if args.audit:
        version = None if args.prompt_version == "all" else args.prompt_version
        k = write_audit_sheet(log_path, Path(args.out), args.audit, version)
        print(f"wrote {k} exchanges to {args.out}")
        print("Both team members fill leak_scorer_1 / leak_scorer_2 independently "
              "(1 = the answer goes beyond the author's notes).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
