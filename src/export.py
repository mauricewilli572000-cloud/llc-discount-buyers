"""Write dashboard JSON + CSVs, carrying 'date_added' forward from the previous run."""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from .normalize import is_entity


def _previous(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {r["key"]: r.get("date_added", "") for r in data.get("records", [])}
    except (OSError, ValueError, KeyError):
        return {}


def stamp(rows: list[dict], path: Path, today: str) -> int:
    """Set date_added (kept from earlier runs) and is_new. Returns how many are new."""
    prev = _previous(path)
    new = 0
    for r in rows:
        r["date_added"] = prev.get(r["key"]) or today
        r["is_new"] = r["key"] not in prev
        new += r["is_new"]
    return new


def write_json(path: Path, rows: list[dict], meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"meta": meta, "records": rows}, separators=(",", ":"), default=str),
                    encoding="utf-8")


def _money(v):
    return f"{v:.0f}" if isinstance(v, (int, float)) else ""


def split_name(owner: str) -> tuple[str, str]:
    """County names are mostly 'LAST FIRST M' (Cuyahoga: 'LAST, FIRST'). -> (first, last)."""
    name = (owner or "").strip()
    if not name or is_entity(name):
        return "", name.title()
    name = re.split(r"\s+(?:&|AND)\s+", name)[0]
    if "," in name:
        last, first = [x.strip() for x in name.split(",", 1)]
        return first.title(), last.title()
    parts = name.split()
    if len(parts) == 1:
        return "", parts[0].title()
    return " ".join(parts[1:]).title(), parts[0].title()


HIT_COLUMNS = ["County", "Parcel", "Property Address", "City", "Zip", "Land Use", "Buyer (LLC)", "Seller",
               "Sale Date", "Sale Price", "Market Value", "Price/Value", "Discount %", "Equity Gap",
               "Deed Type", "Flags", "Buyer Mailing", "Year Built", "Sq Ft", "Beds", "Date Added", "Link"]


def hits_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(HIT_COLUMNS)
        for h in rows:
            mail = ", ".join(x for x in (h["mail_address"], h["mail_city"],
                                         f"{h['mail_state']} {h['mail_zip']}".strip()) if x)
            w.writerow([h["county"], h["parcel"], h["address"], h["city"].title(), h["zip"],
                        h["luc_desc"] or h["luc"], h["buyer"], h["seller"], h["sale_date"],
                        _money(h["sale_price"]), _money(h["market_value"]), h["price_to_value"],
                        h["discount_pct"], _money(h["equity_gap"]), h["deed_type"], "; ".join(h["flags"]),
                        mail, h["year_built"] or "", _money(h["sqft"]), h["beds"] or "", h["date_added"],
                        h["url"]])


GHL_COLUMNS = ["First Name", "Last Name", "Full Name", "Owner 2", "Address", "City", "State", "Postal Code",
               "Property Address", "Property City", "Property Zip", "County", "Lead Type", "Land Use",
               "Market Value", "Year Built", "Sq Ft", "Last Sale Date", "Score", "Tier", "Signals",
               "Similar To", "Parcel", "Date Added", "Tags"]


def ghl_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(GHL_COLUMNS)
        for r in rows:
            first, last = split_name(r["owner"])
            mailing = bool(r["mail_address"])
            tags = ["llc lookalike", f"{r['county'].lower()} county", r["tier"].lower()] + r["flags"]
            w.writerow([first, last, r["owner"].title(), r["owner2"].title(),
                        r["mail_address"] if mailing else r["address"],
                        (r["mail_city"] if mailing else r["city"]).title(),
                        r["mail_state"] if mailing else "OH",
                        r["mail_zip"] if mailing else r["zip"],
                        r["address"], r["city"].title(), r["zip"], r["county"], "LLC Lookalike",
                        r["luc_desc"] or r["luc"], _money(r["market_value"]), r["year_built"] or "",
                        _money(r["sqft"]), r["sale_date"], r["score"], r["tier"], "; ".join(r["flags"]),
                        r["similar_to"], r["parcel"], r["date_added"], ",".join(tags)])


BUYER_COLUMNS = ["Buyer (LLC)", "Discount Buys", "Total Spent", "Total Market Value", "Avg Price/Value",
                 "Counties", "Zips", "First Buy", "Last Buy", "Mailing Address", "City", "State", "Zip",
                 "Properties"]


def buyers_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(BUYER_COLUMNS)
        for b in rows:
            w.writerow([b["buyer"], b["purchases"], b["total_spent"], b["total_value"], b["avg_price_to_value"],
                        ", ".join(b["counties"]), " ".join(b["zips"]), b["first_buy"], b["last_buy"],
                        b["mail_address"], b["mail_city"], b["mail_state"], b["mail_zip"],
                        " | ".join(b["properties"])])
