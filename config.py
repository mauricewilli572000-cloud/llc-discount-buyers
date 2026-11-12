"""
Ohio LLC discount buyers + lookalike leads - configuration.

What this repo finds
--------------------
1. HITS: residential parcels whose most recent sale (last WINDOW_DAYS days) went to an
   LLC for less than MAX_PRICE_TO_VALUE of the county's market value.
2. LOOKALIKES: houses that look like those hits (same ZIP / neighborhood, same kind of
   house, similar value, size and age) that have NOT sold, owned by individuals, with
   motivated-seller signals (absentee, out of state, not owner-occupied, long ownership).
3. BUYERS: the LLCs behind the hits, grouped (a cash-buyer list).

Sources (all official county files, free, no login)
---------------------------------------------------
Franklin  Auditor monthly data drop  apps.franklincountyauditor.com/Outside_User_Files/
          Parcel.txt (owner, last sale, LUC, site + mailing address), Value.txt (market value)
Cuyahoga  Fiscal Office tax parcel layer (ArcGIS, daily)
          gis.cuyahogacounty.gov/.../CCFO/Parcel_Fabric_Taxparcels/FeatureServer/1
Hamilton  Auditor exports  hcauditor.org/revalue.asp
          HistoricSalesExport.xlsx, Monthly_tax_information.xlsx, bldginfo.xlsx
Summit    Fiscal Office CAMA exports  fiscaloffice.summitoh.net/data-downloads
          SC706_SALES, SC700_OWNDAT, SC703_ASMT, SC705_PARDAT
Shelby    No bulk sales download found (Auditor site is search-only) - disabled.
"""
from pathlib import Path

STATE = "OH"

# --------------------------------------------------------------------------
# Hit rules
# --------------------------------------------------------------------------
WINDOW_DAYS = 183                 # "last 6 months"
MAX_PRICE_TO_VALUE = 0.50         # sold for under 50% of market value
MIN_SALE_PRICE = 1_000            # $0 / $10 / gift / quit-claim transfers are not sales
MIN_MARKET_VALUE = 15_000         # skip near-worthless parcels (ratios meaningless)
# Ohio land use codes: 510-599 residential dwellings (500 = residential vacant land).
RESIDENTIAL_LUC = (510, 599)
# Ohio taxable (assessed) value is 35% of market. If a county field turns out to be
# the taxable value, the pipeline notices (sale prices ~3x "value") and rescales.
ASSESSMENT_RATIO = 0.35

LLC_PATTERNS = [r"\bL\s?\.?\s?L\s?\.?\s?C\b\.?", r"LLC\b", r"\bLIMITED LIABILITY\b"]
ENTITY_PATTERNS = LLC_PATTERNS + [
    r"\bINC\b", r"\bCORP", r"\bCOMPANY\b", r"\bCO\b", r"\bLTD\b", r"\bL\.?P\b", r"\bLLP\b",
    r"\bBANK\b", r"\bMORTGAGE\b", r"\bFEDERAL\b", r"\bNATIONAL ASS", r"\bHOLDINGS?\b",
    r"\bPROPERTIES\b", r"\bINVESTMENTS?\b", r"\bPARTNERS", r"\bGROUP\b", r"\bASSOC", r"\bCHURCH\b",
    r"\bMINISTR", r"\bFUND\b", r"\bREALTY\b", r"\bHOMES\b", r"\bCAPITAL\b", r"\bVENTURES?\b",
]
GOVERNMENT_PATTERNS = [
    r"\bCITY OF\b", r"\bVILLAGE OF\b", r"\bTOWNSHIP\b", r"\bBOARD OF\b", r"\bCOUNTY\b",
    r"\bSTATE OF OHIO\b", r"\bUNITED STATES\b", r"\bSECRETARY OF\b", r"\bHUD\b",
    r"\bLAND REUTILIZATION\b", r"\bLAND BANK\b", r"\bPORT AUTHORITY\b", r"\bMETROPOLITAN HOUSING\b",
    r"\bSCHOOL DIST", r"\bRAILROAD\b", r"\bCOMMUNITY IMPROVEMENT CORP",
]
# Deed / instrument types that say how the property sold (tagged, not filtered out).
SHERIFF_DEED_RE = r"^SH$|\bSHF\b|SHERIFF"
LAND_BANK_RE = r"LAND (BANK|REUTILIZATION)|COMMUNITY IMPROVEMENT CORP"

