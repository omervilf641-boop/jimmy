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

try:  # The package is optional - Jimmy must run without it.
    import anthropic
except ImportError:  # pragma: no cover - exercised only on bare installs
    anthropic = None  # type: ignore[assignment]

DEFAULT_MODEL = "claude-opus-5"
MAX_TOKENS = 4096
HISTORY_TURNS = 12  # how many past turns are replayed to the model

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
        elif anthropic is None:
            self.offline_reason = "the 'anthropic' package is not installed (pip install anthropic)"
        elif not self._has_credentials():
            self.offline_reason = "no ANTHROPIC_API_KEY found in the environment"
        else:
            try:
                self.client = anthropic.Anthropic()
            except Exception as exc:  # noqa: BLE001 - any construction failure means offline
                self.offline_reason = f"could not start the Claude client ({exc})"

    @staticmethod
    def _has_credentials() -> bool:
        """The SDK also reads `ant auth login` profiles, so check those too."""
        if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
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

    # ------------------------------------------------------------------
    # Response generation
    # ------------------------------------------------------------------

    def respond(
        self,
        user_input: str,
        memory_context: str = "",
        history: Optional[List[Dict[str, str]]] = None,
        on_text: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Produce Jimmy's reply. `on_text` receives streamed chunks when online."""
        if not self.online:
            return self._offline_respond(user_input, memory_context)

        try:
            return self._claude_respond(user_input, memory_context, history or [], on_text)
        except Exception as exc:  # noqa: BLE001 - narrowed inside the handler
            fallback = self._handle_api_error(exc)
            if fallback is not None:
                return fallback
            raise

    def _handle_api_error(self, exc: Exception) -> Optional[str]:
        """Turn an API failure into a graceful reply, dropping offline if needed."""
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
    ) -> str:
        try:
            return self._stream(user_input, memory_context, history, on_text)
        except Exception as exc:  # noqa: BLE001
            # Older models reject mid-conversation system messages - retry once
            # with the memory folded into the user turn instead.
            rejects_system = (
                anthropic is not None
                and isinstance(exc, anthropic.BadRequestError)
                and self._mid_conversation_system
                and "system" in str(exc).lower()
            )
            if not rejects_system:
                raise
            self._mid_conversation_system = False
            return self._stream(user_input, memory_context, history, on_text)

    def _stream(
        self,
        user_input: str,
        memory_context: str,
        history: List[Dict[str, str]],
        on_text: Optional[Callable[[str], None]],
    ) -> str:
        messages = self._build_messages(user_input, memory_context, history)
        with self.client.messages.stream(  # type: ignore[union-attr]
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=PERSONA,
            output_config={"effort": "low"},  # chat replies don't need deep reasoning
            messages=messages,
        ) as stream:
            if on_text is not None:
                for chunk in stream.text_stream:
                    on_text(chunk)
            message = stream.get_final_message()

        if message.stop_reason == "refusal":
            return "I'd rather not answer that one. Ask me something else and I'm all yours."

        return "".join(
            block.text for block in message.content if block.type == "text"
        ).strip()

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
