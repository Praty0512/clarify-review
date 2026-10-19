"""Blinding shared by the study page and the merge step.

Each participant sees, for each item, the two reviews labelled "A" and "B". Which
condition is A is decided by FNV-1a over participant id and item id - computed
identically in the browser (study.html) and here, so the page needs no server and
no answer key is shipped to participants. Item order is shuffled the same way.
"""

from __future__ import annotations

FNV_OFFSET, FNV_PRIME = 0x811C9DC5, 0x01000193


def fnv1a(text: str) -> int:
    h = FNV_OFFSET
    for byte in text.encode("utf-8"):
        h ^= byte
        h = (h * FNV_PRIME) & 0xFFFFFFFF
    return h


def clarify_is_a(participant: str, item: str) -> bool:
    return fnv1a(f"{participant.strip().lower()}|{item}") % 2 == 0
