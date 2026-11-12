"""
Lookalikes: houses that resemble what LLCs just bought at a discount, but haven't sold.

For each county, every residential parcel that
  * is in a ZIP (or neighborhood) where an LLC made a discount buy,
  * is owned by a person (not an LLC, company, bank or government),
  * did not sell in the window,
gets a 0-100 score:
  50 pts  similarity to the closest hit in its area (land use, value, size, age)
  20 pts  how many discount buys happened in that area (investor activity)
  30 pts  motivated-seller signals: absentee, out of state, not owner-occupied, long ownership
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict

import config
from .model import Parcel
from .normalize import address_key, is_entity

W_SIM, W_AREA, W_MOTIVE = 50, 20, 30


def _ratio_sim(a, b, span=math.log(2)) -> float | None:
    if not a or not b or a <= 0 or b <= 0:
        return None
    return max(0.0, 1 - abs(math.log(a / b)) / span)


def similarity(p: Parcel, h: dict) -> float:
    parts = [(0.25, 1.0 if p.luc == h["luc"] else 0.4)]
    v = _ratio_sim(p.market_value, h["market_value"])
    parts.append((0.40, v if v is not None else 0.3))
    s = _ratio_sim(p.sqft, h.get("sqft"), span=math.log(1.6))
    if s is not None:
        parts.append((0.20, s))
    if p.year_built and h.get("year_built"):
        parts.append((0.15, max(0.0, 1 - abs(p.year_built - h["year_built"]) / 40)))
    total_w = sum(w for w, _ in parts)
    return sum(w * x for w, x in parts) / total_w


def motivation(p: Parcel, today: dt.date) -> tuple[float, list[str]]:
    flags, pts = [], 0.0
    absentee = bool(p.mail_address) and address_key(p.mail_address) != address_key(p.address)
    if absentee:
        flags.append("absentee")
        pts += 0.35
    if p.mail_state and p.mail_state.upper() != config.STATE:
        flags.append("out of state")
        pts += 0.20
    if p.homestead is False:
        flags.append("not owner-occupied")
        pts += 0.20 if not absentee else 0.10
    if p.sale_date:
        years = (today - dt.date.fromisoformat(p.sale_date)).days / 365.25
        if years >= config.LONG_TENURE_YEARS:
            flags.append(f"owned {int(years)}+ yrs")
            pts += 0.25
    else:
        flags.append("no recorded sale")
        pts += 0.15
    return min(1.0, pts), flags


def find(parcels: list[Parcel], hits: list[dict], today: dt.date | None = None) -> list[dict]:
    today = today or dt.date.today()
    start = (today - dt.timedelta(days=config.WINDOW_DAYS)).isoformat()
    hit_keys = {(h["county"], h["parcel"]) for h in hits}
    by_zip: dict[tuple, list[dict]] = defaultdict(list)
    by_nbhd: dict[tuple, list[dict]] = defaultdict(list)
    for h in hits:
        if h["zip"]:
            by_zip[(h["county"], h["zip"])].append(h)
        if h.get("nbhd"):
            by_nbhd[(h["county"], h["nbhd"])].append(h)

    scored: dict[str, list[dict]] = defaultdict(list)
    for p in parcels:
        area = by_nbhd.get((p.county, p.nbhd)) if p.nbhd else None
        area_kind = "neighborhood"
        if not area:
            area, area_kind = by_zip.get((p.county, p.zip)), "zip"
        if not area or (p.county, p.parcel) in hit_keys:
            continue
        if not p.owner or is_entity(p.owner) or (p.sale_date and p.sale_date >= start):
            continue
        if not p.market_value or p.market_value < config.MIN_MARKET_VALUE:
            continue
        best = max(area, key=lambda h: similarity(p, h))
        sim = similarity(p, best)
        area_pts = min(1.0, len(area) / 4)
        mot, flags = motivation(p, today)
        score = round(W_SIM * sim + W_AREA * area_pts + W_MOTIVE * mot)
        if score < config.LOOKALIKE_MIN_SCORE:
            continue
        d = p.to_dict()
        d.update({
            "score": score,
            "tier": "Hot" if score >= 80 else "Warm" if score >= 68 else "Cold",
            "flags": flags,
            "similar_to": f"{best['address']} - {best['buyer']} paid ${best['sale_price']:,.0f} "
                          f"({best['discount_pct']:.0f}% under value) on {best['sale_date']}",
            "similar_parcel": best["parcel"],
            "area": f"{area_kind} {p.nbhd if area_kind == 'neighborhood' else p.zip}",
            "area_discount_buys": len(area),
            "key": f"{p.county}|{p.parcel}",
        })
        scored[p.county].append(d)
    out = []
    for county, rows in scored.items():
        rows.sort(key=lambda r: (-r["score"], -(r["market_value"] or 0)))
        out.extend(rows[:config.LOOKALIKES_PER_COUNTY])
    return out
