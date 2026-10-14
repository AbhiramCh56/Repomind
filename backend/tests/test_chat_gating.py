import inspect
import unittest
from unittest import mock

from fastapi import HTTPException

from app.api import deps
from app.api.v1 import chat
from app.core.config import settings


def _is_gated(func) -> bool:
    """True when a route function declares the chat feature-gate dependency."""
    for parameter in inspect.signature(func).parameters.values():
        if getattr(parameter.default, "dependency", None) is deps.require_chat_enabled:
            return True
    return False


class RequireChatEnabledTest(unittest.TestCase):
    def test_enabled_is_allowed(self):
        with mock.patch.object(settings, "CHAT_ENABLED", True):
            self.assertIsNone(deps.require_chat_enabled())

    def test_disabled_raises_503(self):
        with mock.patch.object(settings, "CHAT_ENABLED", False):
            with self.assertRaises(HTTPException) as ctx:
                deps.require_chat_enabled()
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("unavailable", ctx.exception.detail)


class ChatEndpointWiringTest(unittest.TestCase):
    def test_ask_endpoint_is_gated(self):
        self.assertTrue(_is_gated(chat.chat_with_repo))

    def test_stream_endpoint_is_gated(self):
        self.assertTrue(_is_gated(chat.chat_with_repo_stream))

    def test_history_endpoints_are_not_gated(self):
        self.assertFalse(_is_gated(chat.get_sessions))
        self.assertFalse(_is_gated(chat.get_session_messages))


if __name__ == "__main__":
    unittest.main()
