"""Find LLC purchases under 50% of market value, and group the LLC buyers."""
from __future__ import annotations

import datetime as dt
import logging
import re
import statistics
from collections import defaultdict

import config
from .model import Parcel
from .normalize import address_key, is_government, is_llc, name_key

log = logging.getLogger(__name__)
SHERIFF_RE = re.compile(config.SHERIFF_DEED_RE, re.I)
LANDBANK_RE = re.compile(config.LAND_BANK_RE, re.I)


def calibrate_values(parcels: list[Parcel], county: str) -> float:
    """If 'market value' is really the 35% taxable value, sale prices run ~3x it. Detect and rescale.

    Returns the factor applied (1.0 = values already looked like market value).
    """
    since = (dt.date.today() - dt.timedelta(days=730)).isoformat()   # old sale prices predate today's values
    ratios = [p.sale_price / p.market_value for p in parcels
              if p.sale_date >= since and p.sale_price and p.sale_price >= 20_000
              and p.market_value and p.market_value > 5_000 and p.sale_parcels <= 1]
    if len(ratios) < 30:
        return 1.0
    med = statistics.median(ratios)
    if med > 1.9:
        factor = 1 / config.ASSESSMENT_RATIO
        log.warning("%s: median sale/value %.2f - values look like 35%% taxable; rescaling x%.2f",
                    county, med, factor)
        for p in parcels:
            if p.market_value:
                p.market_value = round(p.market_value * factor)
        return factor
    log.info("%s: median sale/value %.2f (values look like market value)", county, med)
    return 1.0


def _in_window(p: Parcel, start: str, end: str) -> bool:
    return bool(p.sale_date) and start <= p.sale_date <= end


def find_hits(parcels: list[Parcel], today: dt.date | None = None) -> tuple[list[dict], dict]:
    """Returns (hits, stats). A hit = newest sale in window, LLC buyer, price < 50% of market value."""
    today = today or dt.date.today()
    start = (today - dt.timedelta(days=config.WINDOW_DAYS)).isoformat()
    end = today.isoformat()
    stats = defaultdict(int)
    recent = [p for p in parcels if _in_window(p, start, end)]
    stats["sales_in_window"] = len(recent)
    llc = [p for p in recent if is_llc(p.buyer_name)]
    stats["llc_purchases"] = len(llc)

    # Several parcels bought on one deed for one price: compare against their combined value.
    groups: dict[tuple, list[Parcel]] = defaultdict(list)
    for p in llc:
        groups[(p.county, name_key(p.buyer_name), p.sale_date, p.sale_price)].append(p)

    hits = []
    for (_, _, _, price), members in groups.items():
        combined = sum(m.market_value or 0 for m in members)
        declared = max(m.sale_parcels for m in members)
        for p in members:
            if not price or price < config.MIN_SALE_PRICE:
                stats["skipped_nominal_price"] += 1
                continue
            if not p.market_value or p.market_value < config.MIN_MARKET_VALUE:
                stats["skipped_no_value"] += 1
                continue
            if declared > len(members):          # deed covers parcels we can't see -> ratio unreliable
                stats["skipped_bundle_unknown"] += 1
                continue
            value = combined if len(members) > 1 else p.market_value
            ratio = price / value if value else None
            if ratio is None or ratio >= config.MAX_PRICE_TO_VALUE:
                continue
            tags = []
            if len(members) > 1:
                tags.append(f"bundle of {len(members)}")
            if SHERIFF_RE.search(p.deed_type or ""):
                tags.append("sheriff sale")
            if LANDBANK_RE.search(p.seller or ""):
                tags.append("land bank seller")
            elif p.seller and is_government(p.seller):
                tags.append("government seller")
            if p.homestead:
                tags.append("homestead")
            d = p.to_dict()
            d.update({
                "buyer": p.buyer_name,
                "price_to_value": round(ratio, 3),
                "discount_pct": round((1 - ratio) * 100, 1),
                "equity_gap": round(value - price),
                "bundle_value": round(combined) if len(members) > 1 else None,
                "flags": tags,
                "key": f"{p.county}|{p.parcel}|{p.sale_date}",
            })
            hits.append(d)
    hits.sort(key=lambda h: (h["sale_date"], -h["discount_pct"]), reverse=True)
    stats["hits"] = len(hits)
    return hits, dict(stats)


def buyers(hits: list[dict]) -> list[dict]:
    """Group hits by LLC: how many discount buys, total spent, where, how to reach them."""
    by: dict[str, dict] = {}
    for h in hits:
        k = name_key(h["buyer"])
        b = by.setdefault(k, {"buyer": h["buyer"], "purchases": 0, "total_spent": 0.0, "total_value": 0.0,
                              "counties": set(), "zips": set(), "first_buy": h["sale_date"],
                              "last_buy": h["sale_date"], "mail_address": "", "mail_city": "",
                              "mail_state": "", "mail_zip": "", "properties": []})
        b["purchases"] += 1
        b["total_spent"] += h["sale_price"] or 0
        b["total_value"] += h["market_value"] or 0
        b["counties"].add(h["county"])
        if h["zip"]:
            b["zips"].add(h["zip"])
        b["first_buy"] = min(b["first_buy"], h["sale_date"])
        b["last_buy"] = max(b["last_buy"], h["sale_date"])
        # LLC tax-bill mailing address = how to reach the buyer (skip when it's just the property)
        if h["mail_address"] and not b["mail_address"] and address_key(h["mail_address"]) != address_key(h["address"]):
            for f in ("mail_address", "mail_city", "mail_state", "mail_zip"):
                b[f] = h[f]
        b["properties"].append(f"{h['address']}, {h['city']} ({h['county']})".strip(", "))
    out = []
    for b in by.values():
        b["counties"] = sorted(b["counties"])
        b["zips"] = sorted(b["zips"])
        b["avg_price_to_value"] = round(b["total_spent"] / b["total_value"], 3) if b["total_value"] else None
        b["total_spent"] = round(b["total_spent"])
        b["total_value"] = round(b["total_value"])
        out.append(b)
    out.sort(key=lambda b: (-b["purchases"], -b["total_spent"]))
    return out
