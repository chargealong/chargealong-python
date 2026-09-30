"""The client itself."""

from __future__ import annotations

import ipaddress
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence, Tuple, Union

from ._errors import error_for
from ._models import (
    CONNECTORS,
    Country,
    CountryDetail,
    LocalityDetail,
    Nearby,
    NetworkDetail,
    NetworkList,
    Overview,
    Redirect,
    RegionDetail,
    SearchResult,
    SiteDetail,
    TripPlan,
    Vehicle,
    site_path,
)

__version__ = "0.1.0"

DEFAULT_BASE_URL = "https://api.chargealong.io"

#: (method, url, headers, timeout) -> (status, body bytes) or
#: (status, body bytes, response headers). Headers are only read for
#: Retry-After, so a two item answer is enough for a test double.
Transport = Callable[[str, str, dict, float], "tuple"]

# Bounded reads. A network's page is the largest answer here and runs to a few
# hundred kilobytes; past a few megabytes, something on the other end of the
# socket is not this API and a client should not be talked into reading it all.
_MAX_BODY = 16 << 20

# What the service accepts, mirrored so a bad value costs no request.
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_COUNTRY_CODE = re.compile(r"^[A-Z]{2}$")

Point = Tuple[float, float]


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """Follow no redirect at all.

    The API does not redirect, so a 3xx is a proxy or a hijack rather than an
    answer. A query here carries where somebody is; it goes nowhere it was not
    sent. The 3xx comes back as an error with its status.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "chargealong: refused a redirect", headers, fp)


_opener = urllib.request.build_opener(_NoRedirects)


def _urllib_transport(method: str, url: str, headers: dict, timeout: float):
    req = urllib.request.Request(url, method=method, headers=headers)
    try:
        with _opener.open(req, timeout=timeout) as res:
            return res.status, res.read(_MAX_BODY), dict(res.headers.items())
    except urllib.error.HTTPError as err:
        body = err.read(_MAX_BODY) if err.fp is not None else b""
        return err.code, body, dict(err.headers.items()) if err.headers else {}


def _check_base_url(raw: str) -> str:
    """Refuse a base URL that would put the request somewhere it should not go.

    https always, and plaintext http only to loopback, which is what a local
    proxy and a test server need.
    """
    if not raw:
        raise ValueError("chargealong: no base URL")
    parsed = urllib.parse.urlparse(raw)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError(f"chargealong: base URL {raw!r} is not absolute")
    # https://api.chargealong.io:pass@evil.example reads as the real host to
    # anyone skimming a config file, and is a different host to urllib.
    if parsed.username or parsed.password:
        raise ValueError(
            f"chargealong: base URL {raw!r} carries credentials, and the host it "
            "would reach is not the one it reads as"
        )
    if "?" in raw or "#" in raw:
        raise ValueError(f"chargealong: base URL {raw!r} has a query or a fragment, which would swallow the path")
    if parsed.scheme == "https":
        return raw.rstrip("/")
    if parsed.scheme == "http" and _is_loopback(parsed.hostname):
        return raw.rstrip("/")
    if parsed.scheme == "http":
        raise ValueError(
            f"chargealong: base URL {raw!r} is plaintext http to a public host, "
            "which would send where people are in the clear"
        )
    raise ValueError(f"chargealong: base URL {raw!r} has scheme {parsed.scheme!r}, want https")


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _segment(value: Any, what: str) -> str:
    """One path segment, encoded.

    ``safe=""`` so a slug carrying a slash cannot walk up the path, and "." and
    ".." are refused because as a whole segment they are the collection or its
    parent, whatever the encoding.
    """
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"chargealong: no {what}")
    if text in (".", ".."):
        raise ValueError(f"chargealong: {text!r} is not a {what}")
    return urllib.parse.quote(text, safe="")


def _number(name: str, value: Any, lo: float, hi: float) -> float:
    """A finite number within the service's own bounds, or ValueError.

    Written as a range check that NaN cannot pass. bool is refused because
    True is an int to Python and a mistake to everybody else.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"chargealong: {name} must be a number, not {value!r}")
    if not (lo <= value <= hi):
        raise ValueError(f"chargealong: {name} must be between {_fmt(lo)} and {_fmt(hi)}, not {value!r}")
    return value


def _count(name: str, value: Any, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"chargealong: {name} must be a whole number, not {value!r}")
    if not (lo <= value <= hi):
        raise ValueError(f"chargealong: {name} must be between {lo} and {hi}, not {value!r}")
    return value


