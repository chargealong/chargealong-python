"""The controls that stop this client being turned against its caller.

There is no key to leak here: the API is keyless. What passes through instead
is where somebody is, as a coordinate or a place name, and the URLs this
client builds from whatever a caller passes in. So: the destination cannot be
moved off https, an id or slug cannot walk out of its path prefix, nothing a
caller supplies reaches a header or a query unencoded, and a number that is
not a number never reaches a URL.
"""

from __future__ import annotations

import json
import math
import unittest
import urllib.error
import urllib.request

from chargealong import DEFAULT_BASE_URL, ChargeAlong
from chargealong._client import _MAX_BODY, _NoRedirects


class Recorder:
    def __init__(self, body=None):
        self.calls = []
        self.body = body if body is not None else {"data": {}}

    def __call__(self, method, url, headers, timeout):
        self.calls.append((method, url, headers, timeout))
        return 200, json.dumps(self.body).encode()

    @property
    def url(self):
        return self.calls[-1][1]


class TestWhereRequestsMayGo(unittest.TestCase):
    def test_the_default_is_https(self):
        self.assertEqual("https://api.chargealong.io", DEFAULT_BASE_URL)

    def test_plaintext_http_to_a_public_host_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            ChargeAlong(base_url="http://api.chargealong.io")
        self.assertIn("clear", str(caught.exception))

    def test_loopback_over_http_is_allowed_for_a_test_server(self):
        for url in ("http://localhost:8080", "http://127.0.0.1:8080", "http://[::1]:8080"):
            ChargeAlong(base_url=url)

    def test_a_host_that_only_starts_like_loopback_is_refused(self):
        for url in ("http://localhost.evil.example", "http://127.0.0.1.evil.example"):
            with self.assertRaises(ValueError):
                ChargeAlong(base_url=url)

    def test_another_scheme_is_refused(self):
        for url in ("ftp://api.chargealong.io", "file:///etc/passwd", "gopher://x"):
            with self.assertRaises(ValueError):
                ChargeAlong(base_url=url)

    def test_a_relative_or_empty_base_url_is_refused(self):
        for url in ("", "api.chargealong.io", "/v1"):
            with self.assertRaises(ValueError):
                ChargeAlong(base_url=url)

    def test_a_base_url_carrying_credentials_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            ChargeAlong(base_url="https://api.chargealong.io:pass@evil.example")
        self.assertIn("credentials", str(caught.exception))

    def test_a_base_url_with_a_query_or_fragment_is_refused(self):
        # Either would swallow the path every call appends.
        for url in ("https://api.chargealong.io?x=1", "https://api.chargealong.io#x"):
            with self.assertRaises(ValueError):
                ChargeAlong(base_url=url)

    def test_no_redirect_is_followed(self):
        # The API never redirects, so one is a proxy or a hijack. A query here
        # is somebody's position; it goes nowhere it was not sent.
        handler = _NoRedirects()
        req = urllib.request.Request("https://api.chargealong.io/v1/nearby?lat=-37.7&lng=144.9")
        for target in (
            "https://evil.example/v1/nearby?lat=-37.7&lng=144.9",
            "http://api.chargealong.io/v1/nearby?lat=-37.7&lng=144.9",
            "https://api.chargealong.io/v1/elsewhere",
        ):
            with self.assertRaises(urllib.error.HTTPError):
                handler.redirect_request(req, None, 302, "Found", {}, target)

    def test_every_call_stays_under_the_base_url(self):
        rec = Recorder()
        ca = ChargeAlong(base_url="https://proxy.example.com/ca/", transport=rec)
        ca.countries()
        ca.site("hwqb4abf")
        ca.locality("australia", "victoria", "batman")
        for _, url, _, _ in rec.calls:
            self.assertTrue(url.startswith("https://proxy.example.com/ca/v1/"), url)


