"""
Jimmy - a personal AI agent that learns from you and helps you.

Run it:      python jimmy.py
One-shot:    python jimmy.py --ask "what do you know about me?"
No API key?  It still runs - see `--offline`.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import config
from .brain import Brain
from .extractor import extract
from .learning_engine import LearningEngine
from .tools import Toolbox
from .voice import Voice

BANNER = """
╔══════════════════════════════════════════╗
║          🤖  J I M M Y  🤖               ║
║      Your learning AI companion          ║
╚══════════════════════════════════════════╝"""

HELP_TEXT = """
What I understand:

  teach <fact>          Teach me something and I'll keep it
  learn skill <name>    Give me a new skill (it improves as we use it)
  forget <thing>        Make me forget it - your memory, your rules
  forget everything     Wipe my memory completely
  stats                 My learning statistics
  progress              My growth, visualised
  memory                Everything I currently remember
  export [file]         Write my memory out as Markdown
  voice on | off        Let me speak my replies out loud
  voice <name>          Switch to a specific voice (e.g. he-IL-HilaNeural)
  voices [prefix]       List the voices available to me (needs network)
  tools                 What I can look at on this machine
  help                  This list
  exit                  End the session

Hebrew works too: למד / כישור / שכח / סטטיסטיקה / התקדמות / זיכרון / קול / כלים / עזרה / יציאה
Anything else is just conversation - and I learn from that as well.
"""

EXIT_WORDS = {"exit", "quit", "bye", "goodbye", "יציאה", "ביי", "להתראות"}


def default_memory_path() -> str:
    """Where Jimmy keeps his memory.

    One fixed location in your home folder, not the working directory - an
    installed `jimmy` is run from everywhere, and a memory that depends on your
    current folder is amnesia with extra steps.
    """
    home = os.environ.get("JIMMY_HOME") or str(Path.home() / ".jimmy")
    return os.path.join(home, "memory.json")


def adopt_local_memory(target: str) -> Optional[str]:
    """Carry an older ./memory.json over the first time, so nothing is lost."""
    local = os.path.abspath("memory.json")
    if os.path.exists(target) or not os.path.exists(local) or local == os.path.abspath(target):
        return None
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(local, target)
    except OSError:
        return None
    return local


def _plural(count: int, word: str) -> str:
    """'1 fact' / '3 facts' - small thing, but Jimmy should read like a person."""
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


class Jimmy:
    """The agent: a brain, a memory, and a personality tying them together."""

    def __init__(
        self,
        name: str = "Jimmy",
        memory_file: Optional[str] = None,
        offline: bool = False,
        speak: bool = False,
        voice_name: str = "auto",
        use_tools: bool = True,
        root: str = ".",
    ) -> None:
        self.name = name
        if memory_file is None:
            memory_file = default_memory_path()
            self.adopted_from = adopt_local_memory(memory_file)
        else:
            self.adopted_from = None
        self.engine = LearningEngine(memory_file)
        self.brain = Brain(force_offline=offline)
        self.voice = Voice(enabled=speak, voice=voice_name)
        self.toolbox = Toolbox(self.engine, root=root) if use_tools else None
        self.active = False
        self.history: List[Dict[str, str]] = []

    # ------------------------------------------------------------------
    # Presentation
    # ------------------------------------------------------------------

    def greet(self) -> str:
        stats = self.engine.get_learning_stats()
        who = f", {stats['user_name']}" if stats["user_name"] else ""
        lines = [
            BANNER,
            f"\nHi{who}! I'm {self.name}.",
            self.brain.status_line(),
            self.voice.status_line(),
            self.tools_status_line(),
        ]
        if stats["total_conversations"]:
            facts = _plural(stats["facts_learned"], "fact")
            skills = _plural(stats["skills_acquired"], "skill")
            lines.append(
                f"📚 We've talked {stats['total_conversations']} times. "
                f"I know {facts} and {skills}. Score: {stats['learning_score']}/100."
            )
        else:
            lines.append("This is our first conversation - teach me something! 🌱")
        if self.adopted_from:
            lines.append(f"📦 Brought your memory over from {self.adopted_from}")
        lines.append(f"💾 Memory: {self.engine.memory_file}")
        lines.append("\nType `help` to see what I understand.\n")
        greeting = "\n".join(lines)
        print(greeting)
        return greeting

    def tools_status_line(self) -> str:
        if self.toolbox is None:
            return "🔧 Tools: off"
        if not self.brain.online:
            return "🔧 Tools: ready, but they need the Claude brain (currently offline)"
        return f"🔧 Tools: on, scoped to {self.toolbox.root}"

    # ------------------------------------------------------------------
    # Conversation
    # ------------------------------------------------------------------

    def chat(
        self,
        user_input: str,
        on_text: Optional[Callable[[str], None]] = None,
        on_tool: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Handle one message. Commands are handled locally; the rest goes to the brain."""
        text = user_input.strip()
        if not text:
            return ""

        command_response = self._handle_command(text)
        if command_response is not None:
            return command_response

        learned = self._learn_passively(text)
        memory_context = self.engine.build_context(text)

        # Track whether the brain actually streamed, so the trailing note is only
        # appended to a live stream - otherwise the caller prints the reply itself.
        did_stream = False

        def tracked(chunk: str) -> None:
            nonlocal did_stream
            did_stream = True
            on_text(chunk)  # type: ignore[misc]

        response = self.brain.respond(
            text,
            memory_context=memory_context,
            history=self.history,
            on_text=tracked if on_text is not None else None,
            toolbox=self.toolbox,
            on_tool=on_tool,
        )

        self.engine.practice_relevant_skills(f"{text} {response}")
        self.engine.add_conversation(text, response)
        self.history.append({"role": "user", "content": text})
        self.history.append({"role": "assistant", "content": response})

        if learned:
            note = f"\n\n💾 (noted: {learned})"
            if did_stream:
                tracked(note)
            response += note

        self.voice.say(response)
        return response

    def _learn_passively(self, text: str) -> str:
        """Pick up anything the message revealed about the user."""
        found = extract(text)
        if found.is_empty():
            return ""

        if found.name:
            self.engine.set_user_name(found.name)
        for key, value in found.preferences.items():
            self.engine.remember_preference(key, value)
        for fact in found.facts:
            self.engine.learn_fact(fact, category="about_user")
        return found.describe()

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def _handle_command(self, text: str) -> Optional[str]:
        """Return a response for a recognised command, or None to keep chatting."""
        lowered = text.lower()

        if lowered in EXIT_WORDS:
            return self.goodbye()

        if lowered in {"help", "?", "עזרה"}:
            return HELP_TEXT

        if lowered in {"stats", "show my stats", "סטטיסטיקה"}:
            return self.show_stats()

        if lowered in {"progress", "show my progress", "התקדמות"}:
            return self.show_progress()

        if lowered in {"memory", "זיכרון"}:
            return self.engine.get_memory_summary()

        if lowered == "forget everything" or lowered in {"שכח הכל", "תשכח הכל"}:
            self.engine.forget_everything()
            self.history.clear()
            return "🧹 Done - my memory is completely empty. We start fresh."

        for prefix in ("learn skill ", "skill ", "כישור "):
            if lowered.startswith(prefix):
                return self.acquire_skill(text[len(prefix):])

        for prefix in ("teach ", "למד ", "תלמד "):
            if lowered.startswith(prefix):
                return self.learn_from_user(text[len(prefix):])

        for prefix in ("forget ", "שכח ", "תשכח "):
            if lowered.startswith(prefix):
                return self.forget(text[len(prefix):])

        if lowered in {"tools", "כלים"}:
            return self.show_tools()

        if lowered == "voices" or lowered.startswith("voices "):
            return self.list_voices(text[len("voices "):].strip() if len(text) > 6 else "")

        for prefix in ("voice", "קול"):
            if lowered == prefix or lowered.startswith(prefix + " "):
                return self.set_voice(text[len(prefix):].strip())

        if lowered == "export" or lowered.startswith("export "):
            target = text[len("export "):].strip() if len(text) > len("export") else ""
            return self.export(target or "jimmy_memory_export.md")

        return None

    def learn_from_user(self, fact: str) -> str:
        fact = fact.strip()
        if not fact:
            return "Teach me what? Try: `teach the deploy script lives in ops/deploy.sh`"

        entry = self.engine.learn_fact(fact)
        if entry["times_reinforced"] > 1:
            return f"✅ I already knew that - now I'm even more sure of it (x{entry['times_reinforced']}). 🧠"
        return f"✅ Learned: '{fact}' 📝"

    def acquire_skill(self, skill: str) -> str:
        skill = skill.strip()
        if not skill:
            return "Which skill? Try: `learn skill python`"

        skill_name = skill.split()[0]
        existing = self.engine._find_skill(skill_name) is not None
        entry = self.engine.learn_skill(skill_name, skill)
        percent = int(entry["proficiency"] * 100)
        if existing:
            return f"💪 Practised '{skill_name}' - proficiency is now {percent}%."
        return f"🎓 New skill: '{skill_name}' at {percent}%. It'll improve as we use it!"

    def forget(self, target: str) -> str:
        target = target.strip()
        if not target:
            return "Forget what? Try: `forget my old phone number`"

        removed = self.engine.forget(target)
        total = sum(len(values) for values in removed.values())
        if not total:
            return f"🤷 I don't have anything matching '{target}'."

        singular = {"facts": "fact", "skills": "skill", "preferences": "preference"}
        parts = [
            _plural(len(values), singular[kind])
            for kind, values in removed.items()
            if values
        ]
        return f"🧹 Forgotten: {', '.join(parts)}. Gone for good."

    def export(self, path: str) -> str:
        written = self.engine.export(path)
        return f"📄 Memory exported to {written}"

    def show_tools(self) -> str:
        """What Jimmy can reach, and where."""
        if self.toolbox is None:
            return "🔧 Tools are off (started with --no-tools)."
        names = "\n".join(f"  • {t['name']}" for t in self.toolbox.definitions())
        return f"""
🔧 My tools (read-only, scoped to {self.toolbox.root})
{names}

I use them on my own when a question needs them - just ask.
The only thing I can change is my own memory.
"""

    def set_voice(self, argument: str) -> str:
        """`voice` / `voice on` / `voice off` / `voice <name>`."""
        argument = argument.strip()

        if not self.voice.available:
            return f"🔇 I can't speak on this machine - {self.voice._why_unavailable()}"

        if not argument:
            return self.voice.status_line()

        lowered = argument.lower()
        if lowered in {"on", "start", "דבר", "הפעל"}:
            self.voice.enabled = True
            self.voice.say(f"Voice on. Hi, I'm {self.name}.")
            return f"🔊 Voice on ({self.voice.backend}, {self.voice.voice})."

        if lowered in {"off", "stop", "mute", "שקט", "כבה"}:
            self.voice.stop()
            self.voice.enabled = False
            return "🔇 Voice off."

        self.voice.voice = argument
        self.voice.enabled = True
        self.voice.say("This is how I sound now.")
        return f"🎙️  Switched to '{argument}' and turned voice on."

    def list_voices(self, prefix: str = "") -> str:
        """The live catalogue, so you never have to guess a voice name."""
        try:
            names = self.voice.list_voices(prefix)
        except Exception as exc:  # noqa: BLE001 - the catalogue needs network
            return f"⚠️  Couldn't fetch the voice list ({exc}). Voices need network access."

        if not names:
            return f"🤷 No voices matched '{prefix}'. Try `voices he` or `voices en-US`."
        shown = names[:40]
        more = f"\n...and {len(names) - len(shown)} more" if len(names) > len(shown) else ""
        return f"🎙️  {len(names)} voices available:\n  " + "\n  ".join(shown) + more

    def show_stats(self) -> str:
        stats = self.engine.get_learning_stats()
        skills = self.engine.knowledge_base["skills"]
        skill_line = (
            ", ".join(f"{s['name']} ({int(s['proficiency'] * 100)}%)" for s in skills)
            or "none yet"
        )
        rule = "=" * 50
        who = stats["user_name"] or "someone I don't know yet"
        return f"""
📊 {self.name}'s Learning Statistics
{rule}
✅ Conversations : {stats['total_conversations']}
📚 Facts learned : {stats['facts_learned']}
🎓 Skills        : {stats['skills_acquired']}
🧠 Learning score: {stats['learning_score']}/100
👤 You are       : {who}

Skills: {skill_line}
{rule}
"""

    def show_progress(self) -> str:
        score = self.engine.knowledge_base["learning_score"]
        filled = int(20 * score / 100)
        bar = "█" * filled + "░" * (20 - filled)

        if score < 25:
            level = "Beginner 🌱"
        elif score < 50:
            level = "Growing 🌿"
        elif score < 75:
            level = "Competent 🌳"
        else:
            level = "Expert 🌲"

        return f"""
🎯 {self.name}'s Progress
{bar} {score}%

Level: {level}
Keep teaching me and I'll keep growing! 📈
"""

    def goodbye(self) -> str:
        self.voice.stop()
        stats = self.engine.get_learning_stats()
        who = f", {stats['user_name']}" if stats["user_name"] else ""
        return f"""
👋 See you{who}!
We've talked {stats['total_conversations']} times and I'm at {stats['learning_score']}/100.
💾 Everything is saved in {self.engine.memory_file} - I'll remember it next time. 🧠
"""

    # ------------------------------------------------------------------
    # Interactive loop
    # ------------------------------------------------------------------

    def interactive_mode(self) -> None:
        self.greet()
        self.active = True

        while self.active:
            try:
                user_input = input("\n💬 You: ").strip()
            except (KeyboardInterrupt, EOFError):
                print(f"\n{self.goodbye()}")
                self.active = False
                break

            if not user_input:
                continue

            streamed = False

            def on_text(chunk: str) -> None:
                nonlocal streamed
                if not streamed:
                    print(f"\n🤖 {self.name}: ", end="", flush=True)
                    streamed = True
                print(chunk, end="", flush=True)

            def on_tool(description: str) -> None:
                nonlocal streamed
                if streamed:
                    print()
                    streamed = False
                print(f"   🔧 {description}", flush=True)

            try:
                response = self.chat(user_input, on_text=on_text, on_tool=on_tool)
            except Exception as exc:  # noqa: BLE001 - the loop must never die
                print(f"\n❌ Something went wrong: {exc}")
                continue

            if streamed:
                print()
            else:
                print(f"\n🤖 {self.name}: {response}")

            if user_input.lower() in EXIT_WORDS:
                self.active = False


