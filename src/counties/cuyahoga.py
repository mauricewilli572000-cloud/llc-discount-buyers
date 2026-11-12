"""Cuyahoga County: Fiscal Office tax parcel layer (ArcGIS REST, updated daily).

Two queries: (1) residential parcels that transferred since the window start,
(2) every residential parcel in the ZIPs where an LLC bought - the lookalike pool.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import time
from pathlib import Path

import requests

import config
from .. import build, fields
from ..model import Parcel
from ..normalize import clean, is_llc, zip5
from . import pkey, residential_only

log = logging.getLogger(__name__)
COUNTY = "Cuyahoga"
S = requests.Session()
S.headers["User-Agent"] = "llc-discount-buyers/1.0 (public records research)"


def _req(url: str, params: dict) -> dict:
    last = None
    for attempt in range(config.HTTP_RETRIES):
        try:
            r = S.post(url, data={**params, "f": "json"}, timeout=120)
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                raise RuntimeError(json.dumps(data["error"]))
            return data
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"ArcGIS request failed: {url}: {last}")


def layer_fields() -> tuple[list[str], dict]:
    info = _req(config.CUYAHOGA_LAYER, {})
    return [f["name"] for f in info.get("fields", [])], info


def query(where: str, info: dict) -> list[dict]:
    page = min(config.ARCGIS_PAGE_SIZE, int(info.get("maxRecordCount") or 1000))
    oid = info.get("objectIdField") or "OBJECTID"
    rows, offset = [], 0
    while True:
        data = _req(f"{config.CUYAHOGA_LAYER}/query", {
            "where": where, "outFields": "*", "returnGeometry": "false", "orderByFields": oid,
            "resultOffset": offset, "resultRecordCount": page})
        feats = data.get("features", [])
        rows.extend(f.get("attributes", {}) for f in feats)
        if not feats or (len(feats) < page and not data.get("exceededTransferLimit")):
            return rows
        offset += len(feats)


def to_parcel(r: dict, cols: dict) -> Parcel:
    raw = clean(fields.pick(r, cols, "parcel"))
    p = Parcel(county=COUNTY, parcel=raw, **build.parcel_fields(r, cols), **build.sale_fields(r, cols))
    p.zip = p.zip or zip5(fields.pick(r, cols, "zip"))
    p.url = config.CUYAHOGA_PARCEL_URL.format(parcel_digits=pkey(raw).zfill(8))
    return p


def sources(raw_dir: Path) -> dict[str, list[str]]:
    names, _ = layer_fields()
    return {"cuyahoga_taxparcel": names}


def load(raw_dir: Path, since: str, rows: list[dict] | None = None) -> list[Parcel]:
    if rows is not None:                       # tests
        cols = fields.detect(rows[0].keys(), "cuyahoga_taxparcel")
        return residential_only([to_parcel(r, cols) for r in rows])
    names, info = layer_fields()
    cols = fields.detect(names, "cuyahoga_taxparcel")
    date_f, luc_f, zip_f = cols.get("sale_date"), cols.get("luc"), cols.get("zip")
    if not date_f:
        raise RuntimeError(f"Cuyahoga layer has no transfer date field: {names}")
    res = f" AND {luc_f} LIKE '5%'" if luc_f else ""
    sales = [to_parcel(r, cols) for r in query(f"{date_f} >= DATE '{since}'{res}", info)]
    log.info("Cuyahoga: %d residential transfers since %s", len(sales), since)
    zips = sorted({p.zip for p in sales if p.zip and is_llc(p.buyer_name)})
    pool: dict[str, Parcel] = {pkey(p.parcel): p for p in sales}
    if zips and zip_f:
        ftype = next((f.get("type") for f in info.get("fields", []) if f["name"] == zip_f), "")
        for i in range(0, len(zips), 10):
            chunk = zips[i:i + 10]
            vals = ",".join(chunk if "Double" in ftype or "Integer" in ftype else (f"'{z}'" for z in chunk))
            for r in query(f"{zip_f} IN ({vals}){res}", info):
                p = to_parcel(r, cols)
                pool.setdefault(pkey(p.parcel), p)
        log.info("Cuyahoga: %d residential parcels in %d LLC-buyer ZIPs", len(pool), len(zips))
    return residential_only(pool.values())


def default_since(days: int) -> str:
    return (dt.date.today() - dt.timedelta(days=days)).isoformat()
