#!/usr/bin/env python3
"""Re-attach data/zillow.json to the dashboard files right away (no county downloads).

    python merge_zillow.py
"""
import json

import config
from src import export, zillow


def main() -> int:
    data = zillow.load()
    for path, csv_writer in ((config.HITS_JSON, export.hits_csv), (config.LOOKALIKES_JSON, export.ghl_csv)):
        doc = json.loads(path.read_text(encoding="utf-8"))
        n = zillow.attach(doc["records"], data)
        doc["meta"]["zillow_checked"] = n
        export.write_json(path, doc["records"], doc["meta"])
        csv_writer(config.HITS_CSV if path == config.HITS_JSON else config.GHL_LOOKALIKES_CSV, doc["records"])
        print(f"{path.name}: {n} records with Zillow data")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
