"""Tests for the experiment harness - the parts Study A's validity rests on."""

import numpy as np
import pytest

from experiments.analyze import cohens_kappa, gap_recovery, mcnemar, wilcoxon_paired
from experiments.mutate import OPERATORS, added_lines, candidate_mutants
from experiments.strip import PLACEHOLDER_MESSAGES, is_properly_stripped, strip_context


# ------------------------------------------------------------------ stripping

def test_strip_removes_intent_and_nothing_else(clear_ctx):
    stripped, withheld = strip_context(clear_ctx)
    assert stripped.linked_issue is None
    assert stripped.body == ""
    assert stripped.commit_messages[0] in PLACEHOLDER_MESSAGES
    assert is_properly_stripped(stripped)
    # The one thing that must never change between conditions.
    assert stripped.diff == clear_ctx.diff
    assert [h.body for h in stripped.hunks] == [h.body for h in clear_ctx.hunks]


def test_withheld_text_is_preserved_for_the_oracle(clear_ctx):
    _, withheld = strip_context(clear_ctx)
    assert "trailing dash" in withheld.problem_statement
    assert not withheld.is_empty()


def test_placeholder_is_stable_across_runs(clear_ctx):
    a, _ = strip_context(clear_ctx)
    b, _ = strip_context(clear_ctx)
    assert a.commit_messages == b.commit_messages
    assert a.fingerprint() == b.fingerprint()


def test_stripping_actually_changes_the_context(clear_ctx):
    stripped, _ = strip_context(clear_ctx)
    assert stripped.fingerprint() != clear_ctx.fingerprint()


# ------------------------------------------------------------------- mutation

PATCH = """diff --git a/calc.py b/calc.py
--- a/calc.py
+++ b/calc.py
@@ -1,3 +1,6 @@
 def clamp(value, lo, hi):
+    if value < lo:
+        return lo
+    if value > hi and strict:
+        return hi
     return value
"""


def test_added_lines_are_the_mutation_surface():
    lines = [line for _, line in added_lines(PATCH)]
    assert "    if value < lo:" in lines
    assert "def clamp(value, lo, hi):" not in lines  # context, not added


def test_generates_mutants_across_operators():
    mutants = candidate_mutants(PATCH)
    ops = {m.op for m in mutants}
    assert "invert_comparison" in ops
    assert "swap_boolean_op" in ops
    assert all(m.diff != PATCH for m in mutants)


def test_mutant_diff_is_still_a_valid_diff():
    from clarifyreview.ingest.diff import parse_unified_diff

    for m in candidate_mutants(PATCH):
        hunks = parse_unified_diff(m.diff)
        assert hunks, f"{m.op} produced an unparseable diff"
        assert any(m.mutated_line in h.added for h in hunks)


def test_mutants_start_unverified():
    assert all(not m.verified for m in candidate_mutants(PATCH))


@pytest.mark.parametrize("op,line,expected_change", [
    ("invert_comparison", "    if a == b:", "!="),
    ("negate_condition", "    if ready:", "not"),
    ("swap_boolean_op", "    x = a and b", " or "),
    ("off_by_one", "    n = len(x) + 1", "-"),
    ("drop_guard", "        raise ValueError('no')", "pass"),
    ("flip_constant", "    ok = True", "False"),
])
def test_each_operator_changes_behaviour(op, line, expected_change):
    result = OPERATORS[op](line)
    assert result is not None and expected_change in result and result != line


def test_operators_return_none_when_inapplicable():
    assert OPERATORS["swap_boolean_op"]("    return x") is None
    assert OPERATORS["off_by_one"]("    return x") is None


# ------------------------------------------------------------------ statistics

def test_mcnemar_detects_a_one_sided_improvement():
    floor =     [0]*40 + [1]*10
    treatment = [1]*35 + [0]*5 + [1]*10
    r = mcnemar(floor, treatment)
    assert r.b_only > r.a_only
    assert r.p_value < 0.01
    assert r.difference > 0
    assert r.ci_low > 0


def test_mcnemar_reports_no_effect_when_there_is_none():
    same = [0, 1] * 25
    r = mcnemar(same, list(same))
    assert r.p_value == 1.0
    assert r.difference == 0.0


def test_mcnemar_rejects_unequal_lengths():
    with pytest.raises(ValueError):
        mcnemar([1, 0], [1])


def test_gap_recovery_is_a_fraction_of_the_ceiling():
    floor =     [0]*10          # 0.0
    ceiling =   [1]*10          # 1.0
    treatment = [1]*8 + [0]*2   # 0.8
    r = gap_recovery(floor, treatment, ceiling)
    assert r["gap_recovery"] == pytest.approx(0.8, abs=1e-6)


def test_wilcoxon_reports_effect_size_alongside_p():
    plain =   [2, 3, 2, 3, 2, 3, 2, 3, 2, 3, 2, 3]
    clarify = [4, 5, 4, 4, 5, 4, 5, 4, 4, 5, 4, 5]
    r = wilcoxon_paired(plain, clarify)
    assert r["p_value"] < 0.01
    assert r["effect_size_r"] > 0.9
    assert r["median_difference"] > 0


def test_wilcoxon_handles_all_ties():
    r = wilcoxon_paired([3, 3, 3], [3, 3, 3])
    assert r["p_value"] == 1.0
    assert r["effect_size_r"] == 0.0


def test_cohens_kappa_matches_known_values():
    assert cohens_kappa([1, 1, 0, 0], [1, 1, 0, 0]) == 1.0
    # Chance-level agreement on a balanced set is ~0.
    assert abs(cohens_kappa([1, 0, 1, 0], [1, 1, 0, 0])) < 1e-9
