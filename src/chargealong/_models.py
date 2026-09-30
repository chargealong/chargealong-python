"""The shapes the API returns.

Every model is a frozen dataclass with a ``from_json``, and every one ignores a
field it does not know: the service may add one before this library learns the
name, and a client that raises on an unrecognised key turns a compatible change
at the service into an outage in somebody's nightly job.

Field names are the wire's own, so the API reference and this code agree.
Rows that carry a ``path`` also have a ``url``: the page on chargealong.io that
row names, with no second request.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Any, Mapping, Optional, Tuple

#: The site the paths belong to.
SITE = "https://chargealong.io"

#: Connector standards the API filters by, as slugs.
CONNECTORS = ("ccs2", "chademo", "type-2", "nacs", "ccs1", "type-1", "gbt")

# Field names per class, worked out once rather than per row.
_KNOWN: "dict[type, frozenset]" = {}


def _only_known(cls, raw: Any) -> dict:
    known = _KNOWN.get(cls)
    if known is None:
        known = _KNOWN[cls] = frozenset(f.name for f in fields(cls))
    if not isinstance(raw, Mapping):
        return {}
    return {k: v for k, v in raw.items() if k in known}


def _map(raw: Any) -> Mapping[str, Any]:
    return raw if isinstance(raw, Mapping) else {}


def _rows(cls, raw: Any) -> tuple:
    """A list of rows, skipping anything that is not an object."""
    if not isinstance(raw, list):
        return ()
    return tuple(cls.from_json(r) for r in raw if isinstance(r, Mapping))


def _strings(raw: Any) -> "tuple[str, ...]":
    if not isinstance(raw, list):
        return ()
    return tuple(s for s in raw if isinstance(s, str))


def _stamp(value: Any) -> "datetime | None":
    """RFC 3339 to datetime, or None.

    A timestamp that will not parse is one field of one row; dropping it beats
    refusing a record that is otherwise complete. Python before 3.11 cannot
    read more than six fractional digits or a Z, so both are tidied first.
    """
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    if "." in text:
        head, _, rest = text.partition(".")
        digits = ""
        while rest and rest[0].isdigit():
            digits, rest = digits + rest[0], rest[1:]
        text = f"{head}.{digits[:6].ljust(6, '0')}{rest}"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def site_path(path: Any) -> bool:
    """A path on the site: one leading slash, not two, and no scheme."""
    return isinstance(path, str) and path.startswith("/") and not path.startswith("//") and "://" not in path


def _url(path: Any) -> str:
    return SITE + path if site_path(path) else ""


# -- places ---------------------------------------------------------------


@dataclass(frozen=True)
class Country:
    iso2: str = ""
    slug: str = ""
    name: str = ""
    site_count: int = 0

    @property
    def url(self) -> str:
        return f"{SITE}/en/{self.slug}/" if self.slug else ""

    @classmethod
    def from_json(cls, raw: Any) -> "Country":
        return cls(**_only_known(cls, raw))


@dataclass(frozen=True)
class Region:
    slug: str = ""
    #: The state or territory code where the country has them: VIC, NSW.
    code: str = ""
    name: str = ""
    site_count: int = 0

    @classmethod
    def from_json(cls, raw: Any) -> "Region":
        return cls(**_only_known(cls, raw))


@dataclass(frozen=True)
class Locality:
    """One suburb or town.

    ``region`` is the region's slug, present where a list spans regions (a
    country's busiest places, a suburb's neighbours). ``distance_km`` is set on
    neighbours.
    """

    slug: str = ""
    name: str = ""
    postcode: str = ""
    time_zone: str = ""
    site_count: int = 0
    region: str = ""
    distance_km: Optional[float] = None

    def url_in(self, country: Country) -> str:
        """The place's page, given the country it is in."""
        if not (country.slug and self.region and self.slug):
            return ""
        return f"{SITE}/en/{country.slug}/{self.region}/{self.slug}/"

    @classmethod
    def from_json(cls, raw: Any) -> "Locality":
        return cls(**_only_known(cls, raw))


# -- sites ----------------------------------------------------------------


@dataclass(frozen=True)
class Cost:
    #: free, paid or unknown.
    kind: str = ""
    has_conditions: bool = False
    #: The price as the source wrote it.
    text: str = ""

    @classmethod
    def from_json(cls, raw: Any) -> "Cost":
        return cls(**_only_known(cls, raw))


