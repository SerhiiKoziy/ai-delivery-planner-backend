"""Simple per-IP fixed-window rate limiting for unauthenticated endpoints
(registration, login) where the caller has no organization yet to key a
plan-based quota off of.

In-memory, not Redis-backed: nothing in this deployment assumes more than a
single API process (no redis/queue service is wired up for the app itself —
only Celery's broker). If this ever runs as multiple worker processes or
instances, swap the in-memory `_WINDOWS` dict for a Redis-backed counter
keyed the same way, since separate processes don't share this dict.
"""

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, Request, status

_WINDOWS: dict[str, deque] = defaultdict(deque)
_LOCK = Lock()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _check_and_record(key: str, max_requests: int, window_seconds: float) -> None:
    now = time.monotonic()
    with _LOCK:
        window = _WINDOWS[key]
        while window and now - window[0] > window_seconds:
            window.popleft()
        if len(window) >= max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later.",
            )
        window.append(now)


def rate_limit_by_ip(scope: str, max_requests: int, window_seconds: float):
    """Return a FastAPI dependency limiting `scope` to `max_requests` per
    `window_seconds` per client IP. `scope` keeps e.g. register/login counted
    in separate windows even for the same caller."""

    def _dependency(request: Request) -> None:
        _check_and_record(f"{scope}:{_client_ip(request)}", max_requests, window_seconds)

    return _dependency


def reset_all_windows_for_tests() -> None:
    """Test-only: clear all rate-limit state so tests don't leak into each other."""
    with _LOCK:
        _WINDOWS.clear()


# Registration: bounds how many accounts one IP can create per hour — the
# main lever against scripted mass sign-up. (Email verification, wired
# separately, stops a created account from being USABLE without a real
# inbox, which closes the gap this alone can't.)
register_rate_limiter = rate_limit_by_ip("register", max_requests=5, window_seconds=3600)

# Login: generous enough for real retry/typo behavior, tight enough to slow
# down credential-stuffing / brute-force attempts against a single IP.
login_rate_limiter = rate_limit_by_ip("login", max_requests=20, window_seconds=60)