class TestWhatReachesTheWire(unittest.TestCase):
    def test_a_slug_cannot_walk_out_of_its_path_prefix(self):
        rec = Recorder()
        ca = ChargeAlong(transport=rec)

        ca.country("../../v1/admin/queue")
        self.assertNotIn("/v1/admin", rec.url)
        self.assertIn("..%2F..%2Fv1%2Fadmin%2Fqueue", rec.url)

        ca.locality("australia", "victoria", "../../../v1/admin")
        self.assertNotIn("/v1/admin", rec.url)

        ca.site("..%2F..")
        self.assertEqual("https://api.chargealong.io/v1/sites/..%252F..", rec.url)

    def test_dot_segments_are_refused(self):
        rec = Recorder()
        ca = ChargeAlong(transport=rec)
        for call in (
            lambda: ca.site("."),
            lambda: ca.site(".."),
            lambda: ca.country(".."),
            lambda: ca.network("australia", "."),
            lambda: ca.vehicle(".."),
        ):
            with self.assertRaises(ValueError):
                call()
        self.assertEqual([], rec.calls)

    def test_a_slug_cannot_smuggle_a_query_string(self):
        rec = Recorder()
        ChargeAlong(transport=rec).country("australia?limit=9999")
        self.assertNotIn("?", rec.url)

    def test_an_empty_slug_is_refused_rather_than_becoming_a_list_call(self):
        rec = Recorder()
        ca = ChargeAlong(transport=rec)
        for call in (
            lambda: ca.country(""),
            lambda: ca.locality("australia", "", "coburg"),
            lambda: ca.site("  "),
            lambda: ca.vehicle(""),
            lambda: ca.networks(""),
        ):
            with self.assertRaises(ValueError):
                call()
        self.assertEqual([], rec.calls)

    def test_a_query_cannot_inject_another_parameter(self):
        rec = Recorder()
        ChargeAlong(transport=rec).search("coburg&prefer=US&limit=9999")
        self.assertIn("q=coburg%26prefer%3DUS%26limit%3D9999", rec.url)
        self.assertNotIn("&prefer=US", rec.url)

    def test_a_query_with_crlf_cannot_split_the_request(self):
        rec = Recorder()
        ChargeAlong(transport=rec).search("coburg\r\nX-Injected: 1")
        self.assertNotIn("\r", rec.url)
        self.assertNotIn("\n", rec.url)

    def test_a_network_filter_cannot_carry_a_parameter(self):
        rec = Recorder()
        with self.assertRaises(ValueError):
            ChargeAlong(transport=rec).nearby(-37.7, 144.9, network="evie&limit=50")
        self.assertEqual([], rec.calls)

    def test_nan_and_infinity_never_reach_a_url(self):
        rec = Recorder()
        ca = ChargeAlong(transport=rec)
        for lat, lng in ((math.nan, 144.9), (-37.7, math.inf), (91, 0), (0, -181), ("x", 0)):
            with self.assertRaises(ValueError):
                ca.nearby(lat, lng)
            with self.assertRaises(ValueError):
                ca.plan_trip((lat, lng), (-33.87, 151.21), range_km=400)
        for bad in (math.nan, math.inf, -math.inf, "fast"):
            with self.assertRaises(ValueError):
                ca.nearby(-37.7, 144.9, min_kw=bad)
            with self.assertRaises(ValueError):
                ca.plan_trip((-37.8, 144.9), (-33.87, 151.21), range_km=bad)
        self.assertEqual([], rec.calls)

    def test_a_count_must_be_a_whole_number(self):
        rec = Recorder()
        ca = ChargeAlong(transport=rec)
        for bad in (2.5, True, "5", math.nan):
            with self.assertRaises(ValueError):
                ca.nearby(-37.7, 144.9, limit=bad)
            with self.assertRaises(ValueError):
                ca.vehicles(limit=bad)
        self.assertEqual([], rec.calls)

    def test_no_credential_header_is_ever_sent(self):
        rec = Recorder({"data": []})
        ChargeAlong(transport=rec).countries()
        self.assertEqual({"Accept", "User-Agent"}, set(rec.calls[-1][2]))


class TestWhatComesBack(unittest.TestCase):
    def test_a_body_that_is_not_an_object_does_not_crash_the_parse(self):
        for raw in (b"[1,2,3]", b'"gotcha"', b"null", b"", b"{"):
            ca = ChargeAlong(transport=lambda m, u, h, t, raw=raw: (200, raw))
            self.assertEqual([], ca.countries())
            self.assertEqual((), ca.nearby(-37.7, 144.9).sites)

    def test_a_problem_document_does_not_decide_whether_it_failed(self):
        body = json.dumps({"data": [], "status": 500, "title": "error"}).encode()
        ca = ChargeAlong(transport=lambda m, u, h, t: (200, body))
        self.assertEqual([], ca.countries())

    def test_the_status_decides_even_when_the_body_says_otherwise(self):
        from chargealong import ChargeAlongError

        body = json.dumps({"data": [{"iso2": "AU"}], "status": 200}).encode()
        ca = ChargeAlong(transport=lambda m, u, h, t: (502, body))
        with self.assertRaises(ChargeAlongError):
            ca.countries()

    def test_rows_of_the_wrong_type_are_skipped(self):
        body = json.dumps({"data": [1, "x", None, {"iso2": "AU"}]}).encode()
        ca = ChargeAlong(transport=lambda m, u, h, t: (200, body))
        self.assertEqual(["AU"], [c.iso2 for c in ca.countries()])

    def test_a_path_from_the_api_cannot_point_off_the_site(self):
        # url joins path onto chargealong.io. A path that is really a host
        # must not become a link to somewhere else.
        from chargealong import Site

        for path in ("//evil.example/x", "https://evil.example/", "javascript:alert(1)", "en/x"):
            self.assertEqual("", Site.from_json({"path": path}).url, path)

    def test_reads_are_bounded(self):
        self.assertLessEqual(_MAX_BODY, 64 << 20)
        self.assertGreater(_MAX_BODY, 4 << 20)  # a network page is well over 100 KB


if __name__ == "__main__":
    unittest.main()
