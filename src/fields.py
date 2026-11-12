"""
Header -> field mapping for county files whose exact layouts aren't published.

Each canonical field has ordered alias rules on the normalized header
(lowercase letters+digits only):
    "eq:alias"  header equals alias
    "in:alias"  alias is a substring of the header
Earlier rules win. data/field_overrides.json pins a field to an exact header once
`python discover.py` has shown the real names:

    {"hamilton_tax": {"market_value": "Market Total Value"}}
"""
from __future__ import annotations

import json
import logging
import re

import config

log = logging.getLogger(__name__)

RULES: dict[str, list[str]] = {
    "parcel": ["eq:parcel", "eq:parcelid", "eq:parid", "eq:parcelnumber", "eq:parcelno", "eq:parcelpin",
               "eq:pin", "eq:ppn", "eq:parcelnum", "in:parcelid", "in:parcelnumber", "in:parcel"],
    "owner": ["eq:owner", "eq:ownername", "eq:owner1", "eq:ownername1", "eq:own1", "eq:deededowner",
              "eq:parcelowner", "eq:taxpayername", "in:ownername1", "in:ownername", "in:deededowner"],
    "owner2": ["eq:owner2", "eq:ownername2", "eq:own2", "in:ownername2"],
    "buyer": ["eq:grantee", "eq:buyer", "eq:buyername", "eq:newowner", "in:grantee", "in:buyer"],
    "seller": ["eq:grantor", "eq:seller", "eq:sellername", "eq:oldown", "eq:oldowner", "eq:prevowner",
               "in:grantor", "in:seller"],
    "sale_date": ["eq:saledate", "eq:saledt", "eq:transferdate", "eq:lastsaledate", "eq:conveyancedate",
                  "eq:dateofsale", "eq:deeddate", "in:saledate", "in:transferdate", "in:saledt",
                  "in:conveyancedate"],
    "sale_price": ["eq:saleprice", "eq:price", "eq:salesamount", "eq:saleamount", "eq:lastsaleamount",
                   "eq:amount", "eq:conveyanceprice", "eq:consideration", "eq:saleamt",
                   "in:saleprice", "in:salesamount", "in:saleamount", "in:conveyanceprice", "in:salesprice"],
    "deed_type": ["eq:deedtype", "eq:instrtyp", "eq:instrumenttype", "eq:saletype", "eq:convtype",
                  "eq:conveyancetype", "in:deedtype", "in:instrument", "in:conveyancetype"],
    "sale_parcels": ["eq:nopar", "eq:numparcels", "eq:numberofparcels", "eq:parcelcount", "eq:parcelssold",
                     "in:numberofparcels", "in:numparcels", "in:noofparcels"],
    "market_value": ["eq:aprtot", "eq:markettotal", "eq:totalmarketvalue", "eq:marketvalue",
                     "eq:grosscertifiedtotal", "eq:totmkt", "eq:mkttotal", "eq:appraisedvalue",
                     "eq:totalappraisedvalue", "in:markettotal", "in:totalmarket", "in:marketvalue",
                     "in:appraisedtotal", "in:totalappraised"],
    "market_land": ["eq:aprland", "eq:marketland", "eq:mktland", "in:marketland", "in:landmarket",
                    "in:appraisedland"],
    "market_bldg": ["eq:aprbldg", "eq:marketimpr", "eq:marketbuilding", "eq:mktbldg", "eq:mktimpr",
                    "in:marketimpr", "in:marketbuild", "in:marketbldg", "in:buildingmarket",
                    "in:appraisedbuild", "in:appraisedimpr"],
    "taxable_value": ["eq:certifiedtaxtotal", "eq:taxtotal", "eq:valtot", "eq:assessedvalue",
                      "eq:totalassessed", "in:assessedtotal", "in:taxabletotal", "in:totalassessed",
                      "in:assessedvalue", "in:certifiedtaxtotal"],
    "luc": ["eq:luc", "eq:landusecode", "eq:landuse", "eq:certifiedtaxluc", "eq:class", "eq:taxluc",
            "eq:usecode", "in:landusecode", "in:landuse", "in:luc"],
    "luc_desc": ["eq:lucdesc", "eq:landusedesc", "eq:landusedescription", "in:lucdesc", "in:landusedesc"],
    "nbhd": ["eq:nbhd", "eq:neighborhood", "eq:nbhdcode", "eq:appraisalarea", "eq:neighborhoodcode",
             "in:appraisalarea", "in:neighborhood", "in:nbhd"],
    "address": ["eq:siteaddress", "eq:location", "eq:propertyaddress", "eq:paraddr", "eq:situsaddress",
                "eq:locationaddress", "eq:paraddrall", "eq:address", "eq:propertylocation", "in:siteaddress",
                "in:propertylocation", "in:propertyaddress",
                "in:situs", "in:locationaddress"],
    "addr_no": ["eq:adrno", "eq:houseno", "eq:housenumber", "eq:streetnumber", "eq:locationnumber",
                "eq:addrno", "eq:stno"],
    "addr_dir": ["eq:adrdir", "eq:streetdirection", "eq:predir", "eq:locationdirection"],
    "addr_street": ["eq:adrstr", "eq:streetname", "eq:street", "eq:locationstreet"],
    "addr_suffix": ["eq:adrsuf", "eq:streetsuffix", "eq:suffix", "eq:locationsuffix", "eq:streettype"],
    "city": ["eq:city", "eq:sitecity", "eq:parcity", "eq:propertycity", "eq:locationcity", "eq:cityname",
             "eq:municipality", "in:sitecity", "in:propertycity"],
    "zip": ["eq:zipcode", "eq:zip", "eq:zipcd", "eq:parzip", "eq:sitezip", "eq:propertyzip",
            "eq:locationzip", "in:sitezip", "in:propertyzip", "in:parzip"],
    "mail_address": ["eq:owneraddress1", "eq:mailaddress", "eq:mailingaddress", "eq:taxmailingaddress",
                     "eq:addr1", "eq:owneraddress", "eq:taxaddress", "eq:mailaddr1", "eq:mailingaddress1",
                     "eq:billingaddress", "in:mailingaddress", "in:mailaddress", "in:owneraddress",
                     "in:taxmailingaddr", "in:taxbilladdress"],
    "mail_csz": ["eq:owneraddress2", "eq:mailcitystatezip", "eq:citystatezip", "in:citystatezip"],
    "mail_city": ["eq:mailcity", "eq:mailingcity", "eq:ownercity", "eq:taxmailingcity", "eq:taxcity",
                  "in:mailcity", "in:mailingcity", "in:ownercity"],
    "mail_state": ["eq:mailstate", "eq:mailingstate", "eq:ownerstate", "eq:statecode", "eq:taxstate",
                   "in:mailstate", "in:mailingstate", "in:ownerstate"],
    "mail_zip": ["eq:mailzip", "eq:mailingzip", "eq:ownerzip", "eq:zip1", "eq:taxzip", "eq:taxmailingzip",
                 "in:mailzip", "in:mailingzip", "in:ownerzip"],
    "year_built": ["eq:yearbuilt", "eq:yrblt", "eq:yearblt", "eq:builtyear", "in:yearbuilt", "in:yrblt"],
    "sqft": ["eq:sfla", "eq:finishedsqft", "eq:livingarea", "eq:sqft", "eq:squarefeet", "eq:totalsqft",
             "eq:finishedsquarefeet", "eq:grosslivingarea", "eq:resflrarea", "in:finishedsq", "in:livingarea",
             "in:sqft", "in:squarefe"],
    "beds": ["eq:rmbed", "eq:bedrooms", "eq:beds", "eq:numbedrooms", "in:bedroom"],
    "homestead": ["eq:ishomestead", "eq:homestead", "eq:ownerocc", "eq:owneroccupied", "eq:ooc",
                  "eq:owneroccupancycredit", "in:homestead", "in:owneroccup"],
    "tax_year": ["eq:taxyr", "eq:taxyear", "eq:year"],
}


