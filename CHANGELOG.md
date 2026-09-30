# Changelog

## 0.1.0

First release.

- `nearby`, `site`, `search`, `plan_trip`, `vehicles`, `vehicle`, `countries`,
  `overview`, `country`, `region`, `networks`, `network`, `locality` and
  `redirect`, covering the free read only surface of api.chargealong.io.
- Every row that carries a `path` has a `url` for its page on chargealong.io.
- `NotFound` and `Gone` tell an id that never existed from a charger that was
  retired; `NoRoute` tells a trip with no road from a parameter to fix.
- Every parameter is checked against the service's own bounds before a
  request is spent on it.
- No dependencies.
