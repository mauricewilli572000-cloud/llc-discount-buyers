"""Tests on synthetic files laid out like each county's real exports (dates relative to today)."""
from __future__ import annotations

import csv
import datetime as dt
import json

import openpyxl
import pytest

import config
from src import analyze, export, fields, lookalike
from src.counties import cuyahoga, franklin, hamilton, summit
from src.model import Parcel
from src.normalize import iso_date, is_entity, is_llc, luc3, name_key

TODAY = dt.date.today()


def d(days_ago: int, fmt="%m/%d/%Y") -> str:
    return (TODAY - dt.timedelta(days=days_ago)).strftime(fmt)


@pytest.fixture(autouse=True)
def no_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FIELD_OVERRIDES", tmp_path / "none.json")


# ---------------------------------------------------------------- helpers
def test_llc_and_entity_detection():
    for n in ("ABC HOMES LLC", "Buckeye Props, L.L.C.", "SMITH HOLDINGS L L C", "XYZ LIMITED LIABILITY CO",
              "OHIOHOUSESLLC"):
        assert is_llc(n), n
    for n in ("SMITH JOHN", "WILLIAMS KLIFFORD & MARY", "MILLCREEK JANE"):
        assert not is_llc(n), n
    assert is_entity("US BANK NATIONAL ASSOCIATION") and is_entity("CITY OF COLUMBUS")
    assert not is_entity("JONES MARY")
    assert name_key("ABC Homes, L.L.C.") == name_key("ABC HOMES LLC")


def test_dates_and_luc():
    assert iso_date("05/01/2026") == "2026-05-01"
    assert iso_date("8-Oct-25") == "2025-10-08"
    assert iso_date(dt.datetime(2026, 3, 4, 0, 0)) == "2026-03-04"
    assert iso_date(1767225600000) == "2026-01-01"            # ArcGIS epoch ms
    assert iso_date(46000) == "2025-12-09"                     # Excel serial
    assert luc3("5100") == "510" and luc3("510 - ONE-FAMILY DWLG") == "510" and luc3(520.0) == "520"


def test_field_detection_prefers_exact_and_respects_overrides(tmp_path, monkeypatch):
    cols = fields.detect(["PARCEL ID", "OwnerName1", "OwnerName2", "LastSaleDate", "LastSaleAmount", "LUC",
                          "LUCDesc"], "t")
    assert cols["parcel"] == "PARCEL ID" and cols["owner"] == "OwnerName1" and cols["owner2"] == "OwnerName2"
    assert cols["luc"] == "LUC" and cols["luc_desc"] == "LUCDesc" and cols["sale_price"] == "LastSaleAmount"
    p = tmp_path / "o.json"
    p.write_text(json.dumps({"t": {"owner": "OwnerName2"}}))
    monkeypatch.setattr(config, "FIELD_OVERRIDES", p)
    assert fields.detect(["OwnerName1", "OwnerName2"], "t")["owner"] == "OwnerName2"


# ---------------------------------------------------------------- core rules
def mk(**kw):
    base = dict(county="Franklin", parcel="1", address="1 MAIN ST", city="COLUMBUS", zip="43205", owner="JOE",
                luc="510", market_value=100_000, sale_date=d(30, "%Y-%m-%d"), sale_price=40_000)
    base.update(kw)
    return Parcel(**base)


def test_hit_rules():
    parcels = [
        mk(parcel="hit", owner="FLIP IT LLC"),                                      # 40% of value -> hit
        mk(parcel="person", owner="SMITH JOHN"),                                    # not an LLC
        mk(parcel="fair", owner="FLIP IT LLC", sale_price=80_000),                  # 80% -> no
        mk(parcel="old", owner="FLIP IT LLC", sale_date=d(300, "%Y-%m-%d")),         # outside 6 months
        mk(parcel="zero", owner="FLIP IT LLC", sale_price=0),                       # $0 transfer
        mk(parcel="hidden-bundle", owner="BIG LLC", sale_parcels=3),                 # can't see the others
        mk(parcel="grantee", owner="NEW OWNER JANE", buyer="GRANTEE HOMES LLC"),    # grantee field wins
    ]
    hits, stats = analyze.find_hits(parcels, TODAY)
    assert {h["parcel"] for h in hits} == {"hit", "grantee"}
    h = next(h for h in hits if h["parcel"] == "hit")
    assert h["price_to_value"] == 0.4 and h["discount_pct"] == 60.0 and h["equity_gap"] == 60_000
    assert stats["skipped_nominal_price"] == 1 and stats["skipped_bundle_unknown"] == 1


