#!/usr/bin/env python3
"""Download each county's files and print their real column names, the detected mapping and a
sample row. Use it when a county shows 0 hits: pin a wrong column in data/field_overrides.json.

    python discover.py                 # all enabled counties
    python discover.py hamilton        # one county
"""
from __future__ import annotations

import importlib
import logging
import sys

import config
from src import fields
from src.io import read_any


def main(argv) -> int:
    logging.basicConfig(level=logging.WARNING)
    names = argv or [k for k, c in config.COUNTIES.items() if c["enabled"]]
    for key in names:
        print(f"\n######## {key}")
        mod = importlib.import_module(f"src.counties.{key}")
        try:
            srcs = mod.sources(config.RAW_DIR / key)
        except Exception as e:  # noqa: BLE001
            print(f"  could not fetch: {e}")
            continue
        for name, src in srcs.items():
            print(f"\n=== {name}")
            if isinstance(src, list):            # ArcGIS layer: field names only
                headers, sample = src, {}
            else:
                it = read_any(src)
                sample = next(it, {})
                headers = list(sample.keys())
            print("  columns:", headers)
            print("  mapping:", fields.detect(headers, name))
            for k, v in list(sample.items())[:60]:
                print(f"    {k!r}: {v!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
