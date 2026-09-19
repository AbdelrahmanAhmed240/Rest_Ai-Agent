#!/usr/bin/env python3
"""Free-only OpenRouter model fallback — focused unit tests.

Mocks all OpenRouter/OpenAI calls. Does NOT consume real API quota.
Tests the agent.reply() fallback chain and free-model validation.
"""

from __future__ import annotations

import unittest
import sys
import os
from unittest.mock import MagicMock, patch

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the REAL openai exception types so our test mock raises them
from openai import RateLimitError as _RealRateLimitError
from openai import AuthenticationError as _RealAuthError

# ---------------------------------------------------------------------------
# Helpers — build the objects the openai client expects
# ---------------------------------------------------------------------------


class _Choice:
    def __init__(self, content: str):
        self.message = _Message(content)


class _Message:
    def __init__(self, content: str):
        self.content = content


class _Response:
    def __init__(self, content: str):
        self.choices = [_Choice(content)]


# ---------------------------------------------------------------------------
# Helper: build a real openai RateLimitError with a minimal httpx response
# so the agent.py except RateLimitError clause matches during tests.
# ---------------------------------------------------------------------------


def _make_rate_limit_error(msg: str = "Rate limit exceeded"):
    import httpx

    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(
        status_code=429,
        request=request,
        content=b'{"error":{"message":"' + msg.replace('"', '\\"') + '","type":"rate_limit_exceeded"}}',
        headers={"content-type": "application/json"},
    )
    return _RealRateLimitError(message=msg, response=response)
from openai import APIError as _RealAPIError

# ---------------------------------------------------------------------------
# Helpers — build the objects the openai client expects
# ---------------------------------------------------------------------------


class _Choice:
    def __init__(self, content: str):
        self.message = _Message(content)


class _Message:
    def __init__(self, content: str):
        self.content = content


class _Response:
    def __init__(self, content: str):
        self.choices = [_Choice(content)]


# ---------------------------------------------------------------------------
# Exception factories — create REAL openai exceptions with httpx objects
# so that agent.py's `except RateLimitError` / `except Exception` clauses
# actually match during testing.
# ---------------------------------------------------------------------------


def _make_rate_limit_error(msg: str = "Rate limit exceeded") -> _RealRateLimitError:
    import httpx

    request = httpx.Request(
        method="POST", url="https://openrouter.ai/api/v1/chat/completions"
    )
    response = httpx.Response(
        status_code=429,
        request=request,
        content=b'{"error": {"message": "' + msg.replace('"', '\\"') + '", "type": "rate_limit_exceeded"}}',
        headers={"content-type": "application/json"},
    )
    return _RealRateLimitError(message=msg, response=response, body={})

def _make_auth_error(msg: str = "Invalid API key"):
    import httpx

    request = httpx.Request(
        method="POST", url="https://openrouter.ai/api/v1/chat/completions"
    )
    response = httpx.Response(
        status_code=401,
        request=request,
        content=b'{"error": {"message": "' + msg.replace('"', '\\"') + '", "type": "authentication_error"}}',
        headers={"content-type": "application/json"},
    )
    return _RealAuthError(message=msg, response=response, body={})

def _make_api_error(msg: str = "Internal server error"):
    import httpx

    request = httpx.Request(
        method="POST", url="https://openrouter.ai/api/v1/chat/completions"
    )
    return _RealAPIError(message=msg, request=request, body={})

# ---------------------------------------------------------------------------
# Patched agent module — we import agent but mock _client and config
# ---------------------------------------------------------------------------


