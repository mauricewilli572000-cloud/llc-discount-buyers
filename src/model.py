"""One parcel with its most recent sale - the shape every county loader produces."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Parcel:
    county: str
    parcel: str
    address: str = ""
    city: str = ""
    zip: str = ""
    owner: str = ""              # current owner (= buyer when the last sale is the newest transfer)
    owner2: str = ""
    buyer: str = ""              # grantee on the sale record, when the county publishes it
    seller: str = ""             # grantor, when published
    mail_address: str = ""
    mail_city: str = ""
    mail_state: str = ""
    mail_zip: str = ""
    luc: str = ""                # 3-digit Ohio land use code
    luc_desc: str = ""
    nbhd: str = ""               # neighborhood / appraisal area, when published
    sale_date: str = ""          # ISO yyyy-mm-dd
    sale_price: float | None = None
    deed_type: str = ""
    sale_parcels: int = 1        # parcels sold together on one price
    market_value: float | None = None
    year_built: int | None = None
    sqft: float | None = None
    beds: int | None = None
    homestead: bool | None = None
    url: str = ""
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def buyer_name(self) -> str:
        return self.buyer or self.owner