def test_bundle_uses_combined_value():
    # one $90k deed for two $100k houses: 45% of combined value -> both are hits
    a = mk(parcel="a", owner="TWO PACK LLC", sale_price=90_000)
    b = mk(parcel="b", owner="TWO PACK LLC", sale_price=90_000)
    hits, _ = analyze.find_hits([a, b], TODAY)
    assert len(hits) == 2 and all("bundle of 2" in h["flags"] for h in hits)
    assert hits[0]["price_to_value"] == 0.45
    # same deed for two $60k houses: 75% -> not hits
    a.market_value = b.market_value = 60_000
    assert analyze.find_hits([a, b], TODAY)[0] == []


def test_calibration_rescales_taxable_values():
    ps = [mk(parcel=str(i), sale_price=100_000, market_value=35_000) for i in range(40)]
    assert analyze.calibrate_values(ps, "X") == pytest.approx(1 / 0.35)
    assert ps[0].market_value == 100_000
    ps = [mk(parcel=str(i), sale_price=100_000, market_value=95_000) for i in range(40)]
    assert analyze.calibrate_values(ps, "X") == 1.0


def test_lookalikes_and_buyers():
    hit = mk(parcel="h", owner="FLIP IT LLC", sqft=1200, year_built=1925, mail_address="9 OFFICE RD",
             mail_city="DUBLIN", mail_state="OH", mail_zip="43017")
    twin = mk(parcel="twin", owner="DOE JANE", sqft=1250, year_built=1928, sale_date="1998-06-01",
              sale_price=30_000, mail_address="44 ELM ST", mail_city="TAMPA", mail_state="FL",
              homestead=False)
    occupied = mk(parcel="occ", owner="ROE RICK", sqft=1250, year_built=1928, sale_date="2019-06-01",
                  sale_price=90_000, mail_address="1 MAIN ST", homestead=True)
    corp = mk(parcel="corp", owner="OTHER INVESTOR LLC", sale_date="1998-06-01")
    elsewhere = mk(parcel="far", owner="DOE JOHN", zip="43085", sale_date="1998-06-01")
    hits, _ = analyze.find_hits([hit], TODAY)
    looks = lookalike.find([hit, twin, occupied, corp, elsewhere], hits, TODAY)
    assert [r["parcel"] for r in looks] == ["twin"]
    t = looks[0]
    assert "absentee" in t["flags"] and "out of state" in t["flags"] and any("owned" in f for f in t["flags"])
    assert t["similar_parcel"] == "h" and t["score"] >= config.LOOKALIKE_MIN_SCORE
    b = analyze.buyers(hits)
    assert b[0]["buyer"] == "FLIP IT LLC" and b[0]["purchases"] == 1 and b[0]["mail_city"] == "DUBLIN"


def test_export_keeps_date_added(tmp_path):
    p = tmp_path / "x.json"
    rows = [{"key": "a"}, {"key": "b"}]
    export.write_json(p, [{"key": "a", "date_added": "2026-01-01"}], {})
    assert export.stamp(rows, p, "2026-11-11") == 1
    assert rows[0]["date_added"] == "2026-01-01" and rows[1]["date_added"] == "2026-11-11"
    assert export.split_name("WILLIAMS KLIFFORD") == ("Klifford", "Williams")
    assert export.split_name("KASIKILE, MUBYAYI") == ("Mubyayi", "Kasikile")


