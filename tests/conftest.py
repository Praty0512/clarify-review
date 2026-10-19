import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import pytest

from clarifyreview.types import LinkedIssue


AMBIGUOUS_DIFF = """diff --git a/app/auth.py b/app/auth.py
--- a/app/auth.py
+++ b/app/auth.py
@@ -10,9 +10,6 @@ class Session:
 def validate_user(user):
     \"\"\"Check the user is usable.\"\"\"
-    if user.email is None:
-        raise ValueError("email is required")
-
     return user.id
"""

CLEAR_DIFF = """diff --git a/app/util.py b/app/util.py
--- a/app/util.py
+++ b/app/util.py
@@ -1,5 +1,6 @@
 def _slugify(text):
-    return text.lower()
+    return text.lower().strip()
diff --git a/tests/test_util.py b/tests/test_util.py
--- a/tests/test_util.py
+++ b/tests/test_util.py
@@ -1,2 +1,5 @@
 def test_slugify():
+    assert _slugify(" A ") == "a"
"""


@pytest.fixture
def ambiguous_ctx():
    from clarifyreview.ingest import from_raw

    return from_raw(
        pr_id="acme/app#1",
        diff=AMBIGUOUS_DIFF,
        repo="acme/app",
        number=1,
        title="fix login bug",
        commit_messages=["fix"],
    )


@pytest.fixture
def clear_ctx():
    from clarifyreview.ingest import from_raw

    return from_raw(
        pr_id="acme/app#2",
        diff=CLEAR_DIFF,
        repo="acme/app",
        number=2,
        title="Strip whitespace in slugify",
        commit_messages=["Strip surrounding whitespace before slugifying, so that "
                         "titles pasted from the CMS do not produce trailing dashes."],
        linked_issue=LinkedIssue(
            number=44,
            title="Slugs from pasted titles have trailing dashes",
            body="When a title is pasted from the CMS it keeps its surrounding "
                 "whitespace, and _slugify turns that into a trailing dash in the "
                 "URL. Trim the input before slugifying. Reproduced on staging with "
                 "the title ' Hello World '.",
        ),
    )
