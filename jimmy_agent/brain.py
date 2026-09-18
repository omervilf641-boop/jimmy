"""
Jimmy's brain - talks to Claude when credentials are available, and falls back
to a self-contained rule-based mode when they are not.

The fallback is not a degraded stub: every other part of Jimmy (memory, facts,
skills, preferences) works identically in both modes. Only the quality of the
prose changes.
"""

from __future__ import annotations

import os
import re
from typing import Callable, Dict, List, Optional

from . import config

import importlib.util

# The SDK costs ~700ms and ~55MB to import, so it is loaded on first real use.
# Offline sessions never pay for it.
_sdk_module = None
_sdk_loaded = False


def _sdk():
    """Import the Anthropic SDK on demand. Returns None if it isn't installed."""
    global _sdk_module, _sdk_loaded
    if not _sdk_loaded:
        _sdk_loaded = True
        try:
            import anthropic as module

            _sdk_module = module
        except ImportError:  # pragma: no cover - only on bare installs
            _sdk_module = None
    return _sdk_module


def _sdk_installed() -> bool:
    """Is the SDK available? Checked without importing it."""
    if _sdk_loaded:
        return _sdk_module is not None
    return importlib.util.find_spec("anthropic") is not None

DEFAULT_MODEL = "claude-opus-5"
MAX_TOKENS = 4096
HISTORY_TURNS = 12  # how many past turns are replayed to the model
MAX_TOOL_ROUNDS = 4  # a hard ceiling, so one question can never run away

PERSONA = """You are Jimmy, a personal AI agent who learns from one specific user and helps them.

Who you are:
- Warm, direct and genuinely curious. You have a personality - you are not a generic assistant.
- You keep it short. Two or three sentences unless the user clearly wants depth.
- You use the occasional emoji, but you never decorate every line with them.
- You reply in whatever language the user writes in (Hebrew, English, anything else).

How your memory works:
- Before each reply you receive a MEMORY block with what you know about this user.
- Use it naturally. If you know their name, use it. If you know their preferences, honour them.
- Never invent memories. If the MEMORY block does not contain something, you do not know it.
- If the user tells you something worth keeping, acknowledge it briefly - it is being saved.

Your tools:
- You can list, read and search files in the folder you were started in, and you can
  save things into your own memory. Use them rather than asking the user to paste things.
- Look before you answer: list or search first, then read what matters. Do not read a
  whole large file when a search would do.
- Keep it to a few calls. If you have enough to answer, answer.
- When you learn something durable about the user or their project, save it with `remember`.

What you actually do: you help. Answer the question, solve the problem, give the concrete
next step. Do not describe what you could do instead of doing it."""


