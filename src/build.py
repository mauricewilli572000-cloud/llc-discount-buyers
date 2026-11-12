"""Turn a raw county row (any layout) into Parcel fields using the detected column map."""
from __future__ import annotations

import re

import config
from . import fields as F
from .normalize import clean, iso_date, luc3, num, split_csz, to_int, zip5


def address(row: dict, cols: dict) -> str:
    a = clean(F.pick(row, cols, "address"))
    if a:
        return a.split(",")[0].strip()
    parts = [clean(F.pick(row, cols, k)) for k in ("addr_no", "addr_dir", "addr_street", "addr_suffix")]
    parts = [p for p in parts if p and p != "0"]
    return " ".join(parts)


def site_city_zip(row: dict, cols: dict) -> tuple[str, str]:
    city = clean(F.pick(row, cols, "city"))
    z = zip5(F.pick(row, cols, "zip"))
    full = clean(F.pick(row, cols, "address"))
    if full and "," in full:                     # 'STREET, CITY, OH 43215'
        parts = [p.strip() for p in full.split(",")]
        if not city and len(parts) > 2:
            city = parts[1]
        if not z:
            m = re.search(r"\b(\d{5})(?:-\d{4})?\s*$", full)
            z = m.group(1) if m else ""
    return city, z


def mailing(row: dict, cols: dict) -> tuple[str, str, str, str]:
    street = clean(F.pick(row, cols, "mail_address"))
    city = clean(F.pick(row, cols, "mail_city"))
    state = clean(F.pick(row, cols, "mail_state"))
    z = zip5(F.pick(row, cols, "mail_zip"))
    csz = clean(F.pick(row, cols, "mail_csz"))
    if csz and not city:
        city, state, z2 = split_csz(csz)
        z = z or z2
    if street and not city:                     # one-line 'STREET, CITY, ST 12345'
        m = re.match(r"^(.*?),\s*(.*?),?\s+([A-Z]{2})\s+(\d{5})", street.upper())
        if m:
            street, city, state, z = m.group(1), m.group(2), m.group(3), m.group(4)
    return street, city, state[:2].upper(), z


def market_value(row: dict, cols: dict) -> tuple[float | None, bool]:
    """(market value, came_from_taxable). Prefers a market total, then land+building, then taxable/0.35."""
    tot = num(F.pick(row, cols, "market_value"))
    if tot:
        return tot, False
    land, bldg = num(F.pick(row, cols, "market_land")), num(F.pick(row, cols, "market_bldg"))
    if land or bldg:
        return (land or 0) + (bldg or 0), False
    tax = num(F.pick(row, cols, "taxable_value"))
    if tax:
        return tax / config.ASSESSMENT_RATIO, True
    return None, False


def homestead(row: dict, cols: dict) -> bool | None:
    v = F.pick(row, cols, "homestead")
    if v is None:
        return None
    s = clean(v).upper()
    if s in ("", "0", "N", "NO", "FALSE", "0.0"):
        return False
    return True


def sale_fields(row: dict, cols: dict) -> dict:
    return {
        "sale_date": iso_date(F.pick(row, cols, "sale_date")),
        "sale_price": num(F.pick(row, cols, "sale_price")),
        "deed_type": clean(F.pick(row, cols, "deed_type")),
        "sale_parcels": to_int(F.pick(row, cols, "sale_parcels")) or 1,
        "buyer": clean(F.pick(row, cols, "buyer")),
        "seller": clean(F.pick(row, cols, "seller")),
    }


def parcel_fields(row: dict, cols: dict) -> dict:
    city, z = site_city_zip(row, cols)
    m = mailing(row, cols)
    mv, _ = market_value(row, cols)
    luc_raw = F.pick(row, cols, "luc")
    return {
        "address": address(row, cols), "city": city, "zip": z,
        "owner": clean(F.pick(row, cols, "owner")), "owner2": clean(F.pick(row, cols, "owner2")),
        "mail_address": m[0], "mail_city": m[1], "mail_state": m[2], "mail_zip": m[3],
        "luc": luc3(luc_raw), "luc_desc": clean(F.pick(row, cols, "luc_desc")) or re.sub(r"^\d+\s*-?\s*", "", clean(luc_raw)),
        "nbhd": clean(F.pick(row, cols, "nbhd")),
        "market_value": mv,
        "year_built": to_int(F.pick(row, cols, "year_built")),
        "sqft": num(F.pick(row, cols, "sqft")) or None,
        "beds": to_int(F.pick(row, cols, "beds")),
        "homestead": homestead(row, cols),
    }


def building_fields(row: dict, cols: dict) -> dict:
    return {"year_built": to_int(F.pick(row, cols, "year_built")),
            "sqft": num(F.pick(row, cols, "sqft")) or None,
            "beds": to_int(F.pick(row, cols, "beds"))}