@dataclass(frozen=True)
class Site:
    """One charging site: a place with one or more chargers.

    ``network`` is a slug (``chargefox``, ``unbranded`` where there is none) and
    ``network_name`` its display name. ``speed`` is ``ac``, ``fast`` or
    ``ultra-fast``. ``status`` matters: only ``active`` sites are worth sending
    a driver to.

    The fields after ``path`` appear on some answers only: ``distance_km`` on
    nearby and alternatives, the rest on a site's own page.
    """

    public_id: str = ""
    name: str = ""
    network: str = ""
    network_name: str = ""
    operator: str = ""
    address: str = ""
    status: str = ""
    speed: str = ""
    max_kw: float = 0
    plugs: int = 0
    standards: "Tuple[str, ...]" = ()
    cost_kind: str = ""
    lat: float = 0.0
    lng: float = 0.0
    path: str = ""
    distance_km: Optional[float] = None
    usage: str = ""
    cost: Optional[Cost] = None
    last_verified_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @property
    def url(self) -> str:
        return _url(self.path)

    @property
    def distance_m(self) -> Optional[int]:
        return None if self.distance_km is None else round(self.distance_km * 1000)

    @classmethod
    def from_json(cls, raw: Any) -> "Site":
        row = _only_known(cls, raw)
        row["standards"] = _strings(row.get("standards"))
        row["cost"] = Cost.from_json(row["cost"]) if isinstance(row.get("cost"), Mapping) else None
        row["last_verified_at"] = _stamp(row.get("last_verified_at"))
        row["updated_at"] = _stamp(row.get("updated_at"))
        return cls(**row)


@dataclass(frozen=True)
class Connector:
    standard: str = ""
    #: As the source described it: "Type 2 (Socket Only)".
    label: str = ""
    #: ac or dc.
    current: str = ""
    power_kw: float = 0
    quantity: int = 0

    @classmethod
    def from_json(cls, raw: Any) -> "Connector":
        return cls(**_only_known(cls, raw))


@dataclass(frozen=True)
class Source:
    """Where a site's record came from, and the licence it came under."""

    key: str = ""
    external_id: str = ""
    provider: str = ""
    licence: str = ""
    last_seen_at: Optional[datetime] = None

    @classmethod
    def from_json(cls, raw: Any) -> "Source":
        row = _only_known(cls, raw)
        row["last_seen_at"] = _stamp(row.get("last_seen_at"))
        return cls(**row)


@dataclass(frozen=True)
class Photo:
    id: str = ""
    #: What the photo was given under, for its credit line.
    licence: str = ""
    width: int = 0
    height: int = 0
    created_at: Optional[datetime] = None

    @classmethod
    def from_json(cls, raw: Any) -> "Photo":
        row = _only_known(cls, raw)
        row["created_at"] = _stamp(row.get("created_at"))
        return cls(**row)


@dataclass(frozen=True)
class Review:
    id: int = 0
    name: str = ""
    #: Whether the driver's charge worked: yes or no.
    worked: str = ""
    rating: Optional[int] = None
    body: str = ""
    created_at: Optional[datetime] = None

    @classmethod
    def from_json(cls, raw: Any) -> "Review":
        row = _only_known(cls, raw)
        row["created_at"] = _stamp(row.get("created_at"))
        return cls(**row)


@dataclass(frozen=True)
class ReviewSummary:
    count: int = 0
    average: Optional[float] = None
    #: The newest visible review that charged.
    last_worked_at: Optional[datetime] = None
    #: The newest "the rest of this page is right" from a driver.
    last_checked_at: Optional[datetime] = None

    @classmethod
    def from_json(cls, raw: Any) -> "ReviewSummary":
        row = _only_known(cls, raw)
        row["last_worked_at"] = _stamp(row.get("last_worked_at"))
        row["last_checked_at"] = _stamp(row.get("last_checked_at"))
        return cls(**row)


@dataclass(frozen=True)
class Reviews:
    summary: ReviewSummary = field(default_factory=ReviewSummary)
    #: Newest first.
    recent: "Tuple[Review, ...]" = ()

    @classmethod
    def from_json(cls, raw: Any) -> "Reviews":
        raw = _map(raw)
        return cls(summary=ReviewSummary.from_json(raw.get("summary")), recent=_rows(Review, raw.get("recent")))


