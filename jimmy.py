"""
Jimmy - a personal AI agent that learns from you and helps you.

Run it:      python jimmy.py
One-shot:    python jimmy.py --ask "what do you know about me?"
No API key?  It still runs - see `--offline`.
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable, Dict, List, Optional

from brain import Brain
from extractor import extract
from learning_engine import LearningEngine

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
  help                  This list
  exit                  End the session

Hebrew works too: למד / כישור / שכח / סטטיסטיקה / התקדמות / זיכרון / עזרה / יציאה
Anything else is just conversation - and I learn from that as well.
"""

EXIT_WORDS = {"exit", "quit", "bye", "goodbye", "יציאה", "ביי", "להתראות"}


def _plural(count: int, word: str) -> str:
    """'1 fact' / '3 facts' - small thing, but Jimmy should read like a person."""
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


class Jimmy:
    """The agent: a brain, a memory, and a personality tying them together."""

    def __init__(
        self,
        name: str = "Jimmy",
        memory_file: str = "memory.json",
        offline: bool = False,
    ) -> None:
        self.name = name
        self.engine = LearningEngine(memory_file)
        self.brain = Brain(force_offline=offline)
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
        lines.append("\nType `help` to see what I understand.\n")
        greeting = "\n".join(lines)
        print(greeting)
        return greeting

    # ------------------------------------------------------------------
    # Conversation
    # ------------------------------------------------------------------

    def chat(self, user_input: str, on_text: Optional[Callable[[str], None]] = None) -> str:
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

            try:
                response = self.chat(user_input, on_text=on_text)
            except Exception as exc:  # noqa: BLE001 - the loop must never die
                print(f"\n❌ Something went wrong: {exc}")
                continue

            if streamed:
                print()
            else:
                print(f"\n🤖 {self.name}: {response}")

            if user_input.lower() in EXIT_WORDS:
                self.active = False


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Jimmy - a learning AI agent")
    parser.add_argument("--memory", default="memory.json", help="path to the memory file")
    parser.add_argument("--offline", action="store_true", help="never call the Claude API")
    parser.add_argument("--ask", metavar="MESSAGE", help="ask one thing and exit")
    args = parser.parse_args(argv)

    jimmy = Jimmy(memory_file=args.memory, offline=args.offline)

    if args.ask:
        print(jimmy.chat(args.ask))
        return 0

    jimmy.interactive_mode()
    return 0


if __name__ == "__main__":
    sys.exit(main())