# ---------------------------------------------------------------- county loaders
def write_tab(path, header, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t", quoting=csv.QUOTE_ALL)
        w.writerow(header)
        w.writerows(rows)
    return path


def test_franklin_loader(tmp_path):
    parcel = write_tab(tmp_path / "Parcel.txt",
                       ["PARCEL ID", "SiteAddress", "OwnerName1", "OwnerName2", "OwnerAddress1", "OwnerAddress2",
                        "TaxpayerAddress1", "TaxpayerAddress2", "CDQ", "IsHomestead", "LUC", "LUCDesc", "ZipCode",
                        "City", "LastSaleDate", "LastSaleAmount", "BankCode", "ExemptStatus"],
                       [["010-000034-00", "1645 E GREENWAY AV, COLUMBUS, OH 43203", "BUCKEYE FLIPS LLC", "",
                         "100 MAIN ST", "DUBLIN OH 43017-1234", "", "", "", "False", "510",
                         "510 - ONE-FAMILY DWLG", "43203", "COLUMBUS", d(40), "38000.00", "", ""],
                        ["010-000035-00", "1649 E GREENWAY AV, COLUMBUS, OH 43203", "JONES MARY", "",
                         "77 PINE RD", "ATLANTA GA 30301", "", "", "", "False", "510", "510 - ONE-FAMILY DWLG",
                         "43203", "COLUMBUS", "06/15/2001", "52000.00", "", ""],
                        ["010-000036-00", "1 SHOP ST, COLUMBUS, OH 43203", "SHOP LLC", "", "", "", "", "", "",
                         "False", "430", "430 - RESTAURANT", "43203", "COLUMBUS", d(20), "1000.00", "", ""]])
    value = write_tab(tmp_path / "Value.txt", ["Parcel Id", "TaxYear", "ValueType", "MarketLand", "MarketImpr"],
                      [["010-000034-00", "2025", "BASE", "20000", "80000"],
                       ["010-000034-00", "2024", "BASE", "10000", "50000"],
                       ["010-000035-00", "2025", "BASE", "20000", "75000"]])
    ps = franklin.load(tmp_path, "", files={"franklin_parcel": parcel, "franklin_value": value})
    assert [p.parcel for p in ps] == ["010-000034-00", "010-000035-00"]       # restaurant dropped
    p = ps[0]
    assert (p.address, p.city, p.zip, p.market_value) == ("1645 E GREENWAY AV", "COLUMBUS", "43203", 100_000)
    assert (p.mail_city, p.mail_state, p.mail_zip, p.homestead) == ("DUBLIN", "OH", "43017", False)
    hits, _ = analyze.find_hits(ps, TODAY)
    assert len(hits) == 1 and hits[0]["price_to_value"] == 0.38
    looks = lookalike.find(ps, hits, TODAY)
    assert [r["parcel"] for r in looks] == ["010-000035-00"]


def test_cuyahoga_loader_rows():
    ms = int(dt.datetime.combine(TODAY - dt.timedelta(days=15), dt.time()).timestamp() * 1000)
    rows = [
        {"OBJECTID": 1, "parcelpin": "12322045", "deeded_owner": "OLD OWNER", "grantee": "CLE HOUSES LLC",
         "grantor": "SMITH, BOB", "transfer_date": ms, "sales_amount": 20000.0, "par_addr_all": "4918 MCBRIDE AVE",
         "par_city": "CLEVELAND", "par_zip": 44127.0, "certified_tax_luc": "5100", "certified_tax_total": 21000.0,
         "gross_certified_total": None, "tax_luc_description": "SINGLE FAMILY DWELLING"},
        {"OBJECTID": 2, "parcelpin": "12322046", "deeded_owner": "OFFICE BLDG LLC", "grantee": "", "grantor": "",
         "transfer_date": ms, "sales_amount": 5000.0, "par_addr_all": "1 E 55 ST", "par_city": "CLEVELAND",
         "par_zip": 44127.0, "certified_tax_luc": "4470", "certified_tax_total": 210000.0},
    ]
    ps = cuyahoga.load(None, "", rows=rows)
    assert len(ps) == 1
    p = ps[0]
    assert p.buyer_name == "CLE HOUSES LLC" and p.zip == "44127" and p.luc == "510"
    assert p.market_value == pytest.approx(60_000)                # 35% taxable -> market
    assert analyze.find_hits(ps, TODAY)[0][0]["price_to_value"] == pytest.approx(0.333, abs=0.001)


def test_hamilton_loader(tmp_path):
    def xlsx(name, header, rows, title=True):
        wb = openpyxl.Workbook()
        ws = wb.active
        if title:
            ws.append(["Hamilton County Auditor - export"])
            ws.append([])
        ws.append(header)
        for r in rows:
            ws.append(r)
        path = tmp_path / name
        wb.save(path)
        return path

    sales = xlsx("HistoricSalesExport.xlsx", ["Parcel Number", "Sale Date", "Sale Amount", "Deed Type",
                                              "Number of Parcels"],
                 [["241-0001-0127-00", TODAY - dt.timedelta(days=50), 25000, "SH", 1],
                  ["241-0001-0127-00", dt.datetime(2010, 1, 5), 61000, "WD", 1],
                  ["241-0001-0128-00", dt.datetime(1999, 3, 1), 40000, "WD", 1]])
    tax = xlsx("Monthly_tax_information.xlsx",
               ["Parcel Number", "Owner Name 1", "Owner Address", "Owner City", "Owner State", "Owner Zip",
                "Property Location", "Land Use Code", "Market Land Value", "Market Improvement Value",
                "Appraisal Area"],
               [["241-0001-0127-00", "QUEEN CITY HOMES LLC", "5 VINE ST", "CINCINNATI", "OH", "45202",
                 "105 SIXTY NINTH ST", 520, 10000, 70000, "04601"],
                ["241-0001-0128-00", "WAY IMOGENE", "408 WELLESLEY AVE", "CINCINNATI", "OH", "45224",
                 "107 SIXTY NINTH ST", 520, 9000, 66000, "04601"]])
    bldg = xlsx("bldginfo.xlsx", ["Parcel Number", "Year Built", "Finished Sq Ft", "Bedrooms"],
                [["241-0001-0127-00", 1895, 1487, 4], ["241-0001-0128-00", 1900, 1500, 4]], title=False)
    ps = hamilton.load(tmp_path, "", files={"hamilton_sales": sales, "hamilton_tax": tax,
                                            "hamilton_building": bldg})
    p = {x.parcel: x for x in ps}["241-0001-0127-00"]
    assert p.sale_price == 25000 and p.market_value == 80000 and p.year_built == 1895 and p.nbhd == "04601"
    hits, _ = analyze.find_hits(ps, TODAY)
    assert len(hits) == 1 and "sheriff sale" in hits[0]["flags"]
    looks = lookalike.find(ps, hits, TODAY)
    assert looks and looks[0]["parcel"] == "241-0001-0128-00" and looks[0]["area"] == "neighborhood 04601"


def test_summit_loader(tmp_path):
    def wcsv(name, header, rows):
        path = tmp_path / name
        with path.open("w", newline="") as f:
            w = csv.writer(f, quoting=csv.QUOTE_ALL)
            w.writerow(header)
            w.writerows(rows)
        return path

    sales = wcsv("SC706_SALES.csv", ["PARCEL", "SALEDT", "PRICE", "INSTRTYP", "NOPAR", "OLDOWN", "OWN1"],
                 [["0101379", d(60, "%d-%b-%Y").upper(), "30000", "WD", "1", "SMITH BOB", ""],
                  ["0101379", "01-JAN-2012", "90000", "WD", "1", "", ""]])
    own = wcsv("SC700_OWNDAT.csv", ["PARCEL", "TAXYR", "OWN1", "OWN2", "ADDR1", "CITYNAME", "STATECODE", "ZIP1"],
               [["0101379", "2026", "RUBBER CITY RENTALS LLC", "", "1 MAIN ST", "AKRON", "OH", "44308"]])
    asmt = wcsv("SC703_ASMT.csv", ["PARCEL", "TAXYR", "APRLAND", "APRBLDG", "APRTOT"],
                [["0101379", "2026", "15000", "75000", "90000"], ["0101379", "2025", "1", "1", "2"]])
    pardat = wcsv("SC705_PARDAT.csv", ["TAPE CREATE DATE", "PARCEL", "TAXYR", "SEQ", "ALT-ID", "ADRNO", "ADRADD",
                                       "ADRDIR", "ADRSTR", "ADRSUF", "LUC", "ZIPCD", "USER2", "UDATE1", "CITY"],
                  [["30-OCT-2026", "0101379", "2026", "0", "X", "120", "", "", "JOSEPH", "AVE", "510", "44203",
                    "", "", "BARBERTON"]])
    ps = summit.load(tmp_path, "", files={"summit_sales": sales, "summit_owndat": own, "summit_asmt": asmt,
                                          "summit_pardat": pardat})
    assert len(ps) == 1
    p = ps[0]
    assert (p.address, p.zip, p.owner, p.market_value, p.sale_price) == (
        "120 JOSEPH AVE", "44203", "RUBBER CITY RENTALS LLC", 90000, 30000)
    assert analyze.find_hits(ps, TODAY)[0][0]["price_to_value"] == pytest.approx(0.333, abs=0.001)


# ---------------------------------------------------------------- end to end
def test_run_pipeline_end_to_end(tmp_path, monkeypatch):
    import run_pipeline
    from src.counties import cuyahoga as cu, franklin as fr, hamilton as ha, summit as su

    for name in ("HITS_JSON", "LOOKALIKES_JSON", "BUYERS_JSON", "HITS_CSV", "GHL_LOOKALIKES_CSV", "BUYERS_CSV",
                 "STATE_JSON"):
        monkeypatch.setattr(config, name, tmp_path / getattr(config, name).name)
    monkeypatch.setattr(config, "RAW_DIR", tmp_path / "raw")
    parcels = [mk(parcel="h", owner="FLIP IT LLC", mail_address="9 OFFICE RD", mail_city="DUBLIN",
                  mail_state="OH", mail_zip="43017"),
               mk(parcel="t", owner="DOE JANE", sale_date="1990-01-01", mail_address="1 X ST", mail_state="FL")]
    monkeypatch.setattr(fr, "load", lambda raw, since: [Parcel(**p.to_dict()) for p in parcels])

    def boom(raw, since):
        raise RuntimeError("site down")
    for m in (cu, ha, su):
        monkeypatch.setattr(m, "load", boom)
    assert run_pipeline.main([]) == 0
    hits = json.loads(config.HITS_JSON.read_text())
    assert hits["meta"]["counties"]["Franklin"]["status"] == "ok"
    assert hits["meta"]["counties"]["Hamilton"]["status"] == "error"
    assert hits["meta"]["counties"]["Shelby"]["status"] == "disabled"
    assert [r["parcel"] for r in hits["records"]] == ["h"]
    assert [r["parcel"] for r in json.loads(config.LOOKALIKES_JSON.read_text())["records"]] == ["t"]
    assert "FLIP IT LLC" in config.BUYERS_CSV.read_text(encoding="utf-8-sig")
    assert "Doe" in config.GHL_LOOKALIKES_CSV.read_text(encoding="utf-8-sig")
    # second run: nothing new, date_added kept
    assert run_pipeline.main([]) == 0
    assert json.loads(config.HITS_JSON.read_text())["meta"]["new_hits"] == 0


# ---------------------------------------------------------------- real layouts (from discover.py, Nov 2026)
CUY_REAL = ['ObjectID', 'parcel_id', 'myplaceppn', 'book_page', 'parcel_year', 'parcel_owner', 'second_owner',
            'grantor', 'grantee', 'parcel_addr', 'parcel_predir', 'parcel_street', 'parcel_suffix', 'parcel_unit',
            'parcel_city', 'parcel_zip', 'par_addr_all', 'mail_name', 'mail_addr_street', 'mail_unit_no',
            'mail_city', 'mail_state', 'mail_zip', 'mail_country', 'last_transfer_date', 'last_sales_amount',
            'tax_luc', 'tax_luc_description', 'ext_luc', 'property_class', 'prop_class_desc', 'neighborhood_code',
            'certified_tax_total', 'gross_certified_total', 'tax_market_total', 'homestead_flag',
            'total_res_liv_area', 'max_age']


def test_cuyahoga_real_columns():
    cols = fields.detect(CUY_REAL, "cuyahoga_taxparcel")
    assert cols["zip"] == "parcel_zip" and cols["city"] == "parcel_city" and cols["luc"] == "tax_luc"
    assert cols["mail_address"] == "mail_addr_street" and cols["sqft"] == "total_res_liv_area"
    assert cols["sale_date"] == "last_transfer_date" and cols["buyer"] == "grantee"


HAM_TAX = ['parcel_number', '2_5_flag', 'homestead_flag', 'book', 'page', 'property_id', 'mltown', 'prop_class_code',
           'class_description', 'appraisal_area', 'area_description', 'owner_name_1', 'owner_name_2',
           'owner_address_1', 'owner_address_2', 'owner_city', 'owner_state', 'owner_zip', 'location_house_number',
           'location_street_direction', 'location_street_name', 'location_street_suffix', 'location_city',
           'location_state', 'location_zip', 'mailing_name_1', 'mailing_name_2', 'mailing_address_1',
           'mailing_address_2', 'mailing_city', 'mailing_state', 'mailing_zip', 'transfer_date', 'sale_amount',
           'num_parcels', 'sale_type', 'previous_owner_name_1', 'market_land_value', 'market_impr_value',
           'total_market_value']


def test_hamilton_real_layout(tmp_path, monkeypatch):
    ov = tmp_path / "ov.json"
    ov.write_text((config.ROOT / "data" / "field_overrides.json").read_text())
    monkeypatch.setattr(config, "FIELD_OVERRIDES", ov)

    def xlsx(name, header, rows):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(header)
        for r in rows:
            ws.append(r)
        wb.save(tmp_path / name)
        return tmp_path / name

    def tax_row(pid, owner, no, mail_no, sold, price, value, mail_state="OH"):
        row = dict.fromkeys(HAM_TAX)
        row.update({"parcel_number": pid, "homestead_flag": "N", "prop_class_code": 510,
                    "class_description": "SINGLE FAMILY DWLG", "appraisal_area": "00100", "owner_name_1": owner,
                    "owner_address_1": f"{mail_no} SUSSEX AVE", "location_house_number": no,
                    "location_street_name": "SUSSEX", "location_street_suffix": "AVE",
                    "mailing_address_1": f"{mail_no} SUSSEX AVE", "mailing_city": "CINCINNATI",
                    "mailing_state": mail_state, "mailing_zip": 452301403, "transfer_date": sold,
                    "sale_amount": price, "num_parcels": 1, "sale_type": "WD - Warranty Deed",
                    "market_land_value": 28370, "market_impr_value": value - 28370, "total_market_value": value})
        return [row[h] for h in HAM_TAX]

    recent = dt.datetime.combine(TODAY - dt.timedelta(days=40), dt.time())
    tax = xlsx("tax.xlsx", HAM_TAX, [
        tax_row("0010001000100", "SUSSEX FLIPS LLC", 2327, 2327, recent, 60000, 236790),
        tax_row("0010001000200", "JOSEVAS MARY JC", 2331, 900, dt.datetime(2001, 1, 2), 90000, 230000, "FL"),
    ])
    sales = xlsx("sales.xlsx", ["parcel_number", "use_code", "number_of_parcels", "owner_name_1", "date_of_sale",
                                "instrument_type", "appraisal_area", "previous_owner", "sale_price"],
                 [[10001000100, 510, 1, "SUSSEX FLIPS LLC", recent, "SH - Sheriff Deed", 100, "DOE JOHN", 60000]])
    bldg = xlsx("bldg.xlsx", ["PARCELID", "LIVE_FSQFT", "SQFT", "YEARBUILT"],
                [["0010001000100", 1314, None, 1996], ["0010001000200", 1300, None, 1994]])
    ps = hamilton.load(tmp_path, "", files={"hamilton_sales": sales, "hamilton_tax": tax, "hamilton_building": bldg})
    assert len(ps) == 2
    p = {x.parcel: x for x in ps}["0010001000100"]
    assert (p.address, p.zip, p.luc, p.market_value, p.sqft, p.year_built) == (
        "2327 SUSSEX AVE", "45230", "510", 236790, 1314, 1996)
    assert p.seller == "DOE JOHN"
    hits, _ = analyze.find_hits(ps, TODAY)
    assert len(hits) == 1 and "sheriff sale" in hits[0]["flags"]
    looks = lookalike.find(ps, hits, TODAY)
    assert [r["parcel"] for r in looks] == ["0010001000200"] and "out of state" in looks[0]["flags"]


# ---------------------------------------------------------------- location fill, junk addresses, Zillow
def test_location_fill_from_owner_and_neighbors():
    from src import location
    occ = mk(parcel="1", address="100 ELM ST", zip="", city="", mail_address="100 ELM ST", mail_zip="44306",
             mail_city="AKRON")
    near = mk(parcel="2", address="112 ELM ST", zip="", city="", mail_address="9 FAR RD", mail_zip="90210")
    far_away = mk(parcel="3", address="9000 ELM ST", zip="", city="")
    other = mk(parcel="4", address="5 OAK ST", zip="", city="")
    assert location.fill([occ, near, far_away, other]) == 2
    assert (occ.zip, occ.city, near.zip, near.city) == ("44306", "AKRON", "44306", "AKRON")
    assert far_away.zip == "" and other.zip == ""


def test_junk_one_line_address_uses_parts():
    from src import build
    cols = {"address": "LOCATION", "addr_no": "ADRNO", "addr_street": "ADRSTR", "addr_suffix": "ADRSUF"}
    assert build.address({"LOCATION": "OW", "ADRNO": "189", "ADRSTR": "PEMBROKE", "ADRSUF": "RD"}, cols) == \
        "189 PEMBROKE RD"
    assert build.address({"LOCATION": "12 MAIN ST", "ADRNO": "12"}, cols) == "12 MAIN ST"


def test_zillow_attach():
    from src import zillow
    rows = [{"county": "Franklin", "parcel": "1", "sale_price": 50000, "discount_pct": 60.0, "sqft": None},
            {"county": "Franklin", "parcel": "2"}]
    data = {"Franklin|1": {"zestimate": 200000, "sqft": 900, "checked": "2026-11-14"}}
    assert zillow.attach(rows, data) == 1
    assert rows[0]["pct_of_zestimate"] == 25.0 and rows[0]["sqft"] == 900 and "zillow" not in rows[1]


SUM_PARDAT = ['TAPE CREATE DATE', 'PARCEL', 'TAXYR', 'SEQ', 'ALT-ID', 'ADRNO', 'ADRADD', 'ADRDIR', 'ADRSTR', 'ADRSUF',
              'NBHDP', 'NBHDS', 'CLASS', 'LUC', 'LUCM', 'LVU', 'TIEBACK', 'LANDISC', 'ACRES', 'STREET1', 'STREET2',
              'TRAFFIC', 'TOP01', 'TOP02', 'UTIL1', 'UTIL2', 'UTIL3', 'CARDS', 'PARTIAL', 'BLDGROSD', 'BLDGROSV',
              'MBD', 'MBLDV', 'NOTECD1', 'NOTECD2', 'NOTE1', 'NOTE2', 'DEACTIVATE', 'WEN', 'LOCATION', 'FRONTING',
              'ZIPCD', 'ADRSUF2', 'USER1', 'USER2', 'USER3', 'USER4', 'USER9', 'CITY', 'Rental_Registration',
              'UDATE1', 'UDATE2', 'UDATE3']


def test_summit_real_layout(tmp_path, monkeypatch):
    ov = tmp_path / "ov.json"
    ov.write_text((config.ROOT / "data" / "field_overrides.json").read_text())
    monkeypatch.setattr(config, "FIELD_OVERRIDES", ov)

    def wcsv(name, header, rows):
        path = tmp_path / name
        with path.open("w", newline="") as f:
            w = csv.writer(f, quoting=csv.QUOTE_ALL)
            w.writerow(header)
            w.writerows(rows)
        return path

    def pardat(pid, no, dirn, street, suf):
        row = dict.fromkeys(SUM_PARDAT, "")
        row.update({"TAPE CREATE DATE": "30-OCT-2026", "PARCEL": pid, "TAXYR": "2027", "SEQ": "0", "ADRNO": no,
                    "ADRDIR": dirn, "ADRSTR": street, "ADRSUF": suf, "NBHDP": "30200", "CLASS": "R", "LUC": "510",
                    "WEN": "SHED/DECK I", "LOCATION": "21", "ZIPCD": "12-OC", "USER2": "44203",
                    "USER4": "07-OCT-19", "CITY": "                    ", "UDATE1": "BARBERTON"})
        return [row[h] for h in SUM_PARDAT]

    sold = d(45, "%d-%b-%Y").upper()
    sales = wcsv("s.csv", ['TAPE CREATE DATE', 'PARCEL', 'TRANSNO', 'OLDOWN', 'OWN1', 'SALEDATE', 'PRICE', 'SALETYPE'],
                 [["30-OCT-2026", "0100001", "1", "BALL DOUGLAS R", "MAGIC CITY HOMES LLC", sold, "40000", ""],
                  ["30-OCT-2026", "0100002", "2", "X", "WAGNER THOMAS", "30-DEC-1999", "50000", ""]])
    own = wcsv("o.csv", ['TAPE CREATE DATE', 'PARID', 'TAXYR', 'SEQ', 'OWNER1', 'OWNER2', 'ADDRESS_1', 'ADDRESS_2',
                         'OWNER ZIPCD1', 'OWNER ZIPCD2', 'CITYNAME', 'STATECODE'],
               [["30-OCT-2026", "0100001", "2027", "0", "MAGIC CITY HOMES LLC", "", "1 MAIN ST", "", "44308", "",
                 "AKRON", "  "],
                ["30-OCT-2026", "0100002", "2027", "0", "WAGNER THOMAS", "", "55 PALM AVE", "", "33101", "",
                 "MIAMI", "FL"]])
    asmt = wcsv("a.csv", ['TAPE CREATE DATE', 'PARCEL', 'TAXYR', 'SEQ', 'APRLAND', 'APRBLDG', 'LUC'],
                [["30-OCT-2026", "0100001", "2027", "0", "20000", "80000", "510"],
                 ["30-OCT-2026", "0100002", "2027", "0", "20000", "75000", "510"]])
    par = wcsv("p.csv", SUM_PARDAT, [pardat("0100001", "168", "SW", "31ST", "ST"),
                                    pardat("0100002", "176", "SW", "31ST", "ST")])
    ps = summit.load(tmp_path, "", files={"summit_sales": sales, "summit_owndat": own, "summit_asmt": asmt,
                                          "summit_pardat": par})
    p = {x.parcel: x for x in ps}
    a, b = p["0100001"], p["0100002"]
    assert (a.address, a.zip, a.city, a.buyer, a.market_value) == (
        "168 SW 31ST ST", "44203", "BARBERTON", "MAGIC CITY HOMES LLC", 100000)
    assert (a.mail_address, a.mail_state, b.mail_state) == ("1 MAIN ST", "OH", "FL")
    hits, _ = analyze.find_hits(ps, TODAY)
    assert len(hits) == 1
    looks = lookalike.find(ps, hits, TODAY)
    assert [r["parcel"] for r in looks] == ["0100002"] and "out of state" in looks[0]["flags"]
