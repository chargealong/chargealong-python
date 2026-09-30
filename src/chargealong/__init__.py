"""ChargeAlong: public EV charging sites, trip planning and electric cars, as an API.

Free, keyless and cached at the edge. The directory behind chargealong.io.

    >>> from chargealong import ChargeAlong
    >>> ca = ChargeAlong()
    >>> near = ca.nearby(-37.7404, 144.9633, min_kw=50)
    >>> near.sites[0].name, near.sites[0].max_kw
    ('Coburg Civic Centre / Moreland City', 50)

Charging site data from Open Charge Map contributors, Transport for NSW and the
Queensland Government, places from GeoNames, all CC BY 4.0. Publishing what you
get back means carrying those credits:
chargealong.io/en/guides/where-the-data-comes-from/.
"""

from ._client import DEFAULT_BASE_URL, ChargeAlong, Transport, __version__
from ._errors import BadRequest, ChargeAlongError, Gone, NoRoute, NotFound, RateLimited
from ._models import (
    CONNECTORS,
    SITE,
    ChargeTime,
    Connector,
    Cost,
    Country,
    CountryDetail,
    CountryOverview,
    CurvePoint,
    Facet,
    Gap,
    Locality,
    LocalityDetail,
    NearPlace,
    Nearby,
    Network,
    NetworkDetail,
    NetworkList,
    Overview,
    Photo,
    PlaceMatch,
    PostcodeMatch,
    Redirect,
    Region,
    RegionDetail,
    Review,
    Reviews,
    ReviewSummary,
    Route,
    SearchResult,
    Site,
    SiteDetail,
    Source,
    TripPlan,
    TripStop,
    Vehicle,
)

__all__ = [
    "BadRequest", "CONNECTORS", "ChargeAlong", "ChargeAlongError", "ChargeTime", "Connector", "Cost",
    "Country", "CountryDetail", "CountryOverview", "CurvePoint", "DEFAULT_BASE_URL", "Facet", "Gap",
    "Gone", "Locality", "LocalityDetail", "NearPlace", "Nearby", "Network", "NetworkDetail",
    "NetworkList", "NoRoute", "NotFound", "Overview", "Photo", "PlaceMatch", "PostcodeMatch",
    "RateLimited", "Redirect", "Region", "RegionDetail", "Review", "ReviewSummary", "Reviews",
    "Route", "SITE", "SearchResult", "Site", "SiteDetail", "Source", "Transport", "TripPlan",
    "TripStop", "Vehicle", "__version__",
]
