"""Fill a missing property city / ZIP (Hamilton and Summit files often leave them blank).

1. Owner lives there (mailing address == property address): use the mailing city / ZIP.
2. Otherwise borrow from the nearest house number on the same street that has one.
"""
from __future__ import annotations

import bisect
import re
from collections import defaultdict

from .model import Parcel
from .normalize import address_key

_NUM_RE = re.compile(r"^(\d+)\s+(.*)$")


def _split(addr: str) -> tuple[int, str] | None:
    m = _NUM_RE.match(address_key(addr))
    return (int(m.group(1)), m.group(2)) if m else None


def fill(parcels: list[Parcel]) -> int:
    """Fill blanks in place; returns how many parcels got a ZIP."""
    filled = 0
    for p in parcels:
        if not p.zip and p.mail_zip and p.address and address_key(p.mail_address) == address_key(p.address):
            p.zip, p.city = p.mail_zip, p.city or p.mail_city
            filled += 1
    streets: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    for p in parcels:
        if p.zip:
            s = _split(p.address)
            if s:
                streets[s[1]].append((s[0], p.zip, p.city))
    for v in streets.values():
        v.sort()
    for p in parcels:
        if p.zip:
            continue
        s = _split(p.address)
        cands = streets.get(s[1]) if s else None
        if not cands:
            continue
        i = bisect.bisect_left(cands, (s[0], "", ""))
        near = [c for c in cands[max(0, i - 1):i + 1]]
        best = min(near, key=lambda c: abs(c[0] - s[0]))
        if abs(best[0] - s[0]) <= 400:          # same block-ish; streets can cross ZIPs
            p.zip, p.city = best[1], p.city or best[2]
            filled += 1
    return filled
