from clarifyreview.ingest.semantic import PythonAstExtractor, changed_symbols
from clarifyreview.ingest.diff import parse_unified_diff
from tests.conftest import AMBIGUOUS_DIFF

SOURCE = '''
class Session:
    def get(self, url, **kwargs):
        return self._send(url, **kwargs)

def validate_user(user, strict=False):
    return user.id
'''


def test_extracts_functions_classes_and_methods():
    syms = {s.name: s for s in PythonAstExtractor().symbols(SOURCE)}
    assert syms["Session"].kind == "class"
    assert syms["Session.get"].kind == "method"
    assert syms["validate_user"].kind == "function"
    assert syms["validate_user"].signature == "(user, strict)"


def test_underscore_prefix_is_private():
    syms = {s.name: s for s in PythonAstExtractor().symbols("def _hidden():\n    pass\n")}
    assert not syms["_hidden"].is_public


def test_unparseable_source_returns_nothing_rather_than_raising():
    assert PythonAstExtractor().symbols("def broken(:\n") == []


def test_maps_hunks_onto_symbols():
    """Images must be line-aligned with the real file, not local to themselves.

    The hunk lives at line 10, so a symbol at line 1 of a hand-built image will
    never overlap it. Padding to the real line numbers is the contract
    `reconstruct_sides` upholds, and this asserts the extractor depends on it.
    """
    hunks = parse_unified_diff(AMBIGUOUS_DIFF)
    pad = "\n" * 9  # lines 1-9
    post = {"app/auth.py": pad + "def validate_user(user):\n    return user.id\n"}
    pre = {"app/auth.py": pad + (
        "def validate_user(user):\n"
        "    if user.email is None:\n"
        '        raise ValueError("email is required")\n'
        "    return user.id\n"
    )}
    syms = changed_symbols(hunks, post, pre)
    assert any(s.name == "validate_user" for s in syms)


def test_reconstructed_images_are_line_aligned():
    from clarifyreview.ingest.diff import reconstruct_sides

    pre, post = reconstruct_sides(parse_unified_diff(AMBIGUOUS_DIFF))
    # The hunk header says the change starts at line 10 on both sides.
    assert pre.splitlines()[9].strip().startswith("def validate_user")
    assert post.splitlines()[9].strip().startswith("def validate_user")


def test_end_to_end_ingestion_finds_the_changed_symbol():
    """Without a checkout, ingestion still attributes the change to a symbol."""
    from clarifyreview.ingest import from_raw

    ctx = from_raw(pr_id="x", diff=AMBIGUOUS_DIFF)
    assert [s.name for s in ctx.changed_symbols] == ["validate_user"]


def test_innermost_symbol_wins():
    source = "class A:\n    def m(self):\n        return 1\n"
    syms = PythonAstExtractor().symbols(source)
    from clarifyreview.ingest.semantic import _overlapping
    hit = _overlapping(syms, [(2, 3)])
    assert [s.name for s in hit] == ["A.m"]
