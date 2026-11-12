"""Franklin County: Auditor monthly data drop (Parcel.txt + Value.txt, optional dwelling file)."""
from __future__ import annotations

import logging
import re
import urllib.parse
from pathlib import Path

import config
from .. import build, fields
from ..io import extract, get, read_delimited
from ..model import Parcel
from ..normalize import clean, num
from . import pkey, residential_only

log = logging.getLogger(__name__)
COUNTY = "Franklin"


def hyphen_parcel(p: str) -> str:
    d = re.sub(r"\D", "", p or "")
    if len(d) == 11:
        return f"{d[:3]}-{d[3:9]}-{d[9:]}"
    if len(d) == 9:
        return f"{d[:3]}-{d[3:]}-00"
    return clean(p)


def list_drops() -> list[tuple[str, str]]:
    """[(folder name, url)] of monthly drops, newest first."""
    base = config.FRANKLIN_OUTSIDE_FILES
    years = sorted(set(re.findall(r"/Outside_User_Files/(\d{4})/", get(base).text)), reverse=True)
    drops = []
    for y in years[:2]:
        url = f"{base}{y}/"
        for h in re.findall(r'href="([^"]+)"', get(url).text, re.I):
            h = urllib.parse.urljoin(url, h)
            name = urllib.parse.unquote(h.rstrip("/").rsplit("/", 1)[-1])
            if h.endswith("/") and re.match(r"\d{4}-\d{2}-\d{2}", name):
                drops.append((name, h))
    return sorted(drops, reverse=True)


def sources(raw_dir: Path) -> dict[str, Path]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    found: dict[str, Path] = {}
    for name, url in list_drops()[:5]:
        missing = [f for f in config.FRANKLIN_FILES if f not in found]
        if not missing:
            break
        zpath = raw_dir / "franklin_drop.zip"
        try:
            zpath.write_bytes(get(url + urllib.parse.quote(config.FRANKLIN_ZIP)).content)
        except Exception as e:  # noqa: BLE001
            log.warning("Franklin drop %s unavailable: %s", name, e)
            continue
        got = extract(zpath, raw_dir, names=set(missing), name_re=config.FRANKLIN_OPTIONAL_FILE_RE)
        for base, path in got.items():
            found.setdefault(base, path)
        log.info("Franklin drop %s -> %s", name, sorted(got))
        zpath.unlink(missing_ok=True)
    lost = [f for f in config.FRANKLIN_FILES if f not in found]
    if lost:
        raise RuntimeError(f"Franklin files not found in recent drops: {lost}")
    return {("franklin_" + Path(k).stem.lower()): v for k, v in found.items()}


def market_values(path: Path) -> dict[str, float]:
    best: dict[str, tuple[int, float]] = {}
    for r in read_delimited(path):
        pid = pkey(r.get("Parcel Id") or r.get("PARCEL ID") or "")
        vt = clean(r.get("ValueType")).upper()
        if not pid or (vt and vt != "BASE"):
            continue
        yr = int(num(r.get("TaxYear")) or 0)
        val = (num(r.get("MarketLand")) or 0) + (num(r.get("MarketImpr")) or 0)
        if not val:
            continue
        if pid not in best or yr > best[pid][0]:
            best[pid] = (yr, val)
    return {k: v for k, (_, v) in best.items()}


def buildings(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    cols = None
    for r in read_delimited(path):
        cols = cols or fields.detect(r.keys(), "franklin_building", ["parcel", "year_built", "sqft", "beds"])
        if "year_built" not in cols and "sqft" not in cols:
            return {}
        pid = pkey(fields.pick(r, cols, "parcel"))
        if pid and pid not in out:
            out[pid] = build.building_fields(r, cols)
    return out


def load(raw_dir: Path, since: str, files: dict[str, Path] | None = None) -> list[Parcel]:
    files = files or sources(raw_dir)
    values = market_values(files["franklin_value"])
    bldg = {}
    for name, path in files.items():
        if name not in ("franklin_parcel", "franklin_value"):
            bldg.update(buildings(path))
    out: list[Parcel] = []
    cols = None
    for r in read_delimited(files["franklin_parcel"]):
        cols = cols or fields.detect(r.keys(), "franklin_parcel")
        raw_pid = clean(fields.pick(r, cols, "parcel"))
        pid = pkey(raw_pid)
        if not pid:
            continue
        p = Parcel(county=COUNTY, parcel=hyphen_parcel(raw_pid), **build.parcel_fields(r, cols),
                   **build.sale_fields(r, cols))
        p.market_value = values.get(pid) or p.market_value
        b = bldg.get(pid)
        if b:
            p.year_built, p.sqft, p.beds = b["year_built"], b["sqft"], b["beds"]
        p.url = config.FRANKLIN_PARCEL_URL.format(parcel=re.sub(r"\D", "", raw_pid))
        out.append(p)
    return residential_only(out)
