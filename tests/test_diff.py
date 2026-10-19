from clarifyreview.ingest.diff import (
    changed_line_ranges,
    parse_unified_diff,
    reconstruct_sides,
    split_by_file,
)
from tests.conftest import AMBIGUOUS_DIFF, CLEAR_DIFF


def test_parses_hunks_and_attributes_files():
    hunks = parse_unified_diff(CLEAR_DIFF)
    assert len(hunks) == 2
    assert sorted(h.file for h in hunks) == ["app/util.py", "tests/test_util.py"]


def test_counts_added_and_removed():
    hunk = parse_unified_diff(AMBIGUOUS_DIFF)[0]
    assert hunk.removed == ['    if user.email is None:',
                            '        raise ValueError("email is required")',
                            '']
    assert hunk.added == []
    assert hunk.net_lines == -3


def test_hunk_line_ranges():
    hunks = parse_unified_diff(AMBIGUOUS_DIFF)
    assert changed_line_ranges(hunks, "app/auth.py") == [(10, 15)]


def test_split_by_file():
    by_file = split_by_file(parse_unified_diff(CLEAR_DIFF))
    assert set(by_file) == {"app/util.py", "tests/test_util.py"}


def test_reconstruct_sides_keeps_context_on_both():
    pre, post = reconstruct_sides(parse_unified_diff(AMBIGUOUS_DIFF))
    assert "raise ValueError" in pre
    assert "raise ValueError" not in post
    assert "def validate_user(user):" in pre and "def validate_user(user):" in post


def test_empty_diff_is_not_an_error():
    assert parse_unified_diff("") == []