@dataclass(frozen=True)
class SiteDetail:
    """One site's page: the site, its connectors and sources, what drivers
    said, and nearby alternatives. ``faster`` is the nearest site in a faster
    tier, when this one is not ultra fast."""

    country: Country = field(default_factory=Country)
    region: Region = field(default_factory=Region)
    locality: Locality = field(default_factory=Locality)
    site: Site = field(default_factory=Site)
    connectors: "Tuple[Connector, ...]" = ()
    sources: "Tuple[Source, ...]" = ()
    alternatives: "Tuple[Site, ...]" = ()
    faster: Optional[Site] = None
    reviews: Reviews = field(default_factory=Reviews)
    photos: "Tuple[Photo, ...]" = ()

    @classmethod
    def from_json(cls, raw: Any) -> "SiteDetail":
        raw = _map(raw)
        faster = raw.get("faster")
        return cls(
            country=Country.from_json(raw.get("country")),
            region=Region.from_json(raw.get("region")),
            locality=Locality.from_json(raw.get("locality")),
            site=Site.from_json(raw.get("site")),
            connectors=_rows(Connector, raw.get("connectors")),
            sources=_rows(Source, raw.get("sources")),
            alternatives=_rows(Site, raw.get("alternatives")),
            faster=Site.from_json(faster) if isinstance(faster, Mapping) else None,
            reviews=Reviews.from_json(raw.get("reviews")),
            photos=_rows(Photo, raw.get("photos")),
        )


# -- browsing -------------------------------------------------------------


@dataclass(frozen=True)
class CountryOverview(Country):
    busiest: "Tuple[Locality, ...]" = ()

    @classmethod
    def from_json(cls, raw: Any) -> "CountryOverview":
        row = _only_known(cls, raw)
        row["busiest"] = _rows(Locality, row.get("busiest"))
        return cls(**row)


@dataclass(frozen=True)
class Overview:
    """What the whole directory holds."""

    sites: int = 0
    ultra_fast: int = 0
    countries: "Tuple[CountryOverview, ...]" = ()

    @classmethod
    def from_json(cls, raw: Any) -> "Overview":
        raw = _map(raw)
        return cls(
            sites=raw.get("sites") or 0,
            ultra_fast=raw.get("ultra_fast") or 0,
            countries=_rows(CountryOverview, raw.get("countries")),
        )


@dataclass(frozen=True)
class CountryDetail:
    country: Country = field(default_factory=Country)
    regions: "Tuple[Region, ...]" = ()
    busiest: "Tuple[Locality, ...]" = ()

    @classmethod
    def from_json(cls, raw: Any) -> "CountryDetail":
        raw = _map(raw)
        return cls(
            country=Country.from_json(raw.get("country")),
            regions=_rows(Region, raw.get("regions")),
            busiest=_rows(Locality, raw.get("busiest")),
        )


@dataclass(frozen=True)
class RegionDetail:
    country: Country = field(default_factory=Country)
    region: Region = field(default_factory=Region)
    localities: "Tuple[Locality, ...]" = ()

    @classmethod
    def from_json(cls, raw: Any) -> "RegionDetail":
        raw = _map(raw)
        return cls(
            country=Country.from_json(raw.get("country")),
            region=Region.from_json(raw.get("region")),
            localities=_rows(Locality, raw.get("localities")),
        )


@dataclass(frozen=True)
class Network:
    #: The network's slug; ``unbranded`` for sites with none.
    key: str = ""
    name: str = ""
    site_count: int = 0
    region_count: int = 0

    @classmethod
    def from_json(cls, raw: Any) -> "Network":
        return cls(**_only_known(cls, raw))


@dataclass(frozen=True)
class NetworkList:
    country: Country = field(default_factory=Country)
    networks: "Tuple[Network, ...]" = ()

    @classmethod
    def from_json(cls, raw: Any) -> "NetworkList":
        raw = _map(raw)
        return cls(country=Country.from_json(raw.get("country")), networks=_rows(Network, raw.get("networks")))


@dataclass(frozen=True)
class NetworkDetail:
    """One network in a country: where it reaches, and a sample of its sites."""

    country: Country = field(default_factory=Country)
    network: Network = field(default_factory=Network)
    regions: "Tuple[Region, ...]" = ()
    busiest: "Tuple[Locality, ...]" = ()
    sites: "Tuple[Site, ...]" = ()

    @classmethod
    def from_json(cls, raw: Any) -> "NetworkDetail":
        raw = _map(raw)
        return cls(
            country=Country.from_json(raw.get("country")),
            network=Network.from_json(raw.get("network")),
            regions=_rows(Region, raw.get("regions")),
            busiest=_rows(Locality, raw.get("busiest")),
            sites=_rows(Site, raw.get("sites")),
        )


