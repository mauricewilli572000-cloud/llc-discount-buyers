"""HTTP downloads and streaming row readers (CSV / tab-delimited / XLSX)."""
from __future__ import annotations

import csv
import io
import logging
import time
import zipfile
from pathlib import Path

import config
from . import fields

log = logging.getLogger(__name__)
csv.field_size_limit(50_000_000)

try:  # browser-like TLS fingerprint; some county sites block plain clients
    from curl_cffi import requests as _http
    _SESSION = _http.Session(impersonate="chrome")
except Exception:  # pragma: no cover
    import requests as _http
    _SESSION = _http.Session()
    _SESSION.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0 Safari/537.36"


def get(url: str, **kw):
    last = None
    for attempt in range(config.HTTP_RETRIES):
        try:
            r = _SESSION.get(url, timeout=config.HTTP_TIMEOUT, **kw)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            last = str(e)
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed: {last}")


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    log.info("Downloading %s", url)
    dest.write_bytes(get(url).content)
    return dest


def extract(zpath: Path, out_dir: Path, names=None, name_re=None) -> dict[str, Path]:
    """Extract members (by exact base name, or regex on the base name). {base name: path}."""
    import re
    out: dict[str, Path] = {}
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            base = Path(info.filename).name
            if not base or info.is_dir():
                continue
            if names is not None and base not in names and not (name_re and re.search(name_re, base, re.I)):
                continue
            dest = out_dir / base
            with z.open(info) as src, dest.open("wb") as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
            out[base] = dest
    return out


def _sniff_delimiter(sample: str) -> str:
    first = sample.splitlines()[0] if sample else ""
    return max(("\t", ",", "|"), key=first.count) if first else ","


def read_delimited(path: Path):
    """Yield dict rows from a CSV / tab / pipe file (encoding-tolerant)."""
    raw = path.read_bytes()[:20000]
    enc = "utf-8-sig"
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        enc = "latin-1"
    with path.open(encoding=enc, errors="replace", newline="") as f:
        delim = _sniff_delimiter(f.read(20000))
        f.seek(0)
        reader = csv.DictReader(f, delimiter=delim)
        reader.fieldnames = [(h or "").strip().strip('"') for h in (reader.fieldnames or [])]
        yield from reader


def read_xlsx(path: Path, sheet: int | None = None):
    """Yield dict rows from an XLSX, finding the header row (first row with 3+ known column words)."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheets = [wb.worksheets[sheet]] if sheet is not None else wb.worksheets
    known = {a.split(":", 1)[1] for rules in fields.RULES.values() for a in rules}
    for ws in sheets:
        header = None
        for row in ws.iter_rows(values_only=True):
            if header is None:
                cells = [fields.norm(c) for c in row]
                hits = sum(1 for c in cells if c and any(k == c or (len(k) > 4 and k in c) for k in known))
                if hits >= 3:
                    header = [str(c).strip() if c is not None else "" for c in row]
                continue
            if row is None or all(c is None or c == "" for c in row):
                continue
            yield dict(zip(header, row))
    wb.close()


def read_any(path: Path):
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        return read_xlsx(path)
    return read_delimited(path)


def headers_of(path: Path) -> list[str]:
    for row in read_any(path):
        return list(row.keys())
    return []


def first_member(zpath: Path, out_dir: Path, exts=(".csv", ".txt", ".xlsx")) -> Path:
    with zipfile.ZipFile(zpath) as z:
        info = next(i for i in z.infolist() if Path(i.filename).suffix.lower() in exts)
        dest = out_dir / Path(info.filename).name
        with z.open(info) as src, dest.open("wb") as dst:
            while chunk := src.read(1 << 20):
                dst.write(chunk)
    return dest


def zip_bytes_member(content: bytes) -> tuple[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        info = next(i for i in z.infolist() if not i.is_dir())
        return info.filename, z.read(info)
