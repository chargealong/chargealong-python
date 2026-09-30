"""The ChargeAlong client, tested against what the API actually sends.

unittest rather than pytest so the suite runs with nothing installed: the
library has no dependencies, and a test suite that needs one is a worse first
impression than no test suite. pytest runs these too.

The fixtures are real answers from api.chargealong.io, trimmed to a few rows.
"""

from __future__ import annotations

import json
import pathlib
import unittest
import urllib.parse

from chargealong import (
    CONNECTORS,
    BadRequest,
    ChargeAlong,
    ChargeAlongError,
    Gone,
    NoRoute,
    NotFound,
    RateLimited,
    Site,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


class Recorder:
    """A transport that answers one canned body and remembers what was asked."""

    def __init__(self, body=None, status=200):
        self.calls = []
        self.body = body if body is not None else {"data": []}
        self.status = status

    def __call__(self, method, url, headers, timeout):
        self.calls.append((method, url, headers, timeout))
        return self.status, json.dumps(self.body).encode()

    @property
    def url(self) -> str:
        return self.calls[-1][1]

    @property
    def path(self) -> str:
        return urllib.parse.urlparse(self.url).path

    @property
    def query(self) -> "dict[str, list[str]]":
        return urllib.parse.parse_qs(urllib.parse.urlparse(self.url).query)


def client(body=None, status=200) -> "tuple[ChargeAlong, Recorder]":
    rec = Recorder(body, status)
    return ChargeAlong(transport=rec), rec


class TestNearby(unittest.TestCase):
    def test_nearby_asks_for_the_point_and_reads_the_sites(self):
        ca, rec = client(fixture("nearby"))
        result = ca.nearby(-37.7404, 144.9633)

        self.assertEqual("/v1/nearby", rec.path)
        self.assertEqual(["-37.7404"], rec.query["lat"])
        self.assertEqual(["144.9633"], rec.query["lng"])
        self.assertEqual("Merlynston", result.near.name)
        self.assertEqual("VIC", result.near.region_code)
        site = result.sites[0]
        self.assertIsInstance(site, Site)
        self.assertEqual("hwqb4abf", site.public_id)
        self.assertEqual("chargefox", site.network)
        self.assertEqual(("type-2",), site.standards)
        self.assertEqual(7, site.max_kw)
        self.assertGreater(site.distance_km, 0)
        self.assertEqual(round(site.distance_km * 1000), site.distance_m)

    def test_every_filter_is_sent_as_the_api_reads_it(self):
        ca, rec = client(fixture("nearby"))
        ca.nearby(-37.74, 144.96, min_kw=50, radius_km=20, limit=5,
                  connector=["ccs2", "chademo"], network="evie-networks")

        self.assertEqual(["50"], rec.query["min_kw"])
        self.assertEqual(["20"], rec.query["radius_km"])
        self.assertEqual(["5"], rec.query["limit"])
        # Repeated, not comma separated: that is how /v1/nearby reads it.
        self.assertEqual(["ccs2", "chademo"], rec.query["connector"])
        self.assertEqual(["evie-networks"], rec.query["network"])

    def test_a_single_connector_may_be_a_string(self):
        ca, rec = client(fixture("nearby"))
        ca.nearby(-37.74, 144.96, connector="ccs2")
        self.assertEqual(["ccs2"], rec.query["connector"])

    def test_filters_left_out_are_not_sent(self):
        ca, rec = client(fixture("nearby"))
        ca.nearby(-37.74, 144.96)
        self.assertEqual({"lat", "lng"}, set(rec.query))

    def test_near_is_none_in_the_middle_of_nowhere(self):
        ca, _ = client({"data": {"near": None, "sites": []}})
        result = ca.nearby(-25.0, 131.0)
        self.assertIsNone(result.near)
        self.assertEqual((), result.sites)

    def test_an_unknown_connector_is_refused_before_a_request(self):
        ca, rec = client()
        with self.assertRaises(ValueError) as caught:
            ca.nearby(-37.74, 144.96, connector=["css2"])
        self.assertIn("ccs2", str(caught.exception))
        self.assertEqual([], rec.calls)

    def test_filters_out_of_range_are_refused_before_a_request(self):
        ca, rec = client()
        for kwargs in ({"limit": 0}, {"limit": 51}, {"radius_km": 0.5}, {"radius_km": 151},
                       {"min_kw": -1}, {"min_kw": 401}, {"network": "Evie Networks"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ca.nearby(-37.74, 144.96, **kwargs)
        self.assertEqual([], rec.calls)


class TestSite(unittest.TestCase):
    def test_a_site_reads_in_full(self):
        ca, rec = client(fixture("site"))
        detail = ca.site("hwqb4abf")

        self.assertEqual("/v1/sites/hwqb4abf", rec.path)
        self.assertEqual("australia", detail.country.slug)
        self.assertEqual("VIC", detail.region.code)
        self.assertEqual("Australia/Melbourne", detail.locality.time_zone)
        self.assertEqual("Coburg Town Hall / Moreland City", detail.site.name)
        self.assertEqual("public", detail.site.usage)
        self.assertEqual("free", detail.site.cost.kind)
        self.assertEqual(2023, detail.site.last_verified_at.year)
        self.assertEqual("type-2", detail.connectors[0].standard)
        self.assertEqual("ac", detail.connectors[0].current)
        self.assertEqual("ocm", detail.sources[0].key)
        self.assertIn("CC BY 4.0", detail.sources[0].licence)
        self.assertEqual(1, len(detail.alternatives))
        self.assertEqual("guzgfbyv", detail.faster.public_id)

    def test_reviews_and_photos_are_read(self):
        ca, _ = client(fixture("site"))
        detail = ca.site("hwqb4abf")

        self.assertEqual(2, detail.reviews.summary.count)
        self.assertEqual(4.5, detail.reviews.summary.average)
        self.assertIsNone(detail.reviews.summary.last_checked_at)
        self.assertEqual(5, detail.reviews.recent[0].rating)
        self.assertIsNone(detail.reviews.recent[1].rating)
        self.assertEqual("", detail.reviews.recent[1].body)
        self.assertEqual(1600, detail.photos[0].width)

    def test_faster_is_none_when_there_is_nothing_faster(self):
        body = fixture("site")
        del body["data"]["faster"]
        ca, _ = client(body)
        self.assertIsNone(ca.site("hwqb4abf").faster)

    def test_a_missing_site_raises_not_found(self):
        ca, _ = client(fixture("not_found"), status=404)
        with self.assertRaises(NotFound) as caught:
            ca.site("zzzzzzzz")
        self.assertEqual(404, caught.exception.status)
        self.assertEqual("not found", caught.exception.title)

    def test_a_retired_site_raises_gone_not_not_found(self):
        # A caller holding stored ids needs to tell "removed from its source"
        # from "never existed": the first is worth dropping from a list, the
        # second is a typo.
        ca, _ = client({"status": 410, "title": "gone", "type": "about:blank"}, status=410)
        with self.assertRaises(Gone) as caught:
            ca.site("hwqb4abf")
        self.assertNotIsInstance(caught.exception, NotFound)
        self.assertIsInstance(caught.exception, ChargeAlongError)
        self.assertEqual(410, caught.exception.status)

    def test_a_site_row_links_to_its_page(self):
        ca, _ = client(fixture("site"))
        site = ca.site("hwqb4abf").site
        self.assertEqual(
            "https://chargealong.io/en/australia/victoria/batman/chargefox/coburg-town-hall-moreland-city-hwqb4abf/",
            site.url,
        )


class TestSearch(unittest.TestCase):
    def test_search_reads_places_postcodes_and_sites(self):
        ca, rec = client(fixture("search"))
        result = ca.search("coburg", prefer="AU")

        self.assertEqual("/v1/search", rec.path)
        self.assertEqual(["coburg"], rec.query["q"])
        self.assertEqual(["AU"], rec.query["prefer"])
        self.assertEqual("Coburg", result.localities[0].name)
        self.assertTrue(result.localities[0].exact)
        self.assertEqual("https://chargealong.io/en/united-states/oregon/coburg/", result.localities[0].url)
        self.assertEqual("3058", result.postcodes[0].code)
        self.assertEqual("m6mnomea", result.sites[0].public_id)

    def test_prefer_is_upper_cased_and_checked(self):
        ca, rec = client(fixture("search"))
        ca.search("coburg", prefer="au")
        self.assertEqual(["AU"], rec.query["prefer"])
        with self.assertRaises(ValueError):
            ca.search("coburg", prefer="AUS")

    def test_a_term_the_service_would_refuse_answers_empty_without_a_request(self):
        # The service wants three letters or digits; below that it answers 400.
        ca, rec = client(fixture("search"))
        for term in ("", "  ", "ab", "a-b", "!!!"):
            result = ca.search(term)
            self.assertEqual((), result.localities + result.postcodes)
            self.assertEqual((), result.sites)
        self.assertEqual([], rec.calls)

    def test_a_term_over_a_hundred_characters_is_refused(self):
        ca, rec = client()
        with self.assertRaises(ValueError):
            ca.search("x" * 101)
        self.assertEqual([], rec.calls)


class TestBrowsing(unittest.TestCase):
    def test_countries(self):
        ca, rec = client(fixture("countries"))
        countries = ca.countries()
        self.assertEqual("/v1/countries", rec.path)
        self.assertEqual("AU", countries[0].iso2)
        self.assertGreater(countries[0].site_count, 1000)
        self.assertEqual("https://chargealong.io/en/australia/", countries[0].url)

    def test_overview(self):
        ca, rec = client(fixture("overview"))
        overview = ca.overview()
        self.assertEqual("/v1/overview", rec.path)
        self.assertGreater(overview.sites, overview.ultra_fast)
        self.assertEqual("australia", overview.countries[0].slug)
        self.assertEqual("randwick", overview.countries[0].busiest[0].slug)
        self.assertEqual("new-south-wales", overview.countries[0].busiest[0].region)

    def test_country(self):
        ca, rec = client(fixture("country"))
        detail = ca.country("australia")
        self.assertEqual("/v1/countries/australia", rec.path)
        self.assertEqual("ACT", detail.regions[0].code)
        self.assertEqual("randwick", detail.busiest[0].slug)
        self.assertEqual(
            "https://chargealong.io/en/australia/new-south-wales/randwick/",
            detail.busiest[0].url_in(detail.country),
        )

    def test_region(self):
        ca, rec = client(fixture("region"))
        detail = ca.region("australia", "victoria")
        self.assertEqual("/v1/countries/australia/regions/victoria", rec.path)
        self.assertEqual("victoria", detail.region.slug)
        self.assertEqual("abbotsford", detail.localities[0].slug)

    def test_networks(self):
        ca, rec = client(fixture("networks"))
        result = ca.networks("australia")
        self.assertEqual("/v1/countries/australia/networks", rec.path)
        self.assertEqual("australia", result.country.slug)
        self.assertEqual("unbranded", result.networks[0].key)

    def test_network(self):
        ca, rec = client(fixture("network"))
        detail = ca.network("australia", "chargefox")
        self.assertEqual("/v1/countries/australia/networks/chargefox", rec.path)
        self.assertEqual("Chargefox", detail.network.name)
        self.assertEqual("NSW", detail.regions[0].code)
        self.assertEqual("gnhcbx24", detail.sites[0].public_id)

    def test_locality(self):
        ca, rec = client(fixture("locality"))
        detail = ca.locality("australia", "victoria", "batman")
        self.assertEqual("/v1/localities/australia/victoria/batman", rec.path)
        self.assertEqual("batman", detail.locality.slug)
        self.assertEqual("guzgfbyv", detail.sites[0].public_id)
        self.assertEqual({"connector", "network", "speed"}, {f.kind for f in detail.facets})
        self.assertGreater(detail.neighbours[0].distance_km, 0)

    def test_an_unknown_field_is_ignored_rather_than_raised(self):
        body = fixture("countries")
        body["data"][0]["something_new"] = 1
        ca, _ = client(body)
        self.assertEqual("AU", ca.countries()[0].iso2)


class TestTrips(unittest.TestCase):
    def test_a_trip_sends_both_ends_as_latitude_comma_longitude(self):
        ca, rec = client(fixture("trip"))
        ca.plan_trip((-37.8136, 144.9631), (-33.8688, 151.2093), range_km=400)

        self.assertEqual("/v1/trips/plan", rec.path)
        self.assertEqual(["-37.8136,144.9631"], rec.query["from"])
        self.assertEqual(["-33.8688,151.2093"], rec.query["to"])
        self.assertEqual(["400"], rec.query["range_km"])
        self.assertEqual({"from", "to", "range_km"}, set(rec.query))

    def test_every_option_is_sent(self):
        ca, rec = client(fixture("trip"))
        ca.plan_trip((-37.81, 144.96), (-33.87, 151.21), range_km=420, reserve=15, start=90,
                     charge_to=85, battery_kwh=75, max_dc_kw=250, max_ac_kw=11, min_kw=100,
                     connectors=["ccs2", "type-2"])
        q = rec.query
        self.assertEqual(["15"], q["reserve"])
        self.assertEqual(["90"], q["start"])
        self.assertEqual(["85"], q["charge_to"])
        self.assertEqual(["75"], q["battery_kwh"])
        self.assertEqual(["250"], q["max_dc_kw"])
        self.assertEqual(["11"], q["max_ac_kw"])
        self.assertEqual(["100"], q["min_kw"])
        # Comma separated here, unlike nearby: that is how /v1/trips/plan reads it.
        self.assertEqual(["ccs2,type-2"], q["connectors"])

    def test_the_plan_reads_route_stops_and_totals(self):
        ca, _ = client(fixture("trip"))
        plan = ca.plan_trip((-37.81, 144.96), (-33.87, 151.21), range_km=400)

        self.assertTrue(plan.feasible)
        self.assertGreater(plan.route.distance_km, 800)
        self.assertEqual(3, len(plan.route.line))
        # The line is longitude, latitude pairs, as GeoJSON has it.
        self.assertAlmostEqual(144.96, plan.route.line[0][0], places=1)
        stop = plan.stops[0]
        self.assertEqual("xyjobdss", stop.site.public_id)
        self.assertTrue(stop.dc)
        self.assertGreater(stop.depart_pct, stop.arrive_pct)
        self.assertEqual(plan.drive_min + plan.charge_min, plan.total_min)
        self.assertIsNone(plan.gap)

    def test_an_infeasible_plan_says_where_the_gap_is(self):
        ca, _ = client(fixture("trip_gap"))
        plan = ca.plan_trip((-31.95, 115.86), (-34.93, 138.6), range_km=300)
        self.assertFalse(plan.feasible)
        self.assertEqual(410.2, plan.gap.from_km)
        self.assertEqual(790.8, plan.gap.to_km)

    def test_the_same_point_twice_is_refused(self):
        ca, rec = client()
        with self.assertRaises(ValueError):
            ca.plan_trip((-37.81, 144.96), (-37.81, 144.96), range_km=400)
        self.assertEqual([], rec.calls)

    def test_options_outside_the_services_bounds_are_refused(self):
        ca, rec = client()
        for kwargs in ({"range_km": 49}, {"range_km": 1501}, {"reserve": 4}, {"reserve": 51},
                       {"charge_to": 49}, {"battery_kwh": 9}, {"max_dc_kw": 401},
                       {"max_ac_kw": 2}, {"min_kw": 351}, {"start": 101},
                       {"connectors": ["tesla"]}):
            args = {"range_km": 400, **kwargs}
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ca.plan_trip((-37.81, 144.96), (-33.87, 151.21), **args)
        self.assertEqual([], rec.calls)

    def test_a_point_must_be_a_pair(self):
        ca, _ = client()
        for bad in ((1,), (1, 2, 3), "-37.8,144.9", None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ca.plan_trip(bad, (-33.87, 151.21), range_km=400)


class TestVehicles(unittest.TestCase):
    def test_vehicles_with_a_term(self):
        ca, rec = client(fixture("vehicles"))
        cars = ca.vehicles(q="model 3", limit=2)
        self.assertEqual("/v1/vehicles", rec.path)
        self.assertEqual(["model 3"], rec.query["q"])
        self.assertEqual(["2"], rec.query["limit"])
        self.assertEqual("tesla-model-3", cars[0].slug)
        self.assertEqual(("ccs2",), cars[0].dc_ports)
        self.assertEqual(0, cars[0].curve[0].pct)
        self.assertFalse(cars[0].curve_is_generic)

    def test_all_is_sent_only_when_asked(self):
        ca, rec = client(fixture("vehicles"))
        ca.vehicles()
        self.assertEqual({}, rec.query)
        ca.vehicles(all=True)
        self.assertEqual(["true"], rec.query["all"])

    def test_a_limit_outside_one_to_a_hundred_is_refused(self):
        ca, rec = client()
        for limit in (0, 101, -1):
            with self.assertRaises(ValueError):
                ca.vehicles(limit=limit)
        self.assertEqual([], rec.calls)

    def test_one_vehicle_carries_its_charging_times(self):
        ca, rec = client(fixture("vehicle"))
        car = ca.vehicle("tesla-model-3")
        self.assertEqual("/v1/vehicles/tesla-model-3", rec.path)
        self.assertEqual("Tesla", car.brand)
        self.assertEqual(50, car.charging[0].charger_kw)
        self.assertGreater(car.charging[0].minutes_10_80, 0)


class TestRedirect(unittest.TestCase):
    def test_a_moved_page_says_where_it_went(self):
        ca, rec = client(fixture("redirect"))
        moved = ca.redirect("/en/australia/victoria/hampton/ampcharge/x-abcd2345/")
        self.assertEqual("/v1/redirect", rec.path)
        self.assertEqual(["/en/australia/victoria/hampton/ampcharge/x-abcd2345/"], rec.query["path"])
        self.assertEqual("/en/australia/victoria/sandringham/ampcharge/x-abcd2345/", moved.to)
        self.assertEqual(301, moved.status)
        self.assertEqual("https://chargealong.io/en/australia/victoria/sandringham/ampcharge/x-abcd2345/", moved.url)

    def test_a_page_that_never_moved_is_none(self):
        ca, _ = client(fixture("not_found"), status=404)
        self.assertIsNone(ca.redirect("/en/nowhere/"))

    def test_only_a_path_on_this_site_is_asked_about(self):
        ca, rec = client()
        for bad in ("", "en/x/", "//evil.example/", "https://evil.example/"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ca.redirect(bad)
        self.assertEqual([], rec.calls)


class TestErrors(unittest.TestCase):
    def test_a_bad_request_keeps_the_services_words(self):
        ca, _ = client(fixture("bad_nearby"), status=400)
        with self.assertRaises(BadRequest) as caught:
            ca.countries()
        err = caught.exception
        self.assertEqual(400, err.status)
        self.assertEqual("invalid nearby request", err.title)
        self.assertEqual("lat: must be between -90 and 90", err.detail)
        self.assertIn("lat: must be between -90 and 90", str(err))

    def test_rate_limited_carries_retry_after(self):
        rec_calls = []

        def transport(method, url, headers, timeout):
            rec_calls.append(url)
            return 429, b'{"title": "too many requests"}', {"Retry-After": "30"}

        ca = ChargeAlong(transport=transport)
        with self.assertRaises(RateLimited) as caught:
            ca.countries()
        self.assertEqual(30.0, caught.exception.retry_after)

    def test_a_server_error_is_the_base_class(self):
        ca, _ = client({"title": "temporarily unavailable"}, status=503)
        with self.assertRaises(ChargeAlongError) as caught:
            ca.countries()
        self.assertNotIsInstance(caught.exception, (BadRequest, NotFound))
        self.assertEqual(503, caught.exception.status)

    def test_no_road_between_the_points_is_no_route(self):
        # Sydney to Auckland has no road: an answer to show, not a parameter
        # to fix. Still a BadRequest for code that catches the broad class.
        ca, _ = client({"status": 422, "title": "no road route between these points"}, status=422)
        with self.assertRaises(NoRoute) as caught:
            ca.plan_trip((-33.87, 151.21), (-36.85, 174.76), range_km=400)
        self.assertIsInstance(caught.exception, BadRequest)
        self.assertEqual(422, caught.exception.status)


class TestMisc(unittest.TestCase):
    def test_connectors_match_the_service(self):
        self.assertEqual(("ccs2", "chademo", "type-2", "nacs", "ccs1", "type-1", "gbt"), CONNECTORS)

    def test_requests_identify_the_library(self):
        from chargealong import __version__

        ca, rec = client(fixture("countries"))
        ca.countries()
        self.assertEqual(f"chargealong-python/{__version__}", rec.calls[-1][2]["User-Agent"])
        self.assertEqual("application/json", rec.calls[-1][2]["Accept"])


if __name__ == "__main__":
    unittest.main()
