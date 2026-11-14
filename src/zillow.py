"""Zillow lookups done in chat, saved in data/zillow.json and attached to dashboard records.

The weekly GitHub run can't reach Zillow, so lookups are made through the Zillow connector in
a Claude chat and written to data/zillow.json, keyed "County|parcel":

    {"Franklin|010-113253-00": {"address": "2784 S High St, Columbus, OH 43207",
       "zestimate": 149300, "zestimate_low": 124000, "zestimate_high": 181000,
       "beds": 2, "baths": 1, "sqft": 784, "year_built": 1935,
       "comp": "6971 London Groveport Rd: 3bd/1ba 816 sf sold $177,000 ~2 mo ago",
       "checked": "2026-11-14"}}

Every run re-attaches them, so they survive the Monday refresh.
"""
from __future__ import annotations

import json

import config

PATH = config.DATA_DIR / "zillow.json"


def load() -> dict[str, dict]:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def attach(rows: list[dict], data: dict[str, dict] | None = None) -> int:
    """Add r['zillow'] (+ % of Zestimate for sales, filled-in size / age). Returns rows matched."""
    data = load() if data is None else data
    n = 0
    for r in rows:
        z = data.get(f"{r['county']}|{r['parcel']}")
        r.pop("zillow", None)
        r.pop("pct_of_zestimate", None)
        if not z:
            continue
        n += 1
        r["zillow"] = z
        zest = z.get("zestimate")
        if zest and r.get("sale_price") and r.get("discount_pct") is not None:
            r["pct_of_zestimate"] = round(r["sale_price"] / zest * 100, 1)
        for ours, theirs in (("sqft", "sqft"), ("year_built", "year_built"), ("beds", "beds")):
            if not r.get(ours) and z.get(theirs):
                r[ours] = z[theirs]
    return n