def _make_agent_mock(
    primary_model: str = "nvidia/nemotron-3.5-lightning:free",
    fallback_raw: str = (
        "nvidia/nemotron-3-super-120b-a12b:free,"
        "poolside/laguna-xs-2.1:free,"
        "cohere/north-mini-code:free,"
        "z-ai/glm-5.2:free"
    ),
    call_seq=None,
):
    """Build patched mocks for agent module and return (agent_module, mock_client).

    call_seq: list of dicts describing what each .create() call should return.
      Each entry: {"model": expected_model, "response": _Response|Exception}
      The mock asserts the model matches and returns the response.
    """
    if call_seq is None:
        call_seq = []

    call_index = [0]

    mock_client = MagicMock()
    mock_client.chat.completions.create = MagicMock()

    def _create_side_effect(**kwargs):
        idx = call_index[0]
        if idx >= len(call_seq):
            raise RuntimeError(
                f"Too many LLM calls (expected {len(call_seq)})"
            )
        entry = call_seq[idx]
        expected_model = entry.get("model", "")
        actual_model = kwargs.get("model", "")
        if actual_model != expected_model:
            raise AssertionError(
                f"LLM call #{idx}: expected model={expected_model!r}, "
                f"got model={actual_model!r}"
            )
        call_index[0] += 1
        result = entry.get("response")
        if isinstance(result, Exception):
            raise result
        return result

    mock_client.chat.completions.create.side_effect = _create_side_effect

    mock_openai_cls = MagicMock()
    mock_openai_cls.return_value = mock_client

    # Remove cached agent module if present
    for key in list(sys.modules.keys()):
        if key.startswith("app.services.agent"):
            del sys.modules[key]

    with patch("app.services.agent.config") as mock_config, \
         patch("app.services.agent.OpenAI") as mock_openai_cls_patch:
        mock_config.OPENROUTER_API_KEY = "test-key"
        mock_config.OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
        mock_config.OPENROUTER_MODEL = primary_model
        mock_config.OPENROUTER_FALLBACK_MODELS = fallback_raw
        mock_config.AGENT_TEMPERATURE = 0.3
        mock_config.CHROMA_PERSIST_DIR = "/tmp/chroma"

        def _is_model_free(mid):
            if not mid:
                return False
            return mid.strip().endswith(":free")

        def _get_fallback_models():
            raw = mock_config.OPENROUTER_FALLBACK_MODELS or ""
            seen = set()
            result = []
            primary = mock_config.OPENROUTER_MODEL or ""
            for entry in raw.split(","):
                m = entry.strip()
                if not m:
                    continue
                if not _is_model_free(m):
                    continue
                if m.lower().startswith("google/"):
                    continue
                if m == primary:
                    continue
                if m not in seen:
                    seen.add(m)
                    result.append(m)
            return result

        mock_config.is_model_free = staticmethod(_is_model_free)
        mock_config.get_fallback_models = staticmethod(_get_fallback_models)

        mock_openai_cls_patch.return_value = mock_client

        # Now import agent with mocked config
        from app.services import agent as agent_module

        agent_module._client = mock_client

        return agent_module, mock_client


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestFreeModelValidation(unittest.TestCase):
    """Verify that only :free models can be auto-selected."""

    def test_primary_free_model_passes_validation(self):
        """nvidia/nemotron-3.5-lightning:free is recognized as free."""
        from config import config

        self.assertTrue(
            config.is_model_free("nvidia/nemotron-3.5-lightning:free")
        )
        self.assertTrue(config.is_model_free("openai/gpt-oss-20b:free"))
        self.assertTrue(config.is_model_free("z-ai/glm-5.2:free"))

    def test_paid_model_fails_validation(self):
        """A model without :free is rejected."""
        from config import config

        self.assertFalse(config.is_model_free("openai/gpt-4"))
        self.assertFalse(config.is_model_free("google/gemma-4-31b-it"))
        self.assertFalse(config.is_model_free(""))
        self.assertFalse(config.is_model_free(None))

    def test_google_model_skipped_in_fallback(self):
        """Google models are excluded from fallback even if :free."""
        from config import config

        old = config.OPENROUTER_FALLBACK_MODELS
        try:
            config.OPENROUTER_FALLBACK_MODELS = (
                "nvidia/nemotron-3-super-120b-a12b:free,"
                "google/gemma-4-26b-a4b-it:free,"
                "poolside/laguna-xs-2.1:free"
            )
            result = config.get_fallback_models()
            self.assertNotIn("google/gemma-4-26b-a4b-it:free", result)
            self.assertIn("nvidia/nemotron-3-super-120b-a12b:free", result)
            self.assertIn("poolside/laguna-xs-2.1:free", result)
        finally:
            config.OPENROUTER_FALLBACK_MODELS = old

    def test_paid_fallback_model_skipped(self):
        """A fallback entry without :free is skipped."""
        from config import config

        old = config.OPENROUTER_FALLBACK_MODELS
        try:
            config.OPENROUTER_FALLBACK_MODELS = (
                "nvidia/nemotron-3-super-120b-a12b:free,"
                "openai/gpt-4,"
                "poolside/laguna-xs-2.1:free"
            )
            result = config.get_fallback_models()
            self.assertNotIn("openai/gpt-4", result)
            self.assertEqual(len(result), 2)
        finally:
            config.OPENROUTER_FALLBACK_MODELS = old

    def test_primary_model_not_in_fallback_list(self):
        """The primary model is excluded from its own fallback list."""
        from config import config

        result = config.get_fallback_models()
        self.assertNotIn("nvidia/nemotron-3.5-lightning:free", result)
        expected = [
            "nvidia/nemotron-3-super-120b-a12b:free",
            "poolside/laguna-xs-2.1:free",
            "cohere/north-mini-code:free",
            "z-ai/glm-5.2:free",
        ]
        self.assertEqual(result, expected)

    def test_fallback_order_is_correct(self):
        """Fallback models appear in the configured order."""
        from config import config

        result = config.get_fallback_models()
        expected = [
            "nvidia/nemotron-3-super-120b-a12b:free",
            "poolside/laguna-xs-2.1:free",
            "cohere/north-mini-code:free",
            "z-ai/glm-5.2:free",
        ]
        self.assertEqual(result, expected)


