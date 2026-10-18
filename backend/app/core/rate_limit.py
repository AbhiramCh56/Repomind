"""
In-process rate limiting for the authentication endpoints.

Why a small in-repo limiter rather than a library:

* ``/auth/login`` takes an ``OAuth2PasswordRequestForm``, so the account name
  lives in the form body. A limiter whose key function only sees the request
  cannot key the login by account, and that per-account limit is the one that
  actually stops credential stuffing (many IPs, one account).
* The store is a per-process sliding-window log. That is correct for a single
  instance and deliberately swappable: running more than one worker or replica
  gives each process its own counters, so the store must be moved to something
  shared (Redis) before scaling out.

Limits are enforced as a dependency, which runs *before* the route body. An
over-budget login therefore never reaches ``bcrypt.checkpw`` - the expensive,
deliberately-slow step that would otherwise make the login route a cheap CPU
denial-of-service target.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from typing import Callable, Deque, Dict, NamedTuple, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.config import settings


class Limit(NamedTuple):
    """One budget: ``times`` hits are allowed per ``seconds``."""

    scope: str
    times: int
    seconds: float


class SlidingWindowStore:
    """
    Sliding-window log: one deque of hit timestamps per key.

    Timestamps older than the window are pruned on every access, and the number
    of keys is capped so a flood of distinct keys (spoofed addresses or
    usernames) cannot grow memory without bound.
    """

    def __init__(
        self,
        max_keys: int = 10_000,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._max_keys = max(1, int(max_keys))
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._hits: Dict[str, Deque[float]] = OrderedDict()

    def check(self, key: str, limit: Limit) -> Optional[float]:
        """
        Record one hit for ``key``.

        Returns the ``Retry-After`` seconds when the budget is already spent,
        otherwise ``None``. A rejected hit is *not* recorded, so the retry time
        is stable and the window drains predictably instead of being pushed back
        by every further attempt.
        """
        now = self._clock()
        cutoff = now - limit.seconds

        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                hits = deque()
                if len(self._hits) >= self._max_keys:
                    # Drop the least-recently-used key rather than growing.
                    self._hits.popitem(last=False)
                self._hits[key] = hits
            else:
                self._hits.move_to_end(key)

            while hits and hits[0] <= cutoff:
                hits.popleft()

            if len(hits) >= limit.times:
                return max(1.0, limit.seconds - (now - hits[0]))

            hits.append(now)
            return None

    def __len__(self) -> int:
        with self._lock:
            return len(self._hits)

    def clear(self) -> None:
        """Forget every counter. Used to isolate tests, and a natural hook for a
        future "unblock" action."""
        with self._lock:
            self._hits.clear()


_store = SlidingWindowStore(max_keys=settings.RATE_LIMIT_MAX_KEYS)


def client_ip(request: Request) -> str:
    """
    The requesting client's address.

    Prefers ``settings.CLIENT_IP_HEADER`` when configured, then falls back to
    ``request.client`` (the socket peer, which uvicorn already rewrites from
    ``X-Forwarded-For`` for proxies it trusts).

    The configured header must be one the edge controls. On Render,
    ``cf-connecting-ip`` is set by Cloudflare to the real client and overwrites
    any client-supplied value, so it cannot be forged; ``x-forwarded-for`` can
    be, because its leftmost entry is client-supplied. Getting this wrong hurts
    both ways - an unset header behind a proxy collapses every client into one
    per-IP bucket, while a forgeable one lets a client pick their own address.
    """
    header = settings.CLIENT_IP_HEADER
    if header:
        raw = request.headers.get(header)
        if raw:
            # The leftmost value is the original client; the rest are proxies.
            candidate = raw.split(",")[0].strip()
            if candidate:
                return candidate

    client = request.client
    return client.host if client and client.host else "unknown"


def _enforce(store: SlidingWindowStore, key: str, limits: tuple) -> None:
    """Charge every limit against ``key``; raise 429 if any budget is spent."""
    if not settings.RATE_LIMIT_ENABLED:
        return

    retry_after = 0.0
    for limit in limits:
        retry = store.check(f"{limit.scope}:{key}", limit)
        if retry is not None:
            retry_after = max(retry_after, retry)

    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again later.",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )


def limit_by_ip(*limits: Limit, store: Optional[SlidingWindowStore] = None) -> Callable:
    """Dependency factory: throttle by client address."""
    target = store or _store

    def dependency(request: Request) -> None:
        _enforce(target, client_ip(request), limits)

    return dependency


def limit_by_account(
    *limits: Limit, store: Optional[SlidingWindowStore] = None
) -> Callable:
    """
    Dependency factory: throttle by the login username.

    Reads the same ``OAuth2PasswordRequestForm`` the route uses; FastAPI caches
    the parsed body within a request, so the form is not read twice. Usernames
    are lower-cased so ``Alice`` and ``alice`` share one budget.
    """
    target = store or _store

    def dependency(form_data: OAuth2PasswordRequestForm = Depends()) -> None:
        account = (form_data.username or "").strip().lower() or "anonymous"
        _enforce(target, f"account:{account}", limits)

    return dependency
