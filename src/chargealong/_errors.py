"""What the API said when it refused."""

from __future__ import annotations


class ChargeAlongError(Exception):
    """The API refused, and said why.

    The service answers RFC 7807 problem documents: a title and a detail
    written for a person to read and act on, such as which parameter is out of
    range. Collapsing that into "HTTP 400" throws away the only part of the
    answer that says what to do about it.
    """

    def __init__(self, status: int, title: str = "", detail: str = ""):
        self.status = status
        self.title = title
        self.detail = detail
        message = title or f"HTTP {status}"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(f"{status} {message}")


class NotFound(ChargeAlongError):
    """Nothing is filed under that id or slug.

    Its own class because it is an ordinary thing to hit rather than a failure:
    a place with no charging sites has no page, and code walking a list of ids
    will meet this.
    """


class BadRequest(ChargeAlongError):
    """The request could not be served as written. The detail names the
    parameter: "lat: must be between -90 and 90"."""


class NoRoute(BadRequest):
    """No road route between the two points of a trip (422).

    An answer to show rather than a parameter to fix: Sydney to Auckland has
    no road. (Melbourne to Hobart does: the router takes the ferry, and the
    plan comes back infeasible with the crossing as its gap.)
    """


class RateLimited(ChargeAlongError):
    """Too many requests from here.

    The API is free and keyless, and asks callers to be gentle: keep answers
    rather than fetching them again, and debounce anything a person types.

    ``retry_after`` is the seconds the service asked for, when it said.
    """

    def __init__(self, status: int, title: str = "", detail: str = "", retry_after: float | None = None):
        super().__init__(status, title, detail)
        self.retry_after = retry_after


def error_for(status: int, title: str = "", detail: str = "", retry_after: float | None = None) -> ChargeAlongError:
    if status == 404:
        return NotFound(status, title, detail)
    if status == 422:
        return NoRoute(status, title, detail)
    if status == 429:
        return RateLimited(status, title, detail, retry_after)
    if 400 <= status < 500:
        return BadRequest(status, title, detail)
    return ChargeAlongError(status, title, detail)