@dataclass(frozen=True)
class Facet:
    """A filter and how many sites it keeps: kind connector, network or speed."""

    kind: str = ""
    key: str = ""
    count: int = 0

    @classmethod
    def from_json(cls, raw: Any) -> "Facet":
        return cls(**_only_known(cls, raw))


@dataclass(frozen=True)
class LocalityDetail:
    """One suburb or town: every charging site in it, what to filter by, and
    the places around it."""

    country: Country = field(default_factory=Country)
    region: Region = field(default_factory=Region)
    locality: Locality = field(default_factory=Locality)
    sites: "Tuple[Site, ...]" = ()
    facets: "Tuple[Facet, ...]" = ()
    neighbours: "Tuple[Locality, ...]" = ()

    @classmethod
    def from_json(cls, raw: Any) -> "LocalityDetail":
        raw = _map(raw)
        return cls(
            country=Country.from_json(raw.get("country")),
            region=Region.from_json(raw.get("region")),
            locality=Locality.from_json(raw.get("locality")),
            sites=_rows(Site, raw.get("sites")),
            facets=_rows(Facet, raw.get("facets")),
            neighbours=_rows(Locality, raw.get("neighbours")),
        )


# -- search and nearby ----------------------------------------------------


@dataclass(frozen=True)
class PlaceMatch:
    """A suburb or town matching a search. ``exact`` is a full name match, which
    a search box can go straight to."""

    country_iso2: str = ""
    country_name: str = ""
    region_code: str = ""
    region_name: str = ""
    slug: str = ""
    name: str = ""
    postcode: str = ""
    site_count: int = 0
    path: str = ""
    exact: bool = False
    lat: float = 0.0
    lng: float = 0.0

    @property
    def url(self) -> str:
        return _url(self.path)

    @classmethod
    def from_json(cls, raw: Any) -> "PlaceMatch":
        return cls(**_only_known(cls, raw))


@dataclass(frozen=True)
class PostcodeMatch:
    """A postcode's centre, for the chargers near it."""

    country_iso2: str = ""
    country_name: str = ""
    code: str = ""
    lat: float = 0.0
    lng: float = 0.0

    @classmethod
    def from_json(cls, raw: Any) -> "PostcodeMatch":
        return cls(**_only_known(cls, raw))


@dataclass(frozen=True)
class SearchResult:
    localities: "Tuple[PlaceMatch, ...]" = ()
    postcodes: "Tuple[PostcodeMatch, ...]" = ()
    sites: "Tuple[Site, ...]" = ()

    @classmethod
    def from_json(cls, raw: Any) -> "SearchResult":
        raw = _map(raw)
        return cls(
            localities=_rows(PlaceMatch, raw.get("localities")),
            postcodes=_rows(PostcodeMatch, raw.get("postcodes")),
            sites=_rows(Site, raw.get("sites")),
        )


@dataclass(frozen=True)
class NearPlace:
    """The closest named place to a point, for a heading."""

    country_iso2: str = ""
    name: str = ""
    region_code: str = ""
    region_name: str = ""
    path: str = ""
    distance_km: float = 0.0

    @property
    def url(self) -> str:
        return _url(self.path)

    @classmethod
    def from_json(cls, raw: Any) -> "NearPlace":
        return cls(**_only_known(cls, raw))


@dataclass(frozen=True)
class Nearby:
    """The sites nearest a point, nearest first. ``near`` is None in the middle
    of nowhere."""

    near: Optional[NearPlace] = None
    sites: "Tuple[Site, ...]" = ()

    @classmethod
    def from_json(cls, raw: Any) -> "Nearby":
        raw = _map(raw)
        near = raw.get("near")
        return cls(
            near=NearPlace.from_json(near) if isinstance(near, Mapping) else None,
            sites=_rows(Site, raw.get("sites")),
        )


# -- trips ----------------------------------------------------------------