class Brain:
    """Generates Jimmy's replies, online or offline."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        force_offline: bool = False,
        client: Optional[object] = None,
    ) -> None:
        self.model = os.environ.get("JIMMY_MODEL", model)
        self.client = client
        self.offline_reason: Optional[str] = None
        self._mid_conversation_system = True  # downgraded automatically if rejected

        if client is not None:
            return
        if force_offline:
            self.offline_reason = "offline mode requested"
        elif not self._has_credentials():
            # Checked first: it is the common case, and it costs no import.
            self.offline_reason = "no API key yet - run `jimmy --set-key` or open the app"
        elif not _sdk_installed():
            self.offline_reason = "the 'anthropic' package is not installed (pip install anthropic)"
        else:
            try:
                # Pass the key explicitly so a key stored in Jimmy's own config
                # works without being exported into the environment.
                stored = config.stored_api_key()
                anthropic = _sdk()
                self.client = (
                    anthropic.Anthropic(api_key=stored) if stored and not os.environ.get("ANTHROPIC_API_KEY")
                    else anthropic.Anthropic()
                )
            except Exception as exc:  # noqa: BLE001 - any construction failure means offline
                self.offline_reason = f"could not start the Claude client ({exc})"

    @staticmethod
    def _has_credentials() -> bool:
        """Environment, then Jimmy's own config, then an `ant auth login` profile."""
        if config.api_key():
            return True
        profile_dir = os.path.expanduser("~/.config/anthropic")
        return os.path.isdir(profile_dir) and bool(os.listdir(profile_dir))

    @property
    def online(self) -> bool:
        return self.client is not None

    def status_line(self) -> str:
        if self.online:
            return f"🧠 Brain: Claude ({self.model}) - connected"
        return f"💤 Brain: offline mode - {self.offline_reason}"

    def verify(self) -> tuple:
        """Check the credentials actually work. Returns (ok, message).

        Uses count_tokens: it authenticates against the real API without
        generating anything, so confirming a key costs nothing.
        """
        if not self.online:
            return False, self.offline_reason or "not connected"

        try:
            self.client.messages.count_tokens(  # type: ignore[union-attr]
                model=self.model, messages=[{"role": "user", "content": "hi"}]
            )
            return True, f"connected to {self.model}"
        except Exception as exc:  # noqa: BLE001 - narrowed below
            anthropic = _sdk()
            if anthropic is not None:
                if isinstance(exc, anthropic.AuthenticationError):
                    return False, "the API rejected that key"
                if isinstance(exc, anthropic.PermissionDeniedError):
                    return False, "that key exists but isn't allowed to use this model"
                if isinstance(exc, anthropic.APIConnectionError):
                    return None, "couldn't reach the API to check - the key was saved anyway"
            return None, f"couldn't check the key ({type(exc).__name__}) - it was saved anyway"

    # ------------------------------------------------------------------
    # Response generation
    # ------------------------------------------------------------------

    def respond(
        self,
        user_input: str,
        memory_context: str = "",
        history: Optional[List[Dict[str, str]]] = None,
        on_text: Optional[Callable[[str], None]] = None,
        toolbox: Optional[object] = None,
        on_tool: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Produce Jimmy's reply. `on_text` receives streamed chunks when online."""
        if not self.online:
            return self._offline_respond(user_input, memory_context)

        try:
            return self._claude_respond(
                user_input, memory_context, history or [], on_text, toolbox, on_tool
            )
        except Exception as exc:  # noqa: BLE001 - narrowed inside the handler
            fallback = self._handle_api_error(exc)
            if fallback is not None:
                return fallback
            raise

    def _handle_api_error(self, exc: Exception) -> Optional[str]:
        """Turn an API failure into a graceful reply, dropping offline if needed."""
        anthropic = _sdk()
        if anthropic is None:
            return None

        if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
            self.client = None
            self.offline_reason = "the API credentials were rejected"
            return "⚠️  My Claude credentials were rejected, so I've switched to offline mode. Everything I remember is still intact."
        if isinstance(exc, anthropic.RateLimitError):
            return "⏳ I'm being rate limited right now - give me a moment and ask again."
        if isinstance(exc, anthropic.APIConnectionError):
            return "🌐 I couldn't reach the Claude API. Check the connection and try again - nothing was lost."
        if isinstance(exc, anthropic.APIStatusError):
            return f"⚠️  The API returned an error ({exc.status_code}). Try again in a moment."
        return None

    def _build_messages(
        self, user_input: str, memory_context: str, history: List[Dict[str, str]]
    ) -> List[Dict[str, object]]:
        messages: List[Dict[str, object]] = list(history[-HISTORY_TURNS * 2:])
        messages.append({"role": "user", "content": user_input})

        if memory_context:
            block = f"MEMORY - what you know about this user:\n\n{memory_context}"
            if self._mid_conversation_system:
                # Keeps the cached prefix intact; supported on Opus 5.
                messages.append({"role": "system", "content": block})
            else:
                messages[-1] = {
                    "role": "user",
                    "content": f"{block}\n\n---\n\n{user_input}",
                }
        return messages

    def _claude_respond(
        self,
        user_input: str,
        memory_context: str,
        history: List[Dict[str, str]],
        on_text: Optional[Callable[[str], None]],
        toolbox: Optional[object] = None,
        on_tool: Optional[Callable[[str], None]] = None,
    ) -> str:
        try:
            return self._stream(user_input, memory_context, history, on_text, toolbox, on_tool)
        except Exception as exc:  # noqa: BLE001
            # Older models reject mid-conversation system messages - retry once
            # with the memory folded into the user turn instead.
            anthropic = _sdk()
            rejects_system = (
                anthropic is not None
                and isinstance(exc, anthropic.BadRequestError)
                and self._mid_conversation_system
                and "system" in str(exc).lower()
            )
            if not rejects_system:
                raise
            self._mid_conversation_system = False
            return self._stream(user_input, memory_context, history, on_text, toolbox, on_tool)

    @staticmethod
    def _finalize(replies: List[str]) -> str:
        """Never hand back an empty reply - silence looks like a crash."""
        answer = "\n\n".join(replies).strip()
        return answer or "I came up empty on that one. Try asking it a different way?"

    def _one_turn(self, messages: List[Dict[str, object]], tools, on_text):
        """One request/response round, streamed."""
        request: Dict[str, object] = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "system": PERSONA,
            "output_config": {"effort": "low"},  # chat replies don't need deep reasoning
            "messages": messages,
        }
        if tools:
            request["tools"] = tools

        with self.client.messages.stream(**request) as stream:  # type: ignore[union-attr]
            if on_text is not None:
                for chunk in stream.text_stream:
                    on_text(chunk)
            return stream.get_final_message()

    def _stream(
        self,
        user_input: str,
        memory_context: str,
        history: List[Dict[str, str]],
        on_text: Optional[Callable[[str], None]],
        toolbox: Optional[object] = None,
        on_tool: Optional[Callable[[str], None]] = None,
    ) -> str:
        messages = self._build_messages(user_input, memory_context, history)
        tools = toolbox.definitions() if toolbox is not None else None
        replies: List[str] = []

        for _ in range(MAX_TOOL_ROUNDS if toolbox is not None else 1):
            message = self._one_turn(messages, tools, on_text)

            if message.stop_reason == "refusal":
                return "I'd rather not answer that one. Ask me something else and I'm all yours."

            text = "".join(b.text for b in message.content if b.type == "text").strip()
            if text:
                replies.append(text)

            calls = [b for b in message.content if b.type == "tool_use"]
            if not calls:
                return self._finalize(replies)

            messages.append({"role": "assistant", "content": message.content})
            results = []
            for call in calls:
                if on_tool is not None:
                    on_tool(toolbox.describe_call(call.name, call.input))  # type: ignore[union-attr]
                output, failed = toolbox.run(call.name, call.input)  # type: ignore[union-attr]
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": output,
                        "is_error": failed,
                    }
                )
            messages.append({"role": "user", "content": results})

        # Out of rounds: ask for a plain answer with what it already has.
        messages.append(
            {"role": "user", "content": "That is enough looking. Answer now with what you have."}
        )
        final = self._one_turn(messages, None, on_text)
        text = "".join(b.text for b in final.content if b.type == "text").strip()
        if text:
            replies.append(text)
        return self._finalize(replies)

    # ------------------------------------------------------------------
    # Offline mode
    # ------------------------------------------------------------------

    def _offline_respond(self, user_input: str, memory_context: str) -> str:
        """Rule-based replies that still use everything Jimmy remembers."""
        lowered = user_input.lower()
        name = self._name_from_context(memory_context)
        who = f" {name}" if name else ""

        if re.search(r"\b(hi|hello|hey|yo)\b|שלום|היי|אהלן", lowered):
            return f"Hey there{who}! 👋 I'm running offline right now, but I still remember everything. What's up?"

        if re.search(r"how are you|מה נשמע|מה קורה|מה שלומך", lowered):
            return "Doing well! 🌟 Offline mode, but my memory is fully intact. How are you?"

        if re.search(r"\b(thanks|thank you|thx)\b|תודה", lowered):
            return f"Anytime{who}! 😊"

        if re.search(r"what can you do|abilities|יכולות|מה אתה יודע", lowered):
            return (
                "Right now I'm offline, so I can't reason freely - but I can still "
                "learn facts (`teach ...`), pick up skills (`learn skill ...`), and "
                "remember everything you tell me. Type `help` for the full list. "
                "Set ANTHROPIC_API_KEY and restart me for the full brain. 🧠"
            )

        if re.search(r"\b(sorry|my mistake|wrong)\b|טעיתי|סליחה", lowered):
            return "No worries at all - corrections are how I get better. 🌱"

        if "?" in user_input or re.search(r"^(what|why|how|when|where|who)\b", lowered):
            hint = self._first_relevant_line(memory_context)
            if hint:
                return (
                    f"I'm offline so I can't reason this one through properly, but here's "
                    f"what I remember that might help: {hint}"
                )
            return (
                "That's a real question and I'm offline, so I won't guess. "
                "Set ANTHROPIC_API_KEY and restart me and I'll answer it properly. 🔌"
            )

        return f"Noted{who} - I've stored that. 📝 (Offline mode: I'm remembering, not reasoning.)"

    @staticmethod
    def _name_from_context(memory_context: str) -> str:
        match = re.search(r"^- Name: (.+)$", memory_context, re.MULTILINE)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _first_relevant_line(memory_context: str) -> str:
        for line in memory_context.splitlines():
            line = line.strip()
            if line.startswith("- ") and not line.startswith("- Name:"):
                return line[2:]
        return ""
