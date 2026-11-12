"""Hamilton County: Auditor exports (sales history, monthly tax/parcel info, building info)."""
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

import config
from .. import build, fields
from ..io import download, read_any
from ..model import Parcel
from ..normalize import address_key, clean, iso_date
from . import pkey, residential_only

log = logging.getLogger(__name__)
COUNTY = "Hamilton"


def sources(raw_dir: Path) -> dict[str, Path]:
    return {f"hamilton_{k}": download(config.HAMILTON_BASE + v, raw_dir / v)
            for k, v in config.HAMILTON_FILES.items()}


def latest_sales(path: Path, since: str) -> dict[str, dict]:
    """{parcel key: newest sale row fields} - only parcels whose newest sale is on/after `since`."""
    newest: dict[str, dict] = {}
    cols = None
    for r in read_any(path):
        cols = cols or fields.detect(r.keys(), "hamilton_sales")
        pid = pkey(fields.pick(r, cols, "parcel"))
        if not pid:
            continue
        s = build.sale_fields(r, cols)
        if not s["sale_date"]:
            continue
        cur = newest.get(pid)
        if cur is None or s["sale_date"] > cur["sale_date"] or (
                s["sale_date"] == cur["sale_date"] and (s["sale_price"] or 0) > (cur["sale_price"] or 0)):
            newest[pid] = s
    return newest


def buildings(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    cols = None
    for r in read_any(path):
        cols = cols or fields.detect(r.keys(), "hamilton_building", ["parcel", "year_built", "sqft", "beds"])
        pid = pkey(fields.pick(r, cols, "parcel"))
        if not pid:
            continue
        b = build.building_fields(r, cols)
        cur = out.get(pid)
        if cur is None or (b["sqft"] or 0) > (cur["sqft"] or 0):   # main structure = largest
            out[pid] = b
    return out


def load(raw_dir: Path, since: str, files: dict[str, Path] | None = None) -> list[Parcel]:
    files = files or sources(raw_dir)
    sales = latest_sales(files["hamilton_sales"], since)
    bldg = buildings(files["hamilton_building"]) if files.get("hamilton_building") else {}
    year = dt.date.today().year - 1
    out: list[Parcel] = []
    cols = None
    for r in read_any(files["hamilton_tax"]):
        cols = cols or fields.detect(r.keys(), "hamilton_tax")
        raw = clean(fields.pick(r, cols, "parcel"))
        pid = pkey(raw)
        if not pid:
            continue
        p = Parcel(county=COUNTY, parcel=raw, **build.parcel_fields(r, cols), **build.sale_fields(r, cols))
        s = sales.get(pid)
        if s and (not p.sale_date or s["sale_date"] >= p.sale_date):
            for k, v in s.items():
                if v not in (None, "") or k in ("sale_date", "sale_price"):
                    setattr(p, k, v)
        b = bldg.get(pid)
        if b:
            p.year_built = b["year_built"] or p.year_built
            p.sqft = b["sqft"] or p.sqft
            p.beds = b["beds"] or p.beds
        if not p.zip and p.mail_zip and address_key(p.mail_address) == address_key(p.address):
            p.zip, p.city = p.mail_zip, p.city or p.mail_city    # file leaves site ZIP blank
        p.sale_date = iso_date(p.sale_date)
        p.url = config.HAMILTON_PARCEL_URL.format(parcel_digits=pkey(raw).zfill(12), year=year)
        out.append(p)
    return residential_only(out)
