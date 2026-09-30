# chargealong

**Public EV chargers, road trips through charging stops, and how fast electric
cars charge, as an API.** Find the chargers nearest a point, plan Melbourne to
Sydney with the stops and the minutes at each, or look up a car's charging
curve.

- Free and keyless. No account, nothing to configure
- No dependencies: the standard library only
- Typed dataclasses with the field names the API sends, so the docs and your
  editor agree
- Every parameter checked against the service's own limits before a request is
  spent on it

```sh
pip install chargealong
```

## Quick start

```python
from chargealong import ChargeAlong

ca = ChargeAlong()

near = ca.nearby(-37.7404, 144.9633, min_kw=50, limit=5)
for site in near.sites:
    print(site.name, site.network_name, site.max_kw, "kW", site.distance_m, "m")
    print(site.url)
```

Nearest first, within 50 km unless you pass `radius_km` (up to 150), at most
30 sites unless you pass `limit` (up to 50). `near.near` is the closest named
place, for a heading.

Only `status == "active"` sites are worth sending a driver to.

### Filters

```python
ca.nearby(lat, lng,
          min_kw=100,                     # a stop, not a top up
          connector=["ccs2", "chademo"],  # any of these
          network="evie-networks")
```

`CONNECTORS` lists the standards: `ccs2`, `chademo`, `type-2`, `nacs`,
`ccs1`, `type-1`, `gbt`.

## Plan a trip

```python
plan = ca.plan_trip((-37.8136, 144.9631), (-33.8688, 151.2093), range_km=400)

print(plan.route.distance_km, "km,", plan.total_min, "minutes in all")
for stop in plan.stops:
    print(f"{stop.site.name}: arrive {stop.arrive_pct}%, "
          f"charge {stop.charge_min} min to {stop.depart_pct}%")
```

`range_km` is how far the car really goes on a full battery. The rest is
optional: `reserve` (never arrive below, default 20%), `start` (default 100%),
`charge_to` (default 80%), `battery_kwh`, `max_dc_kw`, `max_ac_kw`, `min_kw`
(ignore slower chargers, default 50) and `connectors` (default `ccs2` and
`type-2`).

`plan.feasible` false is an answer, not an error: the car cannot make it
without dropping below the reserve, and `plan.gap` says where, in km from the
start. No road between the points raises `NoRoute`: Sydney to Auckland, say.
Trips are planned in Australia and New Zealand.

`plan.route.line` is the road as `(longitude, latitude)` pairs, ready for a
GeoJSON LineString.

## Electric cars

```python
for car in ca.vehicles("model 3", limit=5):
    print(car.brand, car.model, car.range_km, "km", car.dc_kw, "kW DC")

car = ca.vehicle("tesla-model-3")
for t in car.charging:
    print(f"10 to 80% on {t.charger_kw} kW: {t.minutes_10_80} min")
```

## One charging site

```python
detail = ca.site("hwqb4abf")

print(detail.site.name, detail.site.cost.text)
for c in detail.connectors:
    print(c.label, c.power_kw, "kW x", c.quantity)
print(detail.reviews.summary.count, "reviews, last worked", detail.reviews.summary.last_worked_at)
```

The public id is permanent: store it rather than a name or a path. A site
removed from its source still answers, with `site.status` of `"removed"`, and an
id that never existed raises `NotFound`, so code holding stored ids can tell a
retired charger from a typo.

## Search

```python
found = ca.search("coburg", prefer="AU")
found.localities   # suburbs and towns, exact matches first
found.postcodes    # a postcode's centre, for nearby()
found.sites        # sites by name
```

`prefer` is a two letter country code whose places rank first. A term with
fewer than three letters or digits answers empty without a request.

## Browsing

`countries()`, `overview()`, `country("australia")`,
`region("australia", "victoria")`, `networks("australia")`,
`network("australia", "chargefox")` and
`locality("australia", "victoria", "coburg")` read the directory the way the
site's pages do. Rows that carry a `path` have a `url` for that page on
chargealong.io.

`redirect("/en/...")` says where a moved page went, or `None` if it did not
move.

## Errors

```python
from chargealong import BadRequest, NoRoute, NotFound, RateLimited

try:
    ca.plan_trip(a, b, range_km=400)
except NoRoute:
    ...  # no road between them
except BadRequest as e:
    print(e.detail)  # "range_km: must be between 50 and 1500"
```

Every error is a `ChargeAlongError` carrying the service's own `title` and
`detail`, which say what to do. `RateLimited` carries `retry_after` in seconds
when the service said.

## Being a good citizen

The API is free and cached at the edge. Keep answers rather than fetching them
again, debounce anything a person types, and make one client and share it.

## Attribution

Charging site data is from [Open Charge Map](https://openchargemap.org/)
contributors, Transport for NSW and the Queensland Government, and places from
[GeoNames](https://www.geonames.org/), all under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Car data is from
Open EV Data. Publishing what you get back means carrying those credits: see
[where the data comes from](https://chargealong.io/en/guides/where-the-data-comes-from/)
and the [terms](https://chargealong.io/en/terms/).

## Also available

| Language | Package |
|---|---|
| JavaScript and TypeScript | [`@chargealong/client`](https://www.npmjs.com/package/@chargealong/client) ([source](https://github.com/chargealong/chargealong-js)) |

API reference: [chargealong.io/docs](https://chargealong.io/docs/).

## Licence

MIT for this library. The data carries its own licences, above.
