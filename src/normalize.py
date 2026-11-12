"""Small text / number / date helpers shared by every county loader."""
from __future__ import annotations

import datetime as dt
import re

import config

LLC_RE = re.compile("|".join(config.LLC_PATTERNS), re.I)
ENTITY_RE = re.compile("|".join(config.ENTITY_PATTERNS), re.I)
GOV_RE = re.compile("|".join(config.GOVERNMENT_PATTERNS), re.I)
CSZ_RE = re.compile(r"^(.*?)[\s,]+([A-Z]{2})\s+(\d{5})(?:-?\d{4})?$")


def clean(v) -> str:
    if v is None:
        return ""
    return re.sub(r"\s+", " ", str(v)).strip().strip('"').strip()


def num(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = clean(v).replace(",", "").replace("$", "")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return None


def to_int(v) -> int | None:
    n = num(v)
    return int(n) if n is not None and n > 0 else None


_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d-%b-%Y", "%d-%b-%y", "%Y%m%d",
                 "%m-%d-%Y", "%b %d %Y", "%d-%b-%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S",
                 "%m/%d/%Y %I:%M:%S %p", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")


def iso_date(v) -> str:
    """Excel datetimes, ArcGIS epoch ms, and the usual text formats -> 'YYYY-MM-DD' ('' if unknown)."""
    if v is None or v == "":
        return ""
    if isinstance(v, dt.datetime):
        return v.date().isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, (int, float)):
        if v > 10**11:                                   # ArcGIS epoch milliseconds
            try:
                return dt.datetime.fromtimestamp(v / 1000, tz=dt.timezone.utc).date().isoformat()
            except (OverflowError, OSError, ValueError):
                return ""
        if 20000 < v < 80000:                            # Excel serial day
            return (dt.date(1899, 12, 30) + dt.timedelta(days=int(v))).isoformat()
        if 19000101 <= v <= 21001231:
            v = str(int(v))
        else:
            return ""
    s = clean(v)
    if s.isdigit() and len(s) >= 12:
        return iso_date(int(s))
    s19 = s[:22].upper().title() if re.search(r"[A-Za-z]{3}", s) else s[:22]
    for fmt in _DATE_FORMATS:
        for cand in (s19, s[:10], s[:19]):
            try:
                d = dt.datetime.strptime(cand, fmt).date()
                if 1900 < d.year < 2100:
                    return d.isoformat()
            except ValueError:
                continue
    return ""


def luc3(v) -> str:
    """'510', '5100' (Cuyahoga), '510 - ONE-FAMILY DWLG', 510.0 -> '510'."""
    s = clean(v)
    m = re.match(r"^\s*(\d{3,4})(?:\.0+)?\b", s)
    return m.group(1)[:3] if m else ""


def is_residential(luc: str) -> bool:
    lo, hi = config.RESIDENTIAL_LUC
    return bool(luc) and luc.isdigit() and lo <= int(luc) <= hi


def is_llc(name: str) -> bool:
    return bool(LLC_RE.search(name or ""))


def is_entity(name: str) -> bool:
    return bool(ENTITY_RE.search(name or "")) or is_government(name)


def is_government(name: str) -> bool:
    return bool(GOV_RE.search(name or ""))


def split_csz(text: str) -> tuple[str, str, str]:
    """'COLUMBUS OH 43215-1486' -> ('COLUMBUS', 'OH', '43215')."""
    t = clean(text).upper()
    m = CSZ_RE.match(t)
    return (m.group(1).strip(" ,"), m.group(2), m.group(3)) if m else (t, "", "")


def zip5(v) -> str:
    m = re.search(r"(\d{5})", clean(v).split(".")[0].zfill(5) if isinstance(v, (int, float)) else clean(v))
    return m.group(1) if m else ""


def name_key(name: str) -> str:
    """Normalize a buyer name for grouping: 'ABC Homes, L.L.C.' == 'ABC HOMES LLC'."""
    s = clean(name).upper()
    s = re.sub(r"\bL\s?\.?\s?L\s?\.?\s?C\b\.?", "LLC", s)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\bTHE\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def address_key(addr: str) -> str:
    s = clean(addr).upper()
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\b(STREET)\b", "ST", s)
    s = re.sub(r"\b(AVENUE)\b", "AVE", s)
    s = re.sub(r"\b(AV)\b", "AVE", s)
    s = re.sub(r"\b(ROAD)\b", "RD", s)
    s = re.sub(r"\b(DRIVE)\b", "DR", s)
    return re.sub(r"\s+", " ", s).strip()
