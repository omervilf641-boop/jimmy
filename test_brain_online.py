"""
Tests for Jimmy's online path.

There is no API key here and no network, so a fake client stands in for the
Anthropic SDK. These tests verify the request Jimmy *would* send and every
failure branch around it - the parameter names themselves are checked against
the installed SDK signature in test_sdk_contract.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List, Optional

import anthropic
import httpx2 as httpx

from brain import MAX_TOKENS, PERSONA, Brain


class FakeBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class FakeMessage:
    def __init__(self, text: str, stop_reason: str = "end_turn") -> None:
        self.content = [FakeBlock(text)]
        self.stop_reason = stop_reason


class FakeStream:
    def __init__(self, message: FakeMessage) -> None:
        self._message = message
        self.text_stream = [message.content[0].text]

    def __enter__(self) -> "FakeStream":
        return self

    def __exit__(self, *args: Any) -> bool:
        return False

    def get_final_message(self) -> FakeMessage:
        return self._message


class FakeMessages:
    """Records every request and optionally raises a scripted exception."""

    def __init__(self, reply: str = "Hello!", raises: Optional[Exception] = None,
                 stop_reason: str = "end_turn") -> None:
        self.reply = reply
        self.raises = raises
        self.stop_reason = stop_reason
        self.calls: List[Dict[str, Any]] = []

    def stream(self, **kwargs: Any) -> FakeStream:
        self.calls.append(kwargs)
        if self.raises is not None:
            error, self.raises = self.raises, None  # raise once, then succeed
            raise error
        return FakeStream(FakeMessage(self.reply, self.stop_reason))


class FakeClient:
    def __init__(self, **kwargs: Any) -> None:
        self.messages = FakeMessages(**kwargs)


def _api_error(cls, status: int = 400, message: str = "boom"):
    """Build a real SDK exception without touching the network.

    anthropic 1.x is built on httpx2, not httpx - an object from the wrong
    package is rejected at request time.
    """
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status, request=request, json={"error": {"message": message}})
    return cls(message, response=response, body=None)


class TestOnlineRequestShape(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeClient()
        self.brain = Brain(client=self.client)

    def test_brain_reports_online(self) -> None:
        self.assertTrue(self.brain.online)
        self.assertIn("connected", self.brain.status_line())

    def test_request_carries_the_expected_parameters(self) -> None:
        self.brain.respond("hi")
        call = self.client.messages.calls[0]

        self.assertEqual(call["model"], "claude-opus-5")
        self.assertEqual(call["max_tokens"], MAX_TOKENS)
        self.assertEqual(call["system"], PERSONA)
        self.assertEqual(call["output_config"], {"effort": "low"})

    def test_memory_goes_in_a_mid_conversation_system_message(self) -> None:
        self.brain.respond("hi", memory_context="- Name: Omer")
        messages = self.client.messages.calls[0]["messages"]

        self.assertEqual(messages[-1]["role"], "system")
        self.assertIn("Omer", messages[-1]["content"])
        self.assertEqual(messages[-2], {"role": "user", "content": "hi"})

    def test_no_system_message_when_there_is_nothing_to_remember(self) -> None:
        self.brain.respond("hi")
        messages = self.client.messages.calls[0]["messages"]
        self.assertEqual([m["role"] for m in messages], ["user"])

    def test_history_is_replayed(self) -> None:
        history = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
        ]
        self.brain.respond("second", history=history)
        messages = self.client.messages.calls[0]["messages"]
        self.assertEqual(messages[0]["content"], "first")
        self.assertEqual(messages[-1]["content"], "second")

    def test_streaming_chunks_reach_the_callback(self) -> None:
        chunks: List[str] = []
        result = self.brain.respond("hi", on_text=chunks.append)
        self.assertEqual(chunks, ["Hello!"])
        self.assertEqual(result, "Hello!")


class TestOnlineFailureModes(unittest.TestCase):
    def test_model_without_mid_conversation_system_falls_back(self) -> None:
        """A 400 mentioning 'system' retries once with memory folded into the user turn."""
        error = _api_error(anthropic.BadRequestError, 400, "role 'system' is not supported on this model")
        client = FakeClient(raises=error)
        brain = Brain(client=client)

        result = brain.respond("hi", memory_context="- Name: Omer")

        self.assertEqual(result, "Hello!")
        self.assertEqual(len(client.messages.calls), 2, "should retry exactly once")
        retried = client.messages.calls[1]["messages"]
        self.assertTrue(all(m["role"] != "system" for m in retried))
        self.assertIn("Omer", retried[-1]["content"])
        self.assertFalse(brain._mid_conversation_system, "the downgrade should stick")

    def test_rejected_credentials_switch_to_offline(self) -> None:
        client = FakeClient(raises=_api_error(anthropic.AuthenticationError, 401, "invalid key"))
        brain = Brain(client=client)

        reply = brain.respond("hi")

        self.assertIn("offline", reply.lower())
        self.assertFalse(brain.online)
        self.assertTrue(brain.respond("hi").strip(), "offline mode still answers")

    def test_rate_limit_is_reported_without_going_offline(self) -> None:
        client = FakeClient(raises=_api_error(anthropic.RateLimitError, 429, "slow down"))
        brain = Brain(client=client)

        self.assertIn("rate limited", brain.respond("hi").lower())
        self.assertTrue(brain.online, "a rate limit is temporary - stay online")

    def test_server_error_is_reported(self) -> None:
        client = FakeClient(raises=_api_error(anthropic.APIStatusError, 503, "unavailable"))
        brain = Brain(client=client)
        self.assertIn("503", brain.respond("hi"))

    def test_unexpected_errors_are_not_swallowed(self) -> None:
        client = FakeClient(raises=RuntimeError("something else entirely"))
        with self.assertRaises(RuntimeError):
            Brain(client=client).respond("hi")

    def test_refusal_is_handled_gracefully(self) -> None:
        client = FakeClient(stop_reason="refusal")
        reply = Brain(client=client).respond("hi")
        self.assertIn("rather not", reply.lower())


class TestSdkContract(unittest.TestCase):
    """Guards against the SDK renaming something Jimmy depends on."""

    def test_stream_accepts_every_parameter_jimmy_sends(self) -> None:
        import inspect
        from anthropic.resources.messages import Messages

        params = set(inspect.signature(Messages.stream).parameters)
        for name in ("model", "max_tokens", "system", "messages", "output_config"):
            self.assertIn(name, params, f"SDK no longer accepts {name}")

    def test_every_exception_brain_branches_on_exists(self) -> None:
        for name in (
            "AuthenticationError", "PermissionDeniedError", "RateLimitError",
            "APIConnectionError", "APIStatusError", "BadRequestError",
        ):
            self.assertTrue(hasattr(anthropic, name), f"anthropic.{name} is gone")


if __name__ == "__main__":
    unittest.main(verbosity=2)
