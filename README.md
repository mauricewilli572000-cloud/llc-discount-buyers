# Ohio LLC Discount Buyers + Lookalike Leads

Finds houses that **sold to an LLC in the last 6 months for under 50% of the county's market
value**, then builds a list of **houses that look like them but haven't sold** — the next ones an
investor would want.

Counties: **Franklin, Cuyahoga, Hamilton, Summit**. Shelby is off: its Auditor publishes no bulk
sales or parcel download (search-only site).

## Outputs (`docs/`, served as the dashboard)

| File | What |
| --- | --- |
| `index.html` | Dashboard: Lookalike leads · LLC buys under 50% · LLC buyers |
| `lookalikes.json`, `ghl_lookalikes.csv` | Lookalike leads, scored 0-100 (GoHighLevel columns) |
| `llc_discount_sales.json`, `.csv` | The LLC purchases under 50% of market value |
| `llc_buyers.json`, `.csv` | Those LLCs grouped: # of discount buys, spend, mailing address (cash-buyer list) |

## Rules

**Discount sale (hit):** residential (land use 510-599), newest sale within 183 days, buyer name is
an LLC (grantee if the county publishes it, otherwise the current owner), sale price ≥ $1,000,
market value ≥ $15,000, price ÷ market value < 0.50. Several parcels on one deed for one price are
compared against their combined value; deeds covering parcels we can't see are skipped. Sheriff
sales, land-bank and government sellers are kept but tagged so you can hide them.

**Lookalike:** residential, owned by a person (not an LLC/company/bank/government), not sold in the
window, in a ZIP or neighborhood where a hit happened. Score =
50 × similarity to the closest hit (land use, value, sq ft, year built) +
20 × number of discount buys in that area +
30 × seller signals (absentee, out of state, not owner-occupied, owned 15+ years).
Top 750 per county with score ≥ 55. All knobs are in `config.py`.

"Market value" is the county's appraised value. If a county's value column turns out to be the
35% taxable value, the run notices (recent sale prices ~3× the value) and rescales it.

## Sources (official, free)

- Franklin — Auditor monthly drop `apps.franklincountyauditor.com/Outside_User_Files/` (`Parcel.txt`, `Value.txt`)
- Cuyahoga — Fiscal Office tax parcel layer `gis.cuyahogacounty.gov/.../CCFO/Parcel_Fabric_Taxparcels/FeatureServer/1`
- Hamilton — `hcauditor.org/download/revalue/` (`HistoricSalesExport.xlsx`, `Monthly_tax_information.xlsx`, `bldginfo.xlsx`)
- Summit — `fiscaloffice.summitoh.net/data-downloads` (`SC706_SALES`, `SC700_OWNDAT`, `SC703_ASMT`, `SC705_PARDAT`)

Column names are detected from each file's headers. If a county shows 0 results or odd values,
run the workflow with **discover** ticked (or `python discover.py hamilton`) to print the real
columns, then pin the right one in `data/field_overrides.json`:

```json
{"hamilton_tax": {"market_value": "Total Market Value"}, "summit_sales": {"buyer": "OWN1"}}
```

## Running

Runs Mondays (~7:12 AM ET) via GitHub Actions, or on demand (Actions → Run workflow, optional
single county). A county that fails keeps its previous results; the dashboard shows which.

```powershell
pip install -r requirements.txt
python run_pipeline.py                  # all counties
python run_pipeline.py --county summit  # one county
python -m pytest -q
```

## Zillow data

GitHub can't reach Zillow, so lookups are done through the Zillow connector in a Claude chat and
saved to `data/zillow.json` (keyed `County|parcel`: Zestimate, range, beds/baths/sq ft, a sold comp).
Every run re-attaches them, and the dashboard shows a Zestimate column plus "paid X% of Zestimate"
on discount sales. After adding lookups, `python merge_zillow.py` updates the dashboard files
immediately without re-downloading county data.
