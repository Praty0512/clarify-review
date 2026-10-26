"""Regression test: build_judge_context must render findings and ground truth (offline)."""

import json

from experiments.judge import build_judge_context


def _run(review):
    return {"payload": json.dumps({"review": review})}


def _inst(defect):
    return {
        "has_defect": defect,
        "mutation_op": "flip_cmp" if defect else None,
        "mutation_target": "f.py:3" if defect else None,
        "problem_statement": "Fix the off-by-one in pagination.",
    }


REVIEW = {
    "intent_summary": "Fixes pagination bounds",
    "verdict": "request_changes",
    "overall_confidence": 0.7,
    "findings": [
        {"severity": "major", "category": "correctness", "file": "f.py", "line": 3,
         "claim": "comparison looks inverted", "confidence": 0.8},
    ],
}


def test_context_with_findings_and_injected_defect():
    ctx = build_judge_context(_run(REVIEW), _inst(1))
    assert "comparison looks inverted" in ctx
    assert "[major/correctness] f.py:3" in ctx
    assert "A defect WAS injected" in ctx
    assert "flip_cmp" in ctx and "f.py:3" in ctx
    assert "Fix the off-by-one in pagination." in ctx
    assert "Fixes pagination bounds" in ctx and "request_changes" in ctx


def test_context_without_findings_golden():
    review = {**REVIEW, "findings": []}
    ctx = build_judge_context(_run(review), _inst(0))
    assert "(no findings reported)" in ctx
    assert "No defect was injected" in ctx
    assert "WAS injected" not in ctx


def test_context_missing_review():
    ctx = build_judge_context({"payload": json.dumps({})}, _inst(0))
    assert "(no findings reported)" in ctx