def norm(h) -> str:
    return re.sub(r"[^a-z0-9]", "", str(h or "").lower())


def overrides(source: str) -> dict[str, str]:
    try:
        data = json.loads(config.FIELD_OVERRIDES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {**data.get("*", {}), **data.get(source, {})}


def detect(headers, source: str, wanted=None) -> dict[str, str]:
    """{canonical field: exact header} for the fields found in `headers`."""
    headers = [h for h in headers if h is not None and str(h).strip()]
    by_norm = {}
    for h in headers:
        by_norm.setdefault(norm(h), h)
    pinned = overrides(source)
    used: set[str] = set()
    out: dict[str, str] = {}
    for fld in (wanted or RULES):
        if fld in pinned and pinned[fld] in headers:
            out[fld] = pinned[fld]
            used.add(pinned[fld])
            continue
        for rule in RULES.get(fld, []):
            kind, alias = rule.split(":", 1)
            hit = None
            if kind == "eq":
                h = by_norm.get(alias)
                hit = h if h is not None and h not in used else None
            else:
                hit = next((h for n, h in by_norm.items() if alias in n and h not in used), None)
            if hit is not None:
                out[fld] = hit
                used.add(hit)
                break
    log.info("[%s] columns: %s", source, ", ".join(f"{k}={v!r}" for k, v in out.items()))
    return out


def pick(row: dict, cols: dict[str, str], fld: str):
    h = cols.get(fld)
    return row.get(h) if h is not None else None