def _fmt(value: float) -> str:
    """400 rather than 400.0: what a person would type, and what the docs show."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _point(name: str, value: Any) -> Point:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 2:
        raise ValueError(f"chargealong: {name} must be a (lat, lng) pair")
    lat, lng = value
    try:
        return _number(f"{name} lat", lat, -90, 90), _number(f"{name} lng", lng, -180, 180)
    except ValueError:
        raise ValueError(
            f"chargealong: {name} {value!r} is not a point on the globe; lat -90..90, lng -180..180"
        ) from None


def _connectors(name: str, value: Union[str, Iterable[str]]) -> "list[str]":
    items = [value] if isinstance(value, str) else list(value)
    for c in items:
        if c not in CONNECTORS:
            raise ValueError(f"chargealong: {name} {c!r} is not a connector standard; use " + ", ".join(CONNECTORS))
    return items


def _search_term(term: Any) -> Optional[str]:
    """The term, or None when the service would refuse it as too short.

    The service keeps letters, digits, apostrophes and hyphens, and wants three
    letters or digits among them.
    """
    text = str(term or "").strip()
    if len(text.encode("utf-8")) > 100:
        raise ValueError("chargealong: a search is at most 100 bytes")
    if sum(1 for c in text if c.isalnum()) < 3:
        return None
    return text


class ChargeAlong:
    """A client for the ChargeAlong EV charging API.

    Public charging sites, the networks that run them, trip planning through
    charging stops, and how fast electric cars charge.

        >>> from chargealong import ChargeAlong
        >>> ca = ChargeAlong()
        >>> for site in ca.nearby(-37.7404, 144.9633, min_kw=50).sites:
        ...     print(site.name, site.max_kw, "kW", site.distance_m, "m")

    No key and nothing to buy: the API is free, anonymous and cached at the
    edge. Be gentle with it: keep answers rather than fetching them again, and
    debounce anything a person types.

    Attribution travels with the data. Charging site data is from Open Charge
    Map contributors, Transport for NSW and the Queensland Government, places
    from GeoNames, all CC BY 4.0; cars from Open EV Data. See
    chargealong.io/en/guides/where-the-data-comes-from/.

    Thread safe. Make one and keep it.
    """

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 15.0,
        transport: Optional[Transport] = None,
    ):
        self._base_url = _check_base_url(base_url)
        self._timeout = timeout
        self._transport = transport or _urllib_transport
        self._agent = f"chargealong-python/{__version__}"

    # -- finding chargers --------------------------------------------------

    def nearby(
        self,
        lat: float,
        lng: float,
        *,
        min_kw: Optional[float] = None,
        radius_km: Optional[float] = None,
        limit: Optional[int] = None,
        connector: Union[str, Iterable[str], None] = None,
        network: Optional[str] = None,
    ) -> Nearby:
        """The charging sites nearest a point, nearest first.

        ``radius_km`` defaults to 50 (1 to 150), ``limit`` to 30 (1 to 50).
        ``min_kw`` keeps sites with a connector of at least that power: 100 is
        roughly the line between a stop and a top up. ``connector`` is one
        standard or several (any of them), from :data:`CONNECTORS`.
        ``network`` is a network's slug: ``evie-networks``.
        """
        lat, lng = self._coordinate(lat, lng)
        params: "list[tuple[str, str]]" = [("lat", _fmt(lat)), ("lng", _fmt(lng))]
        if min_kw is not None:
            params.append(("min_kw", _fmt(_number("min_kw", min_kw, 0, 400))))
        if radius_km is not None:
            params.append(("radius_km", _fmt(_number("radius_km", radius_km, 1, 150))))
        if limit is not None:
            params.append(("limit", str(_count("limit", limit, 1, 50))))
        if connector is not None:
            # Repeated: /v1/nearby reads connector=ccs2&connector=chademo.
            params += [("connector", c) for c in _connectors("connector", connector)]
        if network is not None:
            params.append(("network", self._slug_value("network", network)))
        return Nearby.from_json(self._get("/v1/nearby", params).get("data"))

    def site(self, public_id: str) -> SiteDetail:
        """One charging site in full: connectors, price, access, sources, what
        drivers said, and nearby alternatives.

        The id is permanent. Raises :class:`NotFound` for an id that never
        existed and :class:`Gone` for a site removed from its source, so code
        holding stored ids can tell a typo from a retired charger.
        """
        body = self._get(f"/v1/sites/{_segment(public_id, 'site id')}", None)
        return SiteDetail.from_json(body.get("data"))

    def search(self, q: str, *, prefer: Optional[str] = None) -> SearchResult:
        """Places, postcodes and sites matching a name.

        ``prefer`` is a two letter country code whose places rank first, which
        is what a search box wants for its visitor. A term with fewer than
        three letters or digits answers empty without a request, since the
        service would refuse it.
        """
        term = _search_term(q)
        params: "list[tuple[str, str]]" = []
        if prefer is not None:
            code = str(prefer).strip().upper()
            if not _COUNTRY_CODE.match(code):
                raise ValueError(f"chargealong: prefer {prefer!r} is not a two letter country code")
            params.append(("prefer", code))
        if term is None:
            return SearchResult()
        return SearchResult.from_json(self._get("/v1/search", [("q", term)] + params).get("data"))

    # -- trips -------------------------------------------------------------

    def plan_trip(
        self,
        from_: Point,
        to: Point,
        *,
        range_km: float,
        reserve: Optional[float] = None,
        start: Optional[float] = None,
        charge_to: Optional[float] = None,
        battery_kwh: Optional[float] = None,
        max_dc_kw: Optional[float] = None,
        max_ac_kw: Optional[float] = None,
        min_kw: Optional[float] = None,
        connectors: Union[str, Iterable[str], None] = None,
    ) -> TripPlan:
        """A road trip through charging stops.

        ``from_`` and ``to`` are ``(lat, lng)``. ``range_km`` is how far the car
        really goes on a full battery (50 to 1500). The rest are optional:
        ``reserve`` never arrive below this percentage (default 20),
        ``start`` percentage at the start (default 100, above the reserve),
        ``charge_to`` never charge above this (default 80), ``battery_kwh``
        usable battery for charging times, ``max_dc_kw`` and ``max_ac_kw`` what
        the car accepts, ``min_kw`` ignore slower chargers (default 50), and
        ``connectors`` what the car takes (default ccs2 and type-2).

        A plan that cannot meet the reserve is still an answer, with
        ``feasible`` false and ``gap`` saying where. No road between the points
        (Sydney to Auckland) raises :class:`NoRoute`. Trips are planned in
        Australia and New Zealand; the service rounds both points to about
        100 m.
        """
        a, b = _point("from", from_), _point("to", to)
        if (round(a[0], 3), round(a[1], 3)) == (round(b[0], 3), round(b[1], 3)):
            raise ValueError("chargealong: to must be somewhere other than from")

        params: "list[tuple[str, str]]" = [
            ("from", f"{_fmt(a[0])},{_fmt(a[1])}"),
            ("to", f"{_fmt(b[0])},{_fmt(b[1])}"),
            ("range_km", _fmt(_number("range_km", range_km, 50, 1500))),
        ]
        floor = 20.0
        if reserve is not None:
            floor = _number("reserve", reserve, 5, 50)
            params.append(("reserve", _fmt(reserve)))
        if start is not None:
            params.append(("start", _fmt(_number("start", start, floor + 1, 100))))
        if charge_to is not None:
            params.append(("charge_to", _fmt(_number("charge_to", charge_to, max(50.0, floor + 10), 100))))
        if battery_kwh is not None:
            params.append(("battery_kwh", _fmt(_number("battery_kwh", battery_kwh, 10, 250))))
        if max_dc_kw is not None:
            params.append(("max_dc_kw", _fmt(_number("max_dc_kw", max_dc_kw, 20, 400))))
        if max_ac_kw is not None:
            params.append(("max_ac_kw", _fmt(_number("max_ac_kw", max_ac_kw, 3, 22))))
        if min_kw is not None:
            params.append(("min_kw", _fmt(_number("min_kw", min_kw, 0, 350))))
        if connectors is not None:
            # Comma separated: /v1/trips/plan reads connectors=ccs2,type-2.
            params.append(("connectors", ",".join(_connectors("connectors", connectors))))
        return TripPlan.from_json(self._get("/v1/trips/plan", params).get("data"))

    # -- vehicles ----------------------------------------------------------

    def vehicles(self, q: Optional[str] = None, *, limit: Optional[int] = None, all: bool = False) -> "list[Vehicle]":
        """Electric cars: battery, range and how they charge.

        ``q`` finds cars by any part of the brand, model or variant. ``limit``
        is 1 to 100 (default 20); ``all=True`` returns every car, and is
        ignored when ``q`` is given.
        """
        params: "list[tuple[str, str]]" = []
        if q is not None and str(q).strip():
            params.append(("q", str(q).strip()))
        if limit is not None:
            params.append(("limit", str(_count("limit", limit, 1, 100))))
        if all:
            params.append(("all", "true"))
        data = self._get("/v1/vehicles", params).get("data")
        return [Vehicle.from_json(v) for v in (data if isinstance(data, list) else []) if isinstance(v, Mapping)]

    def vehicle(self, slug: str) -> Vehicle:
        """One car, with how long 10 to 80 percent takes on 50, 150 and 350 kW."""
        return Vehicle.from_json(self._get(f"/v1/vehicles/{_segment(slug, 'vehicle')}", None).get("data"))

    # -- browsing ----------------------------------------------------------

    def countries(self) -> "list[Country]":
        """Every country with charging sites, and how many each has."""
        data = self._get("/v1/countries", None).get("data")
        return [Country.from_json(c) for c in (data if isinstance(data, list) else []) if isinstance(c, Mapping)]

    def overview(self) -> Overview:
        """What the whole directory holds: countries and their busiest places."""
        return Overview.from_json(self._get("/v1/overview", None).get("data"))

    def country(self, country: str) -> CountryDetail:
        """One country: its regions and their counts, and its busiest places."""
        return CountryDetail.from_json(self._get(f"/v1/countries/{_segment(country, 'country')}", None).get("data"))

    def region(self, country: str, region: str) -> RegionDetail:
        """One state or region: the places in it that have charging sites."""
        path = f"/v1/countries/{_segment(country, 'country')}/regions/{_segment(region, 'region')}"
        return RegionDetail.from_json(self._get(path, None).get("data"))

    def networks(self, country: str) -> NetworkList:
        """Every charging network in a country, with its site and region counts."""
        path = f"/v1/countries/{_segment(country, 'country')}/networks"
        return NetworkList.from_json(self._get(path, None).get("data"))

    def network(self, country: str, network: str) -> NetworkDetail:
        """One network in a country: where it reaches, and a sample of its sites."""
        path = f"/v1/countries/{_segment(country, 'country')}/networks/{_segment(network, 'network')}"
        return NetworkDetail.from_json(self._get(path, None).get("data"))

    def locality(self, country: str, region: str, locality: str) -> LocalityDetail:
        """One suburb or town: every charging site in it, with facet counts.

        Raises :class:`NotFound` for a place with no sites: those have no page.
        """
        path = (
            f"/v1/localities/{_segment(country, 'country')}"
            f"/{_segment(region, 'region')}/{_segment(locality, 'locality')}"
        )
        return LocalityDetail.from_json(self._get(path, None).get("data"))

    def redirect(self, path: str) -> Optional[Redirect]:
        """Where a page on chargealong.io went, if it moved; None if it did not.

        URLs there are permanent, so this is for the rare page that had to move
        (a site filed under the wrong suburb). Most paths asked about have
        simply not moved, which is None rather than an exception.
        """
        text = str(path or "").strip()
        if not site_path(text):
            raise ValueError(f"chargealong: {path!r} is not a path on chargealong.io, starting with one slash")
        from ._errors import NotFound

        try:
            body = self._get("/v1/redirect", [("path", text)])
        except NotFound:
            return None
        return Redirect.from_json(body.get("data"))

    # -- plumbing ----------------------------------------------------------

    @staticmethod
    def _coordinate(lat: Any, lng: Any) -> Point:
        try:
            return _number("lat", lat, -90, 90), _number("lng", lng, -180, 180)
        except ValueError:
            raise ValueError(
                f"chargealong: ({lat!r}, {lng!r}) is not a point on the globe; lat -90..90, lng -180..180"
            ) from None

    @staticmethod
    def _slug_value(name: str, value: Any) -> str:
        text = str(value or "").strip()
        if len(text) > 100 or not _SLUG.match(text):
            raise ValueError(f"chargealong: {name} {value!r} is not a slug, like evie-networks")
        return text

    def _get(self, path: str, params: "Optional[Sequence[tuple[str, str]]]") -> dict:
        url = self._base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(list(params), quote_via=urllib.parse.quote)

        answer = self._transport(
            "GET",
            url,
            {"Accept": "application/json", "User-Agent": self._agent},
            self._timeout,
        )
        status, raw = answer[0], answer[1]
        headers = answer[2] if len(answer) > 2 and isinstance(answer[2], Mapping) else {}

        # A problem document is JSON; a proxy having a bad day is not. Either
        # way the status is the part a caller can act on, so parsing never
        # decides whether an error is raised.
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}

        if not 200 <= status < 300:
            title = body.get("title") if isinstance(body.get("title"), str) else ""
            detail = body.get("detail") if isinstance(body.get("detail"), str) else ""
            raise error_for(status, title, detail, _retry_after(headers))
        return body


def _retry_after(headers: Mapping[str, Any]) -> Optional[float]:
    for name, value in headers.items():
        if str(name).lower() == "retry-after":
            try:
                seconds = float(value)
            except (TypeError, ValueError):
                return None
            return seconds if math.isfinite(seconds) and seconds > 0 else None
    return None
