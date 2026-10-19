from clarifyreview.detect.features import FEATURE_NAMES, extract, to_array


def test_feature_set_matches_declared_names(ambiguous_ctx):
    feats = extract(ambiguous_ctx)
    assert set(feats) == set(FEATURE_NAMES)
    assert len(to_array(feats)) == len(FEATURE_NAMES)


def test_detects_the_archetype(ambiguous_ctx):
    f = extract(ambiguous_ctx)
    assert f["has_linked_issue"] == 0.0
    assert f["commit_msg_generic"] == 1.0
    assert f["removes_guard"] == 1.0
    assert f["test_file_changed"] == 0.0
    assert f["deletion_ratio"] == 1.0


def test_clear_pr_scores_low(clear_ctx):
    f = extract(clear_ctx)
    assert f["has_linked_issue"] == 1.0
    assert f["commit_msg_generic"] == 0.0
    assert f["test_file_changed"] == 1.0
    assert f["removes_guard"] == 0.0


def test_guard_moved_not_removed_does_not_fire():
    """A refactor that relocates a check should not read as a deleted guard."""
    from clarifyreview.ingest import from_raw

    diff = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,4 +1,4 @@
 def f(user):
-    if user is None:
-        raise ValueError("no user")
+    if user is None:
+        raise ValueError("no user provided")
     return user
"""
    ctx = from_raw(pr_id="x", diff=diff)
    assert extract(ctx)["removes_guard"] == 0.0


def test_sensitive_symbol_detection(ambiguous_ctx):
    assert extract(ambiguous_ctx)["touches_sensitive_symbol"] == 1.0
