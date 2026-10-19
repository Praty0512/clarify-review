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


# ---------------------------------------------------------- v2 prose stripping

from experiments.strip import strip_prose_from_diff, added_prose_lines  # noqa: E402

_Q = '"' * 3
PROSE_PATCH = "\n".join([
    "diff --git a/pkg/mod.py b/pkg/mod.py",
    "--- a/pkg/mod.py",
    "+++ b/pkg/mod.py",
    "@@ -10,2 +10,9 @@ def f(x):",
    "     y = 1",
    "+    # Guard against negative input, which the issue reports crashes downstream.",
    "+    if x < 0:",
    '+        raise ValueError("x must be non-negative")  # see issue 42',
    "+",
    "+    " + _Q,
    "+    Explain the rule at length.",
    "+    " + _Q,
    "     return y",
    "@@ -40,2 +47,3 @@ def g():",
    "     a = 2",
    '+    b = "# not a comment"  # but this is',
    "     return a",
]) + "\n"


def _hunk_counts_are_consistent(diff):
    import re
    for block in re.split(r"(?m)^(?=@@ )", diff)[1:]:
        lines = block.splitlines()
        m = re.match(r"@@ -\d+,(\d+) \+\d+,(\d+) @@", lines[0])
        old_n, new_n = int(m.group(1)), int(m.group(2))
        body = lines[1:]
        old = sum(1 for l in body if not l.startswith("+"))
        new = sum(1 for l in body if not l.startswith("-"))
        if (old, new) != (old_n, new_n):
            return False
    return True


def test_prose_stripping_removes_comments_and_docstrings():
    out = strip_prose_from_diff(PROSE_PATCH)
    assert "Guard against negative input" not in out
    assert "Explain the rule" not in out
    assert "see issue 42" not in out
    assert "but this is" not in out
    assert added_prose_lines(out) == 0


def test_prose_stripping_leaves_every_line_of_code():
    out = strip_prose_from_diff(PROSE_PATCH)
    assert '+    if x < 0:' in out
    assert 'raise ValueError("x must be non-negative")' in out
    # A '#' inside a string literal is code, not a comment.
    assert 'b = "# not a comment"' in out


def test_prose_stripping_keeps_blank_lines():
    out = strip_prose_from_diff(PROSE_PATCH)
    assert "\n+\n" in out


def test_rewritten_hunk_headers_match_their_bodies():
    """A diff whose headers lie is not a diff; a reviewer would see garbage."""
    assert _hunk_counts_are_consistent(strip_prose_from_diff(PROSE_PATCH))


def test_later_hunks_shift_by_the_lines_removed_earlier():
    out = strip_prose_from_diff(PROSE_PATCH)
    second = [l for l in out.splitlines() if l.startswith("@@")][1]
    assert second.startswith("@@ -40,2 +43,3 @@")   # 47 minus the 4 dropped lines


def test_prose_level_strips_and_leaves_the_floor_and_treatment_identical(clear_ctx):
    stripped, _ = strip_context(clear_ctx, level="prose")
    again, _ = strip_context(clear_ctx, level="prose")
    assert stripped.diff == again.diff
    assert is_properly_stripped(stripped, level="prose")


def test_unknown_strip_level_is_refused(clear_ctx):
    with pytest.raises(ValueError):
        strip_context(clear_ctx, level="everything")


def test_hunk_that_starts_inside_an_existing_docstring_keeps_its_code():
    """Regression: found on pylint-dev/pylint-7277 by the runner's own guard. A
    lone closing triple quote at the top of a hunk was read as an opening one,
    and the three lines of code after it were deleted as docstring text."""
    q = '"' * 3
    diff = "\n".join([
        "diff --git a/m.py b/m.py", "--- a/m.py", "+++ b/m.py",
        "@@ -1,4 +1,5 @@ def f():",
        "      explanation from the existing docstring",
        "    " + q,
        "-    old_call()",
        "+    if ready:",
        "+        new_call()",
        "     return 1",
    ]) + "\n"
    out = strip_prose_from_diff(diff)
    assert "+    if ready:" in out and "+        new_call()" in out
    assert _hunk_counts_are_consistent(out)
