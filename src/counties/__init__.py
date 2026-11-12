"""County loaders. Each exposes `load(raw_dir, since) -> list[Parcel]` (residential parcels with their
latest sale) and `sources(raw_dir) -> {source name: local file path}` for discover.py."""
from __future__ import annotations

import re

from ..normalize import is_llc, is_residential


def pkey(p: str) -> str:
    """Join key for a parcel number: digits only, leading zeros dropped."""
    return re.sub(r"\D", "", str(p or "")).lstrip("0")


def latest(rows, key, order):
    """Keep one row per key: the one with the largest order() value."""
    best: dict = {}
    for r in rows:
        k = key(r)
        if not k:
            continue
        o = order(r)
        if k not in best or o > best[k][0]:
            best[k] = (o, r)
    return {k: r for k, (_, r) in best.items()}


def residential_only(parcels):
    return [p for p in parcels if is_residential(p.luc)]


__all__ = ["pkey", "latest", "residential_only", "is_llc"]
