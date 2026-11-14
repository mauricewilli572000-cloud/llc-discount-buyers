"""Summit County: Fiscal Office CAMA exports (sales, owners, appraisal, parcel data)."""
from __future__ import annotations

import logging
import re
import urllib.parse
from pathlib import Path

import config
from .. import build, fields
from ..io import download, first_member, get, read_any
from ..model import Parcel
from ..normalize import clean
from . import pkey, residential_only

log = logging.getLogger(__name__)
COUNTY = "Summit"


def discover_links() -> dict[str, str]:
    found = {p: config.SUMMIT_FILES_BASE + f for p, f in config.SUMMIT_FILES.items()}
    try:
        html = get(config.SUMMIT_DOWNLOADS_PAGE).text
        for prefix in config.SUMMIT_FILES:
            links = sorted(set(re.findall(rf'href="([^"]*{prefix}_\d+\.zip)"', html, re.I)),
                           key=lambda u: int(re.search(r"_(\d+)\.zip", u).group(1)))
            if links:
                found[prefix] = urllib.parse.urljoin(config.SUMMIT_DOWNLOADS_PAGE, links[-1])
    except Exception as e:  # noqa: BLE001
        log.warning("Summit downloads page unavailable, using fallback names: %s", e)
    return found


def sources(raw_dir: Path) -> dict[str, Path]:
    out = {}
    for prefix, url in discover_links().items():
        z = download(url, raw_dir / f"{prefix}.zip")
        out["summit_" + prefix.split("_", 1)[1].lower()] = first_member(z, raw_dir)
    return out


def _by_parcel(path: Path, source: str, order_field: str) -> dict[str, tuple[dict, dict]]:
    """{parcel key: (row, cols)} keeping the row with the largest order field (tax year / sale date)."""
    best: dict[str, tuple] = {}
    cols = None
    for r in read_any(path):
        cols = cols or fields.detect(r.keys(), source)
        pid = pkey(fields.pick(r, cols, "parcel"))
        if not pid:
            continue
        if order_field == "sale_date":
            o = build.sale_fields(r, cols)["sale_date"]
        else:
            o = clean(fields.pick(r, cols, order_field))
        if pid not in best or o > best[pid][0]:
            best[pid] = (o, r)
    return {k: (r, cols) for k, (_, r) in best.items()}


def load(raw_dir: Path, since: str, files: dict[str, Path] | None = None) -> list[Parcel]:
    files = files or sources(raw_dir)
    sales = _by_parcel(files["summit_sales"], "summit_sales", "sale_date")
    owners = _by_parcel(files["summit_owndat"], "summit_owndat", "tax_year")
    asmt = _by_parcel(files["summit_asmt"], "summit_asmt", "tax_year")
    out: list[Parcel] = []
    for pid, (r, cols) in _by_parcel(files["summit_pardat"], "summit_pardat", "tax_year").items():
        p = Parcel(county=COUNTY, parcel=clean(fields.pick(r, cols, "parcel")).zfill(7),
                   **build.parcel_fields(r, cols))
        if pid in owners:
            orow, ocols = owners[pid]
            of = build.parcel_fields(orow, ocols)
            # OWNDAT's street / city columns are the owner's MAILING address
            of["mail_address"] = of["mail_address"] or of["address"]
            of["mail_city"] = of["mail_city"] or of["city"]
            for k in ("owner", "owner2", "mail_address", "mail_city", "mail_state", "mail_zip", "homestead"):
                if of[k] not in (None, ""):
                    setattr(p, k, of[k])
        if pid in asmt:
            arow, acols = asmt[pid]
            mv, _ = build.market_value(arow, acols)
            p.market_value = mv or p.market_value
            if not p.luc:
                p.luc = build.parcel_fields(arow, acols)["luc"]
        if pid in sales:
            srow, scols = sales[pid]
            for k, v in build.sale_fields(srow, scols).items():
                setattr(p, k, v)
            if not p.owner:
                p.owner = p.buyer
        p.url = config.SUMMIT_PARCEL_URL
        out.append(p)
    return residential_only(out)
