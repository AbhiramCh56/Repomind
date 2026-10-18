import inspect
import unittest
from types import SimpleNamespace
from unittest import mock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from app.api.v1 import auth
from app.core import rate_limit
from app.core.config import settings
from app.core.rate_limit import Limit, SlidingWindowStore
from app.db.session import get_db


class FakeClock:
    """Deterministic monotonic clock so the window never depends on wall time."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _dependencies(func) -> list:
    """The dependency callables a route declares (mirrors test_chat_gating)."""
    return [
        parameter.default.dependency
        for parameter in inspect.signature(func).parameters.values()
        if getattr(parameter.default, "dependency", None) is not None
    ]


class SlidingWindowStoreTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.store = SlidingWindowStore(clock=self.clock)
        self.limit = Limit("test", 3, 60)

    def test_allows_up_to_the_budget(self):
        for _ in range(3):
            self.assertIsNone(self.store.check("k", self.limit))

    def test_rejects_past_the_budget(self):
        for _ in range(3):
            self.store.check("k", self.limit)
        retry = self.store.check("k", self.limit)
        self.assertIsNotNone(retry)
        self.assertGreater(retry, 0)
        self.assertLessEqual(retry, 60)

    def test_window_slides(self):
        for _ in range(3):
            self.store.check("k", self.limit)
        self.assertIsNotNone(self.store.check("k", self.limit))
        self.clock.advance(61)
        self.assertIsNone(self.store.check("k", self.limit))

    def test_keys_are_independent(self):
        for _ in range(3):
            self.store.check("a", self.limit)
        self.assertIsNone(self.store.check("b", self.limit))

    def test_rejected_hits_do_not_extend_the_lockout(self):
        for _ in range(3):
            self.store.check("k", self.limit)
        first = self.store.check("k", self.limit)
        self.clock.advance(1)
        second = self.store.check("k", self.limit)
        # Draining towards the window edge, not pushed back by each attempt.
        self.assertLess(second, first)

    def test_key_cap_is_enforced(self):
        store = SlidingWindowStore(max_keys=5, clock=self.clock)
        for index in range(50):
            store.check(f"k{index}", self.limit)
        self.assertLessEqual(len(store), 5)


class EnforceTest(unittest.TestCase):
    def setUp(self):
        self.store = SlidingWindowStore(clock=FakeClock())
        self.limits = (Limit("a", 2, 60),)

    def test_raises_429_with_retry_after(self):
        with mock.patch.object(settings, "RATE_LIMIT_ENABLED", True):
            rate_limit._enforce(self.store, "ip", self.limits)
            rate_limit._enforce(self.store, "ip", self.limits)
            with self.assertRaises(HTTPException) as ctx:
                rate_limit._enforce(self.store, "ip", self.limits)
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertIn("Retry-After", ctx.exception.headers)

    def test_disabled_flag_bypasses_limiting(self):
        with mock.patch.object(settings, "RATE_LIMIT_ENABLED", False):
            for _ in range(50):
                rate_limit._enforce(self.store, "ip", self.limits)
        self.assertEqual(len(self.store), 0)

    def test_multiple_limits_take_the_longest_retry(self):
        limits = (Limit("short", 5, 30), Limit("long", 2, 900))
        with mock.patch.object(settings, "RATE_LIMIT_ENABLED", True):
            rate_limit._enforce(self.store, "x", limits)
            rate_limit._enforce(self.store, "x", limits)
            with self.assertRaises(HTTPException) as ctx:
                rate_limit._enforce(self.store, "x", limits)
        # Bounded by the 900s account window, not the 30s address window.
        self.assertGreater(int(ctx.exception.headers["Retry-After"]), 30)


class ClientIpTest(unittest.TestCase):
    def test_reads_the_peer_address(self):
        request = SimpleNamespace(client=SimpleNamespace(host="1.2.3.4"))
        with mock.patch.object(settings, "CLIENT_IP_HEADER", None):
            self.assertEqual(rate_limit.client_ip(request), "1.2.3.4")

    def test_falls_back_when_the_address_is_missing(self):
        with mock.patch.object(settings, "CLIENT_IP_HEADER", None):
            self.assertEqual(
                rate_limit.client_ip(SimpleNamespace(client=None)), "unknown"
            )
            self.assertEqual(
                rate_limit.client_ip(SimpleNamespace(client=SimpleNamespace(host=None))),
                "unknown",
            )

    def test_prefers_the_configured_header(self):
        request = SimpleNamespace(
            headers={"cf-connecting-ip": "9.9.9.9"},
            client=SimpleNamespace(host="10.0.0.1"),
        )
        with mock.patch.object(settings, "CLIENT_IP_HEADER", "cf-connecting-ip"):
            self.assertEqual(rate_limit.client_ip(request), "9.9.9.9")

    def test_header_lookup_is_case_insensitive(self):
        # Cloudflare sends "CF-Connecting-IP" with capitals; Starlette's Headers
        # lowercases keys, so the configured lowercase name must still match.
        request = SimpleNamespace(
            headers=Headers({"CF-Connecting-IP": "9.9.9.9"}),
            client=SimpleNamespace(host="10.0.0.1"),
        )
        with mock.patch.object(settings, "CLIENT_IP_HEADER", "cf-connecting-ip"):
            self.assertEqual(rate_limit.client_ip(request), "9.9.9.9")

    def test_configured_header_is_ignored_when_absent(self):
        request = SimpleNamespace(headers={}, client=SimpleNamespace(host="10.0.0.1"))
        with mock.patch.object(settings, "CLIENT_IP_HEADER", "cf-connecting-ip"):
            self.assertEqual(rate_limit.client_ip(request), "10.0.0.1")

    def test_header_is_ignored_when_not_configured(self):
        request = SimpleNamespace(
            headers={"cf-connecting-ip": "9.9.9.9"},
            client=SimpleNamespace(host="10.0.0.1"),
        )
        with mock.patch.object(settings, "CLIENT_IP_HEADER", None):
            self.assertEqual(rate_limit.client_ip(request), "10.0.0.1")

    def test_takes_the_leftmost_value_from_a_forwarded_list(self):
        request = SimpleNamespace(
            headers={"x-forwarded-for": "9.9.9.9, 10.0.0.1"},
            client=SimpleNamespace(host="10.0.0.1"),
        )
        with mock.patch.object(settings, "CLIENT_IP_HEADER", "x-forwarded-for"):
            self.assertEqual(rate_limit.client_ip(request), "9.9.9.9")


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.store = SlidingWindowStore(clock=FakeClock())

    def test_ip_guard_separates_addresses(self):
        guard = rate_limit.limit_by_ip(Limit("ip", 1, 60), store=self.store)
        with mock.patch.object(settings, "RATE_LIMIT_ENABLED", True):
            guard(SimpleNamespace(client=SimpleNamespace(host="1.1.1.1")))
            guard(SimpleNamespace(client=SimpleNamespace(host="2.2.2.2")))
            with self.assertRaises(HTTPException):
                guard(SimpleNamespace(client=SimpleNamespace(host="1.1.1.1")))

    def test_account_guard_is_case_insensitive(self):
        guard = rate_limit.limit_by_account(Limit("acct", 2, 60), store=self.store)
        with mock.patch.object(settings, "RATE_LIMIT_ENABLED", True):
            guard(form_data=SimpleNamespace(username="Alice"))
            guard(form_data=SimpleNamespace(username="alice"))
            with self.assertRaises(HTTPException):
                guard(form_data=SimpleNamespace(username="ALICE"))

    def test_account_guard_tolerates_a_blank_username(self):
        guard = rate_limit.limit_by_account(Limit("acct", 1, 60), store=self.store)
        with mock.patch.object(settings, "RATE_LIMIT_ENABLED", True):
            guard(form_data=SimpleNamespace(username=""))
            with self.assertRaises(HTTPException):
                guard(form_data=SimpleNamespace(username=None))


class AuthRouteWiringTest(unittest.TestCase):
    def test_register_is_ip_limited(self):
        self.assertIn(auth._register_ip_guard, _dependencies(auth.register))

    def test_login_is_ip_and_account_limited(self):
        deps = _dependencies(auth.login)
        self.assertIn(auth._login_ip_guard, deps)
        self.assertIn(auth._login_account_guard, deps)

    def test_refresh_is_ip_limited(self):
        self.assertIn(auth._refresh_ip_guard, _dependencies(auth.refresh_token))

    def test_read_only_routes_are_not_rate_limited(self):
        for guard in (
            auth._register_ip_guard,
            auth._login_ip_guard,
            auth._login_account_guard,
            auth._refresh_ip_guard,
        ):
            self.assertNotIn(guard, _dependencies(auth.get_current_user_profile))


class _EmptyQuery:
    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return None


class _EmptySession:
    """Stands in for the DB session; a lookup always misses, so login answers
    'incorrect credentials' (400) and never reaches bcrypt's success path."""

    def query(self, *args, **kwargs):
        return _EmptyQuery()


