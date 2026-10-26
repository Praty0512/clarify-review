"""Blinding shared by the study page and the merge step.

Each participant sees, for each item, the two reviews labelled "A" and "B". Which
condition is A is decided by FNV-1a over participant id and item id - computed
identically in the browser (study.html) and here, so the page needs no server and
no answer key is shipped to participants. Item order is shuffled the same way.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

FNV_OFFSET, FNV_PRIME = 0x811C9DC5, 0x01000193


def fnv1a(text: str) -> int:
    h = FNV_OFFSET
    for byte in text.encode("utf-8"):
        h ^= byte
        h = (h * FNV_PRIME) & 0xFFFFFFFF
    return h


def clarify_is_a(participant: str, item: str) -> bool:
    return fnv1a(f"{participant.strip().lower()}|{item}") % 2 == 0


PARTICIPANT_FIELDS = ["participant", "assigned_to", "sent", "returned"]


def item_ids(html: Path) -> list[str]:
    """Item ids embedded in a built study page."""
    text = Path(html).read_text(encoding="utf-8")
    start = text.find("const ITEMS = ")
    end = text.find(";\nfunction fnv1a", start)
    if start < 0 or end < 0:
        return []
    return [it["id"] for it in json.loads(text[start + len("const ITEMS = "):end])]


def main(argv: list[str] | None = None) -> int:
    """Write the participant tracking sheet and show the A/B balance.

    The codes are the only link between a returned CSV and a person, so the
    `assigned_to` column stays on the researchers' side; nothing here is shipped
    in study.html.
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", type=int, default=16)
    ap.add_argument("--out", default="study/participants.csv")
    ap.add_argument("--html", default="study/study.html")
    args = ap.parse_args(argv)

    out = Path(args.out)
    if out.exists():
        with out.open(newline="", encoding="utf-8-sig") as fh:
            if any((r.get("assigned_to") or r.get("sent") or r.get("returned") or "").strip()
                   for r in csv.DictReader(fh)):
                print(f"{out} already has entries; refusing to overwrite")
                return 2

    codes = [f"P{i:02d}" for i in range(1, args.codes + 1)]
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=PARTICIPANT_FIELDS)
        w.writeheader()
        for c in codes:
            w.writerow({"participant": c, "assigned_to": "", "sent": "", "returned": ""})
    print(f"wrote {len(codes)} participant codes to {out}")

    ids = item_ids(Path(args.html)) if Path(args.html).exists() else []
    if ids:
        per = {c: sum(clarify_is_a(c, i) for i in ids) for c in codes}
        total = sum(per.values())
        print(f"clarify shown as A in {total} of {len(codes) * len(ids)} item views "
              f"(per participant {min(per.values())}-{max(per.values())} of {len(ids)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