# --------------------------------------------------------------------------
# Lookalike rules
# --------------------------------------------------------------------------
LOOKALIKE_MIN_SCORE = 55
LOOKALIKES_PER_COUNTY = 750
LONG_TENURE_YEARS = 15

# --------------------------------------------------------------------------
# Counties
# --------------------------------------------------------------------------
COUNTIES = {
    "franklin": {"enabled": True, "label": "Franklin"},
    "cuyahoga": {"enabled": True, "label": "Cuyahoga"},
    "hamilton": {"enabled": True, "label": "Hamilton"},
    "summit": {"enabled": True, "label": "Summit"},
    "shelby": {"enabled": False, "label": "Shelby",
               "note": "No bulk sales/parcel download published; Auditor site is search-only."},
}

# Franklin
FRANKLIN_OUTSIDE_FILES = "https://apps.franklincountyauditor.com/Outside_User_Files/"
FRANKLIN_ZIP = "Tab-Delimited.zip"
FRANKLIN_FILES = ("Parcel.txt", "Value.txt")
FRANKLIN_OPTIONAL_FILE_RE = r"(dwell|resid|build)"       # year built / sq ft, if the drop has one
FRANKLIN_PARCEL_URL = "https://property.franklincountyauditor.com/_web/propertycard/propertycard.aspx?pin={parcel}"

# Cuyahoga (layer URL found by cleveland-code-enforcement's discovery)
CUYAHOGA_LAYER = "https://gis.cuyahogacounty.gov/server/rest/services/CCFO/Parcel_Fabric_Taxparcels/FeatureServer/1"
CUYAHOGA_PARCEL_URL = "https://myplace.cuyahogacounty.gov/{parcel_digits}"
ARCGIS_PAGE_SIZE = 1000

# Hamilton
HAMILTON_BASE = "https://hcauditor.org/download/revalue/"
HAMILTON_FILES = {
    "sales": "HistoricSalesExport.xlsx",
    "tax": "Monthly_tax_information.xlsx",
    "building": "bldginfo.xlsx",
}
HAMILTON_PARCEL_URL = "https://wedge.hcauditor.org/view/re/{parcel_digits}/{year}/summary"

# Summit
SUMMIT_DOWNLOADS_PAGE = "https://fiscaloffice.summitoh.net/data-downloads"
SUMMIT_FILES_BASE = "https://fiscaloffice.summitoh.net/sites/default/files/assets/forms/"
SUMMIT_FILES = {          # prefix -> fallback file name (numeric suffix changes over time)
    "SC706_SALES": "SC706_SALES_5.zip",
    "SC700_OWNDAT": "SC700_OWNDAT_5.zip",
    "SC703_ASMT": "SC703_ASMT_4.zip",
    "SC705_PARDAT": "SC705_PARDAT_4.zip",
}
SUMMIT_PARCEL_URL = "https://propertyaccess.summitoh.net/search/commonsearch.aspx?mode=realprop"

HTTP_TIMEOUT = 300
HTTP_RETRIES = 4

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "raw"
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"
FIELD_OVERRIDES = DATA_DIR / "field_overrides.json"
STATE_JSON = DATA_DIR / "state.json"
HITS_JSON = DOCS_DIR / "llc_discount_sales.json"
LOOKALIKES_JSON = DOCS_DIR / "lookalikes.json"
BUYERS_JSON = DOCS_DIR / "llc_buyers.json"
HITS_CSV = DOCS_DIR / "llc_discount_sales.csv"
GHL_LOOKALIKES_CSV = DOCS_DIR / "ghl_lookalikes.csv"
BUYERS_CSV = DOCS_DIR / "llc_buyers.csv"