class LoginEndpointTest(unittest.TestCase):
    """End to end: the guard fires inside FastAPI's real request cycle, not just
    in the route signature. Budgets come from settings, so the numbers here
    follow config rather than duplicating it (LOGIN_IP_LIMIT must stay above
    LOGIN_ACCOUNT_LIMIT for the account guard to be the one that trips)."""

    def setUp(self):
        rate_limit._store.clear()
        app = FastAPI()
        app.include_router(auth.router, prefix="/auth")
        app.dependency_overrides[get_db] = _EmptySession
        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        rate_limit._store.clear()

    def test_login_is_throttled_once_the_account_budget_is_spent(self):
        budget = settings.LOGIN_ACCOUNT_LIMIT
        responses = [
            self.client.post(
                "/auth/login",
                data={"username": "throttle@example.com", "password": "wrong"},
            )
            for _ in range(budget + 1)
        ]

        self.assertEqual([r.status_code for r in responses[:budget]], [400] * budget)

        throttled = responses[-1]
        self.assertEqual(throttled.status_code, 429)
        self.assertIn("Retry-After", throttled.headers)
        self.assertEqual(
            throttled.json()["detail"], "Too many requests. Please try again later."
        )


    def test_configured_header_isolates_ip_buckets(self):
        """A real request carrying CF-Connecting-IP must drive the per-IP bucket
        (and two different values must be independent)."""
        with mock.patch.object(settings, "CLIENT_IP_HEADER", "cf-connecting-ip"):
            for index in range(settings.LOGIN_IP_LIMIT):
                response = self.client.post(
                    "/auth/login",
                    data={"username": f"user{index}@example.com", "password": "wrong"},
                    headers={"CF-Connecting-IP": "1.1.1.1"},
                )
                self.assertNotEqual(response.status_code, 429)

            blocked = self.client.post(
                "/auth/login",
                data={"username": "last@example.com", "password": "wrong"},
                headers={"CF-Connecting-IP": "1.1.1.1"},
            )
            self.assertEqual(blocked.status_code, 429)

            other = self.client.post(
                "/auth/login",
                data={"username": "other@example.com", "password": "wrong"},
                headers={"CF-Connecting-IP": "2.2.2.2"},
            )
            self.assertNotEqual(other.status_code, 429)


if __name__ == "__main__":
    unittest.main()
