#!/usr/bin/env python3
"""Ohio LLC discount buyers + lookalike leads.

1. Load every residential parcel (with its latest sale) for each enabled county.
2. HITS: newest sale in the last 6 months, buyer is an LLC, price < 50% of market value.
3. LOOKALIKES: unsold, individually owned houses like the hits, in the same areas.
4. BUYERS: hits grouped by LLC (cash-buyer list).
5. Write docs/*.json (dashboard) and docs/*.csv (GHL import / spreadsheets).

Usage:
    python run_pipeline.py                      # all enabled counties
    python run_pipeline.py --county franklin    # one county (others keep last run's results)
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib
import json
import logging
import shutil
import sys

import config
from src import analyze, export, lookalike

log = logging.getLogger("llc_discount_buyers")


def _old_rows(path, county_label):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [r for r in data.get("records", []) if r.get("county") == county_label]
    except (OSError, ValueError):
        return []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--county", action="append", help="only run these counties (repeatable)")
    ap.add_argument("--keep-raw", action="store_true", help="don't delete downloads afterwards")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    today = dt.date.today()
    since = (today - dt.timedelta(days=config.WINDOW_DAYS)).isoformat()

    wanted = [c.lower() for c in args.county] if args.county else None
    all_hits, all_looks, county_meta = [], [], {}
    for key, c in config.COUNTIES.items():
        label = c["label"]
        run_it = c["enabled"] and (wanted is None or key in wanted)
        if not run_it:
            county_meta[label] = {"status": "disabled", "note": c.get("note", "")} if not c["enabled"] else \
                {"status": "kept from previous run"}
            if c["enabled"]:                     # carry earlier results for counties not run now
                all_hits += _old_rows(config.HITS_JSON, label)
                all_looks += _old_rows(config.LOOKALIKES_JSON, label)
            continue
        raw = config.RAW_DIR / key
        raw.mkdir(parents=True, exist_ok=True)
        try:
            mod = importlib.import_module(f"src.counties.{key}")
            parcels = mod.load(raw, since)
            factor = analyze.calibrate_values(parcels, label)
            hits, stats = analyze.find_hits(parcels, today)
            looks = lookalike.find(parcels, hits, today)
            log.info("%s: %d residential parcels, %s, %d lookalikes", label, len(parcels), stats, len(looks))
            county_meta[label] = {"status": "ok", "parcels": len(parcels), "value_factor": round(factor, 3),
                                  "lookalikes": len(looks), **stats}
            all_hits += hits
            all_looks += looks
        except Exception as e:  # noqa: BLE001 - one county failing must not sink the rest
            log.exception("%s failed", label)
            county_meta[label] = {"status": "error", "error": str(e)[:300]}
            all_hits += _old_rows(config.HITS_JSON, label)
            all_looks += _old_rows(config.LOOKALIKES_JSON, label)
        finally:
            if not args.keep_raw:
                shutil.rmtree(raw, ignore_errors=True)

    t = today.isoformat()
    new_hits = export.stamp(all_hits, config.HITS_JSON, t)
    new_looks = export.stamp(all_looks, config.LOOKALIKES_JSON, t)
    all_hits.sort(key=lambda h: (h["sale_date"], h["discount_pct"]), reverse=True)
    all_looks.sort(key=lambda r: -r["score"])
    buyer_rows = analyze.buyers(all_hits)
    meta = {"updated": t, "window_start": since, "max_price_to_value": config.MAX_PRICE_TO_VALUE,
            "counties": county_meta, "hits": len(all_hits), "new_hits": new_hits,
            "lookalikes": len(all_looks), "new_lookalikes": new_looks, "buyers": len(buyer_rows)}
    export.write_json(config.HITS_JSON, all_hits, meta)
    export.write_json(config.LOOKALIKES_JSON, all_looks, meta)
    export.write_json(config.BUYERS_JSON, buyer_rows, meta)
    export.hits_csv(config.HITS_CSV, all_hits)
    export.ghl_csv(config.GHL_LOOKALIKES_CSV, all_looks)
    export.buyers_csv(config.BUYERS_CSV, buyer_rows)
    config.STATE_JSON.parent.mkdir(parents=True, exist_ok=True)
    config.STATE_JSON.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    log.info("Done: %d hits (%d new), %d lookalikes, %d LLC buyers", len(all_hits), new_hits,
             len(all_looks), len(buyer_rows))
    ok = any(m.get("status") == "ok" for m in county_meta.values())
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