class TestFallbackBehavior(unittest.TestCase):
    """Test the fallback chain in agent.reply()."""

    def test_primary_success(self):
        """Test 1: Primary free model succeeds -> no fallback."""
        resp = _Response("Hello! How can I help you?")
        call_seq = [
            {"model": "nvidia/nemotron-3.5-lightning:free", "response": resp}
        ]
        agent, mock_client = _make_agent_mock(call_seq=call_seq)
        result = agent.reply("sess-1", "hello")
        self.assertEqual(result, "Hello! How can I help you?")
        mock_client.chat.completions.create.assert_called_once()

    def test_fallback_success(self):
        """Test 2: Primary rate-limited -> fallback #2 succeeds."""
        primary_err = _make_rate_limit_error("Rate limit exceeded")
        resp = _Response("I'd recommend the chicken sandwich.")
        call_seq = [
            {
                "model": "nvidia/nemotron-3.5-lightning:free",
                "response": primary_err,
            },
            {
                "model": "nvidia/nemotron-3-super-120b-a12b:free",
                "response": resp,
            },
        ]
        agent, mock_client = _make_agent_mock(call_seq=call_seq)
        result = agent.reply("sess-1", "recommend something")
        self.assertIn("chicken sandwich", result)
        calls = mock_client.chat.completions.create.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            calls[0][1]["model"], "nvidia/nemotron-3.5-lightning:free"
        )
        self.assertEqual(
            calls[1][1]["model"], "nvidia/nemotron-3-super-120b-a12b:free"
        )

    def test_third_model_succeeds(self):
        """Test 3: Primary + #2 rate-limited -> #3 succeeds."""
        err = _make_rate_limit_error("Rate limit exceeded")
        resp = _Response("Try the beef shawarma.")
        call_seq = [
            {
                "model": "nvidia/nemotron-3.5-lightning:free",
                "response": err,
            },
            {
                "model": "nvidia/nemotron-3-super-120b-a12b:free",
                "response": err,
            },
            {
                "model": "poolside/laguna-xs-2.1:free",
                "response": resp,
            },
        ]
        agent, mock_client = _make_agent_mock(call_seq=call_seq)
        result = agent.reply("sess-1", "what do you recommend")
        self.assertIn("beef shawarma", result)
        calls = mock_client.chat.completions.create.call_args_list
        self.assertEqual(len(calls), 3)
        self.assertEqual(
            calls[0][1]["model"], "nvidia/nemotron-3.5-lightning:free"
        )
        self.assertEqual(
            calls[1][1]["model"],
            "nvidia/nemotron-3-super-120b-a12b:free",
        )
        self.assertEqual(calls[2][1]["model"], "poolside/laguna-xs-2.1:free")

    def test_fourth_model_succeeds(self):
        """Test 4: Several models fail -> next free model succeeds."""
        err = _make_rate_limit_error("Daily quota exhausted")
        resp = _Response("I suggest the seafood platter.")
        call_seq = [
            {
                "model": "nvidia/nemotron-3.5-lightning:free",
                "response": err,
            },
            {
                "model": "nvidia/nemotron-3-super-120b-a12b:free",
                "response": err,
            },
            {
                "model": "poolside/laguna-xs-2.1:free",
                "response": err,
            },
            {
                "model": "cohere/north-mini-code:free",
                "response": resp,
            },
        ]
        agent, mock_client = _make_agent_mock(call_seq=call_seq)
        result = agent.reply("sess-1", "help me choose")
        self.assertIn("seafood platter", result)
        calls = mock_client.chat.completions.create.call_args_list
        self.assertEqual(len(calls), 4)

    def test_all_fail_daily_limit(self):
        """Test 5: All free models fail -> friendly unavailable message."""
        err = _make_rate_limit_error(
            "You have reached your daily free tier limit"
        )
        call_seq = [
            {
                "model": "nvidia/nemotron-3.5-lightning:free",
                "response": err,
            },
            {
                "model": "nvidia/nemotron-3-super-120b-a12b:free",
                "response": err,
            },
            {
                "model": "poolside/laguna-xs-2.1:free",
                "response": err,
            },
            {
                "model": "cohere/north-mini-code:free",
                "response": err,
            },
            {"model": "z-ai/glm-5.2:free", "response": err},
        ]
        agent, mock_client = _make_agent_mock(call_seq=call_seq)
        result = agent.reply("sess-1", "can i see the menu")
        self.assertIn("daily usage limit", result)
        calls = mock_client.chat.completions.create.call_args_list
        self.assertEqual(len(calls), 5)

    def test_all_fail_transient(self):
        """Test 5b: All fail transient -> temporarily unavailable."""
        err = _make_rate_limit_error("Rate limit exceeded")
        call_seq = [
            {
                "model": "nvidia/nemotron-3.5-lightning:free",
                "response": err,
            },
            {
                "model": "nvidia/nemotron-3-super-120b-a12b:free",
                "response": err,
            },
            {
                "model": "poolside/laguna-xs-2.1:free",
                "response": err,
            },
            {
                "model": "cohere/north-mini-code:free",
                "response": err,
            },
            {"model": "z-ai/glm-5.2:free", "response": err},
        ]
        agent, mock_client = _make_agent_mock(call_seq=call_seq)
        result = agent.reply("sess-1", "hello")
        self.assertIn("temporarily unavailable", result)
        calls = mock_client.chat.completions.create.call_args_list
        self.assertEqual(len(calls), 5)

    def test_auth_error_primary(self):
        """Test 6: Auth error on primary -> no fallback attempted."""
        err = _make_auth_error("Invalid API key")
        call_seq = [
            {
                "model": "nvidia/nemotron-3.5-lightning:free",
                "response": err,
            }
        ]
        agent, mock_client = _make_agent_mock(call_seq=call_seq)
        result = agent.reply("sess-1", "hello")
        self.assertIn("having trouble", result)
        calls = mock_client.chat.completions.create.call_args_list
        self.assertEqual(len(calls), 1)

    def test_api_error_during_fallback(self):
        """Test 6b: Non-rate-limit error on fallback -> stop."""
        primary_err = _make_rate_limit_error("Rate limit")
        fallback_err = _make_api_error("Internal server error")
        call_seq = [
            {
                "model": "nvidia/nemotron-3.5-lightning:free",
                "response": primary_err,
            },
            {
                "model": "nvidia/nemotron-3-super-120b-a12b:free",
                "response": fallback_err,
            },
        ]
        agent, mock_client = _make_agent_mock(call_seq=call_seq)
        result = agent.reply("sess-1", "hello")
        self.assertIn("having trouble", result)
        calls = mock_client.chat.completions.create.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            calls[1][1]["model"], "nvidia/nemotron-3-super-120b-a12b:free"
        )