def _store_key(key: str) -> int:
    """Save (or clear) the API key, and say what that changed."""
    if key and not key.startswith("sk-ant-"):
        print("⚠️  Anthropic keys start with 'sk-ant-'. Nothing was saved.")
        print("   Get one at https://console.anthropic.com/settings/keys")
        return 1

    path = config.set_api_key(key)
    if not key:
        print(f"🔑 Key removed from {path}. Jimmy will run offline.")
        return 0

    print(f"🔑 Key saved to {path} (readable only by you).")
    print("   Checking it with the API...")

    ok, detail = Brain().verify()
    if ok:
        print(f"✅ {detail.capitalize()}. Start him with `jimmy --app`.")
        return 0
    if ok is None:
        print(f"⚠️  {detail.capitalize()}.")
        return 0
    print(f"❌ {detail.capitalize()}.")
    print("   Check it at https://console.anthropic.com/settings/keys")
    return 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Jimmy - a learning AI agent")
    parser.add_argument(
        "--memory",
        default=None,
        help=f"path to the memory file (default: {default_memory_path()})",
    )
    parser.add_argument("--offline", action="store_true", help="never call the Claude API")
    parser.add_argument("--ask", metavar="MESSAGE", help="ask one thing and exit")
    parser.add_argument("--app", action="store_true", help="run as an app in your browser")
    parser.add_argument("--port", type=int, default=0, help="port for --app (default: any free one)")
    parser.add_argument("--no-browser", action="store_true", help="with --app, don't open a browser")
    parser.add_argument("--set-key", metavar="KEY", help="save an Anthropic API key and exit")
    parser.add_argument("--voice", action="store_true", help="speak replies out loud")
    parser.add_argument("--no-tools", action="store_true", help="don't let Jimmy look at files")
    parser.add_argument("--root", default=".", help="folder Jimmy may look inside (default: here)")
    parser.add_argument(
        "--voice-name",
        default="auto",
        metavar="NAME",
        help="voice to use (default: auto - Hebrew or English to match your message)",
    )
    args = parser.parse_args(argv)

    if args.set_key is not None:
        return _store_key(args.set_key)

    jimmy = Jimmy(
        memory_file=args.memory,
        offline=args.offline,
        speak=args.voice,
        voice_name=args.voice_name,
        use_tools=not args.no_tools,
        root=args.root,
    )

    if args.ask:
        print(jimmy.chat(args.ask))
        return 0

    if args.app:
        from .app import run as run_app

        return run_app(jimmy, port=args.port, open_browser=not args.no_browser)

    jimmy.interactive_mode()
    return 0


if __name__ == "__main__":
    sys.exit(main())
