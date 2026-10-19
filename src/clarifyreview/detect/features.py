"""The 14 structured features.

Every one is computable from a `PRContext` with no LLM call. That is the whole
argument for detectors (b) and (c): they cost nothing at inference time, so if
either matches the sampling detector's accuracy, the sampling detector is not
worth its latency or its dollars. Keep the set small - the training set is ~200
rows, not 200,000.
"""

from __future__ import annotations

import re

from ..types import PRContext

FEATURE_NAMES: tuple[str, ...] = (
    # stated intent
    "has_linked_issue",
    "issue_body_len",
    "commit_msg_len",
    "commit_msg_generic",
    "pr_body_len",
    # risk surface
    "removes_guard",
    "touches_public_symbol",
    "signature_changed",
    "modifies_error_handling",
    "touches_sensitive_symbol",
    # shape
    "files_touched",
    "net_lines",
    "changed_symbols",
    "deletion_ratio",
    # corroboration
    "test_file_changed",
)

# A commit message that is only one of these carries no intent at all.
_GENERIC_MSG = re.compile(
    r"^\W*(wip|fix|fixes|fixed|bug ?fix|cleanup|clean up|update|updates|updated|"
    r"minor|misc|refactor|tweak|tidy|chore|patch|changes|small fix|"
    r"address (review )?comments?)\W*$",
    re.IGNORECASE,
)

# Calls whose removal changes what the program refuses to do.
_GUARD_CALL = re.compile(
    r"\b(assert|validate\w*|check\w*|verify\w*|ensure\w*|sanitiz\w*|"
    r"is_valid|require\w*|guard\w*|authorize\w*|authenticate\w*)\b",
    re.IGNORECASE,
)
_GUARD_SHAPE = re.compile(
    r"(if\s+.*\bis\s+None\b)|(if\s+not\s+\w+)|(\braise\s+\w*(Error|Exception))|"
    r"(if\s+\w+\s*==\s*None)|(\bthrow\s+new\s+\w+)",
)
_ERROR_HANDLING = re.compile(
    r"\b(try|except|catch|finally|raise|throw|rescue)\b|"
    r"\b\w*(Error|Exception)\b"
)
_SENSITIVE = re.compile(
    r"\b(auth\w*|login|password|passwd|secret|token|credential\w*|crypt\w*|"
    r"hash|hmac|signature|permission\w*|acl|session|sql|query|exec|eval|"
    r"open|read|write|delete|unlink|subprocess|os\.system)\b",
    re.IGNORECASE,
)
_TEST_FILE = re.compile(r"(^|/)(tests?|spec)/|(^|/)test_[^/]*\.py$|_test\.(py|go|js|ts)$|"
                        r"\.(test|spec)\.(js|ts|tsx)$")


def extract(ctx: PRContext) -> dict[str, float]:
    """Feature vector as a name -> value mapping. Order is fixed by FEATURE_NAMES."""
    added = "\n".join(line for h in ctx.hunks for line in h.added)
    removed = "\n".join(line for h in ctx.hunks for line in h.removed)

    n_added = sum(len(h.added) for h in ctx.hunks)
    n_removed = sum(len(h.removed) for h in ctx.hunks)

    commit_text = " ".join(ctx.commit_messages).strip()
    generic = bool(ctx.commit_messages) and all(
        _GENERIC_MSG.match(m.strip().splitlines()[0] if m.strip() else "")
        for m in ctx.commit_messages
    )

    feats: dict[str, float] = {
        "has_linked_issue": float(
            ctx.linked_issue is not None and ctx.linked_issue.is_substantive
        ),
        "issue_body_len": float(len(ctx.linked_issue.body) if ctx.linked_issue else 0),
        "commit_msg_len": float(len(commit_text)),
        "commit_msg_generic": float(generic or not commit_text),
        "pr_body_len": float(len(ctx.body or "")),
        "removes_guard": float(_removes_guard(added, removed)),
        "touches_public_symbol": float(any(s.is_public for s in ctx.changed_symbols)),
        "signature_changed": float(any(s.signature_changed for s in ctx.changed_symbols)),
        "modifies_error_handling": float(
            bool(_ERROR_HANDLING.search(added) or _ERROR_HANDLING.search(removed))
        ),
        # Removed code counts as much as added: deleting an auth check touches
        # security-sensitive code just as surely as writing one. The file path
        # counts too, since `auth.py` is a strong signal even when the changed
        # symbol inside it is named something neutral.
        "touches_sensitive_symbol": float(
            any(_SENSITIVE.search(s.name) for s in ctx.changed_symbols)
            or any(_SENSITIVE.search(f) for f in ctx.files_touched)
            or bool(_SENSITIVE.search(added) or _SENSITIVE.search(removed))
        ),
        "files_touched": float(len(ctx.files_touched)),
        "net_lines": float(n_added - n_removed),
        "changed_symbols": float(len(ctx.changed_symbols)),
        "deletion_ratio": (n_removed / (n_added + n_removed)) if (n_added + n_removed) else 0.0,
        "test_file_changed": float(
            any(_TEST_FILE.search(f) for f in ctx.files_touched)
        ),
    }
    assert set(feats) == set(FEATURE_NAMES), "feature set drifted from FEATURE_NAMES"
    return feats


def _removes_guard(added: str, removed: str) -> bool:
    """A guard removed and not put back.

    Comparing removed against added rather than looking at removed alone is what
    keeps a refactor that moves a check three lines up from reading as a deleted
    safety check.
    """
    removed_guards = set(_GUARD_CALL.findall(removed))
    added_guards = set(_GUARD_CALL.findall(added))
    if removed_guards - added_guards:
        return True
    removed_shapes = len(_GUARD_SHAPE.findall(removed))
    added_shapes = len(_GUARD_SHAPE.findall(added))
    return removed_shapes > added_shapes


def to_array(feats: dict[str, float]) -> list[float]:
    """Fixed-order vector for sklearn. Order is the contract with the pickle."""
    return [feats[name] for name in FEATURE_NAMES]


def explain(feats: dict[str, float]) -> str:
    """Human-readable summary of the features that are actually firing."""
    notable = []
    if not feats["has_linked_issue"]:
        notable.append("no linked issue")
    if feats["commit_msg_generic"]:
        notable.append("generic commit message")
    if feats["removes_guard"]:
        notable.append("removes a validation or guard")
    if feats["signature_changed"]:
        notable.append("signature changed")
    if feats["touches_public_symbol"]:
        notable.append("touches a public symbol")
    if feats["touches_sensitive_symbol"]:
        notable.append("touches security- or IO-sensitive code")
    if not feats["test_file_changed"]:
        notable.append("no test change alongside")
    if feats["deletion_ratio"] > 0.6:
        notable.append(f"deletion-heavy ({feats['deletion_ratio']:.0%} removed)")
    return "; ".join(notable) if notable else "no ambiguity signals"