class TestPaidModelConfigured(unittest.TestCase):
    """Test 7: Paid primary model -> never requested."""

    def test_paid_primary_never_called(self):
        """If primary is paid, it is skipped and fallback is tried."""
        err = _make_rate_limit_error("Rate limit")
        resp = _Response("Here is the menu.")
        call_seq = [
            {
                "model": "openai/gpt-oss-20b:free",
                "response": resp,
            }
        ]
        agent, mock_client = _make_agent_mock(
            primary_model="openai/gpt-4",
            fallback_raw=(
                "openai/gpt-oss-20b:free,"
                "nvidia/nemotron-3-super-120b-a12b:free"
            ),
            call_seq=call_seq,
        )
        result = agent.reply("sess-1", "hello")
        self.assertIn("menu", result)
        calls = mock_client.chat.completions.create.call_args_list
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["model"], "openai/gpt-oss-20b:free")

    def test_paid_primary_no_fallback(self):
        """Paid primary + no valid fallback -> unavailable message."""
        agent, mock_client = _make_agent_mock(
            primary_model="openai/gpt-4",
            fallback_raw="openai/gpt-4",
            call_seq=[],
        )
        result = agent.reply("sess-1", "hello")
        self.assertIn("temporarily unavailable", result)
        mock_client.chat.completions.create.assert_not_called()