@dataclass(frozen=True)
class Route:
    distance_km: float = 0.0
    duration_min: int = 0
    #: The road, as (longitude, latitude) pairs, the order GeoJSON uses.
    line: "Tuple[Tuple[float, float], ...]" = ()

    @classmethod
    def from_json(cls, raw: Any) -> "Route":
        row = _only_known(cls, raw)
        line = row.get("line")
        row["line"] = tuple(
            (float(p[0]), float(p[1]))
            for p in (line if isinstance(line, list) else [])
            if isinstance(p, list) and len(p) == 2
        )
        return cls(**row)


@dataclass(frozen=True)
class TripStop:
    """One charging stop, in order."""

    site: Site = field(default_factory=Site)
    along_km: float = 0.0
    detour_km: float = 0.0
    power_kw: float = 0.0
    dc: bool = False
    arrive_pct: int = 0
    depart_pct: int = 0
    energy_kwh: float = 0.0
    charge_min: int = 0

    @classmethod
    def from_json(cls, raw: Any) -> "TripStop":
        row = _only_known(cls, raw)
        row["site"] = Site.from_json(row.get("site"))
        return cls(**row)


@dataclass(frozen=True)
class Gap:
    """Where along the route no charger is in reach, in km from the start."""

    from_km: float = 0.0
    to_km: float = 0.0

    @classmethod
    def from_json(cls, raw: Any) -> "Gap":
        return cls(**_only_known(cls, raw))


@dataclass(frozen=True)
class TripPlan:
    """A trip through charging stops.

    ``feasible`` false is an answer, not an error: the car cannot make it
    without dropping below the reserve, and ``gap`` says where.
    """

    route: Route = field(default_factory=Route)
    feasible: bool = False
    arrival_pct: Optional[int] = None
    drive_min: int = 0
    charge_min: int = 0
    total_min: int = 0
    gap: Optional[Gap] = None
    stops: "Tuple[TripStop, ...]" = ()

    @classmethod
    def from_json(cls, raw: Any) -> "TripPlan":
        row = _only_known(cls, raw)
        row["route"] = Route.from_json(row.get("route"))
        row["gap"] = Gap.from_json(row["gap"]) if isinstance(row.get("gap"), Mapping) else None
        row["stops"] = _rows(TripStop, row.get("stops"))
        return cls(**row)


# -- vehicles -------------------------------------------------------------


@dataclass(frozen=True)
class CurvePoint:
    pct: int = 0
    power_kw: float = 0.0

    @classmethod
    def from_json(cls, raw: Any) -> "CurvePoint":
        return cls(**_only_known(cls, raw))


@dataclass(frozen=True)
class ChargeTime:
    """How long 10 to 80 percent takes on a charger of this power."""

    charger_kw: float = 0
    minutes_10_80: int = 0

    @classmethod
    def from_json(cls, raw: Any) -> "ChargeTime":
        return cls(**_only_known(cls, raw))


@dataclass(frozen=True)
class Vehicle:
    """One electric car. ``charging`` is on a single vehicle only.

    From Open EV Data (MIT).
    """

    slug: str = ""
    brand: str = ""
    model: str = ""
    variant: str = ""
    year: Optional[int] = None
    source_id: str = ""
    battery_kwh: float = 0.0
    consumption_kwh_100km: float = 0.0
    range_km: float = 0
    ac_kw: float = 0
    ac_ports: "Tuple[str, ...]" = ()
    dc_kw: float = 0
    dc_ports: "Tuple[str, ...]" = ()
    curve: "Tuple[CurvePoint, ...]" = ()
    #: The curve is a typical one for the car's class, not measured for it.
    curve_is_generic: bool = False
    voltage_v: Optional[int] = None
    charging: "Tuple[ChargeTime, ...]" = ()

    @classmethod
    def from_json(cls, raw: Any) -> "Vehicle":
        row = _only_known(cls, raw)
        row["ac_ports"] = _strings(row.get("ac_ports"))
        row["dc_ports"] = _strings(row.get("dc_ports"))
        row["curve"] = _rows(CurvePoint, row.get("curve"))
        row["charging"] = _rows(ChargeTime, row.get("charging"))
        return cls(**row)


# -- redirects ------------------------------------------------------------


@dataclass(frozen=True)
class Redirect:
    """Where a moved page went. ``status`` is 301, 302 or 308."""

    from_path: str = ""
    to: str = ""
    status: int = 301

    @property
    def url(self) -> str:
        return _url(self.to)

    @classmethod
    def from_json(cls, raw: Any) -> "Redirect":
        raw = _map(raw)
        return cls(from_path=raw.get("from") or "", to=raw.get("to") or "", status=raw.get("status") or 301)