class TestPaidFallbackSkipped(unittest.TestCase):
    """Test 8: Paid fallback model -> skipped, never requested."""

    def test_paid_fallback_skipped(self):
        """A paid model in the fallback list is skipped."""
        resp = _Response("Fallback worked.")
        call_seq = [
            {
                "model": "nvidia/nemotron-3.5-lightning:free",
                "response": _make_rate_limit_error("Rate limit"),
            },
            {
                "model": "openai/gpt-oss-20b:free",
                "response": resp,
            },
        ]
        agent, mock_client = _make_agent_mock(
            fallback_raw="openai/gpt-4,openai/gpt-oss-20b:free",
            call_seq=call_seq,
        )
        result = agent.reply("sess-1", "hello")
        self.assertIn("Fallback worked", result)
        calls = mock_client.chat.completions.create.call_args_list
        models_called = [c[1]["model"] for c in calls]
        self.assertNotIn("openai/gpt-4", models_called)
        self.assertIn("openai/gpt-oss-20b:free", models_called)


class TestGoogleModelSkipped(unittest.TestCase):
    """Test 9: Google model configured -> skipped/never requested."""

    def test_google_fallback_skipped(self):
        """Google :free model in fallback is skipped."""
        resp = _Response("worked.")
        call_seq = [
            {
                "model": "nvidia/nemotron-3.5-lightning:free",
                "response": _make_rate_limit_error("Rate limit"),
            },
            {
                "model": "nvidia/nemotron-3-super-120b-a12b:free",
                "response": resp,
            },
        ]
        agent, mock_client = _make_agent_mock(
            fallback_raw=(
                "google/gemma-4-26b-a4b-it:free,"
                "nvidia/nemotron-3-super-120b-a12b:free"
            ),
            call_seq=call_seq,
        )
        result = agent.reply("sess-1", "hello")
        self.assertIn("worked", result)
        calls = mock_client.chat.completions.create.call_args_list
        models_called = [c[1]["model"] for c in calls]
        self.assertNotIn("google/gemma-4-26b-a4b-it:free", models_called)

    def test_google_primary_skipped(self):
        """Google model as primary is skipped (provider-gated)."""
        resp = _Response("worked.")
        call_seq = [
            {
                "model": "openai/gpt-oss-20b:free",
                "response": resp,
            }
        ]
        agent, mock_client = _make_agent_mock(
            primary_model="google/gemma-4-31b-it",
            fallback_raw="openai/gpt-oss-20b:free",
            call_seq=call_seq,
        )
        result = agent.reply("sess-1", "hello")
        self.assertIn("worked", result)
        calls = mock_client.chat.completions.create.call_args_list
        self.assertNotEqual(calls[0][1]["model"], "google/gemma-4-31b-it")


class TestEachModelAttemptedOnce(unittest.TestCase):
    """Test 10: Each model is attempted at most once per request."""

    def test_no_duplicate_attempts(self):
        """Even with many rate-limit errors, each model is called once."""
        err = _make_rate_limit_error("Rate limit")
        call_seq = [
            {
                "model": "nvidia/nemotron-3.5-lightning:free",
                "response": err,
            },
            {
                "model": "nvidia/nemotron-3-super-120b-a12b:free",
                "response": err,
            },
            {
                "model": "poolside/laguna-xs-2.1:free",
                "response": err,
            },
            {
                "model": "cohere/north-mini-code:free",
                "response": err,
            },
            {"model": "z-ai/glm-5.2:free", "response": err},
        ]
        agent, mock_client = _make_agent_mock(call_seq=call_seq)
        agent.reply("sess-1", "hello")
        calls = mock_client.chat.completions.create.call_args_list
        models = [c[1]["model"] for c in calls]
        self.assertEqual(len(models), len(set(models)))
        self.assertEqual(len(calls), 5)


class TestReasoningStripping(unittest.TestCase):
    """Test 11: Existing reasoning stripping still works."""

    def test_strip_reasoning_called_on_success(self):
        """_strip_reasoning is applied to successful responses."""
        resp = _Response("Analyze user input\n\nHere is the menu.")
        call_seq = [
            {
                "model": "nvidia/nemotron-3.5-lightning:free",
                "response": resp,
            }
        ]
        agent, mock_client = _make_agent_mock(call_seq=call_seq)
        result = agent.reply("sess-1", "hello")
        self.assertNotIn("Analyze user input", result)
        self.assertIn("menu", result)

    def test_strip_reasoning_on_fallback(self):
        """_strip_reasoning is also applied to fallback responses."""
        resp = _Response("Thinking process\n\nThe chicken shawarma is 120.")
        call_seq = [
            {
                "model": "nvidia/nemotron-3.5-lightning:free",
                "response": _make_rate_limit_error("Rate limit"),
            },
            {
                "model": "nvidia/nemotron-3-super-120b-a12b:free",
                "response": resp,
            },
        ]
        agent, mock_client = _make_agent_mock(call_seq=call_seq)
        result = agent.reply("sess-1", "prices")
        self.assertNotIn("Thinking process", result)
        self.assertIn("chicken shawarma", result)


class TestChatResponseFormat(unittest.TestCase):
    """Test 12: Existing chat response format still works."""

    def test_response_is_string(self):
        """reply() returns a plain string."""
        resp = _Response("Hello!")
        call_seq = [
            {
                "model": "nvidia/nemotron-3.5-lightning:free",
                "response": resp,
            }
        ]
        agent, mock_client = _make_agent_mock(call_seq=call_seq)
        result = agent.reply("sess-1", "hello")
        self.assertIsInstance(result, str)

    def test_empty_content_returns_default(self):
        """Empty LLM content returns the default help message."""
        resp = _Response("")
        call_seq = [
            {
                "model": "nvidia/nemotron-3.5-lightning:free",
                "response": resp,
            }
        ]
        agent, mock_client = _make_agent_mock(call_seq=call_seq)
        result = agent.reply("sess-1", "hello")
        self.assertIn("here to help", result)

    def test_history_persisted(self):
        """Conversation history is maintained across calls."""
        call_seq = [
            {
                "model": "nvidia/nemotron-3.5-lightning:free",
                "response": _Response("Hello!"),
            },
            {
                "model": "nvidia/nemotron-3.5-lightning:free",
                "response": _Response("How can I help?"),
            },
        ]
        agent, mock_client = _make_agent_mock(call_seq=call_seq)
        r1 = agent.reply("sess-1", "hello")
        r2 = agent.reply("sess-1", "what's on the menu")
        self.assertEqual(r1, "Hello!")
        self.assertEqual(r2, "How can I help?")
        history = agent.get_history("sess-1")
        self.assertEqual(len(history), 4)


if __name__ == "__main__":
    unittest.main()
