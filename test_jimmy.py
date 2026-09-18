"""
Tests for Jimmy. No API key and no network required - the brain is forced
offline so every test exercises real memory behaviour deterministically.

Run: python -m unittest test_jimmy -v
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest

from jimmy_agent.brain import Brain
from jimmy_agent.extractor import extract
from jimmy_agent import Jimmy
from jimmy_agent.learning_engine import SCHEMA_VERSION, LearningEngine


class MemoryTestCase(unittest.TestCase):
    """Base class giving each test its own throwaway memory file."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.memory_path = os.path.join(self.tmpdir.name, "memory.json")

    def engine(self) -> LearningEngine:
        return LearningEngine(self.memory_path)

    def jimmy(self) -> Jimmy:
        return Jimmy(memory_file=self.memory_path, offline=True)


class TestPersistence(MemoryTestCase):
    def test_facts_survive_restart(self) -> None:
        engine = self.engine()
        engine.learn_fact("the deploy script is ops/deploy.sh")

        reloaded = self.engine()
        facts = [entry["fact"] for entry in reloaded.knowledge_base["learned_facts"]]
        self.assertIn("the deploy script is ops/deploy.sh", facts)

    def test_skills_survive_restart(self) -> None:
        """The original bug: skills were stored but never reloaded into active_skills."""
        engine = self.engine()
        engine.learn_skill("python", "python programming")
        self.assertEqual(engine.get_learning_stats()["active_skills"], ["python"])

        reloaded = self.engine()
        self.assertEqual(reloaded.get_learning_stats()["active_skills"], ["python"])

    def test_user_profile_survives_restart(self) -> None:
        engine = self.engine()
        engine.set_user_name("Omer")
        engine.remember_preference("likes", "short answers")

        reloaded = self.engine()
        self.assertEqual(reloaded.user_name, "Omer")
        self.assertEqual(
            reloaded.knowledge_base["user_profile"]["preferences"]["likes"],
            "short answers",
        )

    def test_save_is_atomic_and_valid_json(self) -> None:
        engine = self.engine()
        engine.learn_fact("שלום עולם")  # non-ASCII must round-trip
        with open(self.memory_path, encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertEqual(data["version"], SCHEMA_VERSION)
        self.assertEqual(data["learned_facts"][0]["fact"], "שלום עולם")

    def test_corrupt_memory_file_does_not_crash(self) -> None:
        with open(self.memory_path, "w", encoding="utf-8") as handle:
            handle.write("{not valid json at all")

        engine = self.engine()  # must not raise
        self.assertEqual(engine.knowledge_base["total_interactions"], 0)
        backups = [n for n in os.listdir(self.tmpdir.name) if ".corrupt-" in n]
        self.assertEqual(len(backups), 1, "the damaged file should be kept, not deleted")

    def test_v1_memory_is_migrated(self) -> None:
        legacy = {
            "created_at": "2026-08-18T00:00:00",
            "conversations": [{"timestamp": "t", "user": "hi", "response": "hey", "interaction_id": 1}],
            "learned_facts": [{"fact": "python is a language", "category": "general", "learned_at": "t", "confidence": 1.0}],
            "skills": [{"name": "coding", "description": "coding", "learned_at": "t", "proficiency": 0.5}],
            "preferences": {"tone": "casual"},
            "learning_score": 13,
            "total_interactions": 1,
        }
        with open(self.memory_path, "w", encoding="utf-8") as handle:
            json.dump(legacy, handle)

        engine = self.engine()
        self.assertEqual(engine.knowledge_base["version"], SCHEMA_VERSION)
        self.assertEqual(engine.skills, ["coding"])
        self.assertEqual(engine.knowledge_base["user_profile"]["preferences"]["tone"], "casual")
        self.assertEqual(engine.knowledge_base["learned_facts"][0]["times_reinforced"], 1)
        self.assertEqual(engine.knowledge_base["skills"][0]["times_used"], 0)


class TestLearning(MemoryTestCase):
    def test_duplicate_fact_reinforces_instead_of_duplicating(self) -> None:
        engine = self.engine()
        engine.learn_fact("Jimmy lives on GitHub")
        engine.learn_fact("  jimmy LIVES on github  ")  # same fact, different shape

        self.assertEqual(len(engine.knowledge_base["learned_facts"]), 1)
        self.assertEqual(engine.knowledge_base["learned_facts"][0]["times_reinforced"], 2)

    def test_duplicate_skill_is_not_duplicated(self) -> None:
        engine = self.engine()
        engine.learn_skill("python")
        engine.learn_skill("Python")

        self.assertEqual(len(engine.knowledge_base["skills"]), 1)

    def test_empty_fact_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.engine().learn_fact("   ")

    def test_skill_proficiency_actually_improves(self) -> None:
        engine = self.engine()
        engine.learn_skill("python")
        start = engine.knowledge_base["skills"][0]["proficiency"]

        engine.improve_skill("python")
        self.assertGreater(engine.knowledge_base["skills"][0]["proficiency"], start)

    def test_proficiency_is_capped_at_one(self) -> None:
        engine = self.engine()
        engine.learn_skill("python")
        for _ in range(50):
            engine.improve_skill("python", improvement_rate=0.5)
        self.assertEqual(engine.knowledge_base["skills"][0]["proficiency"], 1.0)

    def test_improve_unknown_skill_returns_none(self) -> None:
        self.assertIsNone(self.engine().improve_skill("nonexistent"))

    def test_using_a_skill_in_conversation_improves_it(self) -> None:
        agent = self.jimmy()
        agent.chat("learn skill python")
        before = agent.engine.knowledge_base["skills"][0]["proficiency"]

        agent.chat("can you help me with some python code?")
        after = agent.engine.knowledge_base["skills"][0]["proficiency"]
        self.assertGreater(after, before)

    def test_learning_score_grows_and_is_bounded(self) -> None:
        engine = self.engine()
        self.assertEqual(engine.knowledge_base["learning_score"], 0)

        engine.learn_fact("fact one")
        self.assertGreater(engine.knowledge_base["learning_score"], 0)

        for index in range(40):
            engine.learn_fact(f"fact number {index}")
            engine.learn_skill(f"skill{index}")
            engine.add_conversation(f"message {index}", "reply")
        self.assertLessEqual(engine.knowledge_base["learning_score"], 100)


class TestRecall(MemoryTestCase):
    def test_recall_finds_the_relevant_conversation(self) -> None:
        engine = self.engine()
        engine.add_conversation("my favourite language is rust", "noted")
        engine.add_conversation("what's for lunch", "no idea")

        results = engine.recall_similar_conversations("tell me about rust")
        self.assertTrue(results)
        self.assertIn("rust", results[0]["conversation"]["user"])

    def test_recall_ignores_stopwords(self) -> None:
        engine = self.engine()
        engine.add_conversation("the a is of and", "noise")
        self.assertEqual(engine.recall_similar_conversations("the a is of and"), [])

    def test_context_includes_profile_facts_and_skills(self) -> None:
        engine = self.engine()
        engine.set_user_name("Omer")
        engine.remember_preference("likes", "short answers")
        engine.learn_fact("the deploy script is ops/deploy.sh")
        engine.learn_skill("python")

        context = engine.build_context("how do I deploy?")
        self.assertIn("Omer", context)
        self.assertIn("short answers", context)
        self.assertIn("ops/deploy.sh", context)
        self.assertIn("python", context)

    def test_context_is_empty_when_nothing_is_known(self) -> None:
        self.assertEqual(self.engine().build_context("anything"), "")


class TestForgetting(MemoryTestCase):
    def test_forget_removes_a_fact(self) -> None:
        engine = self.engine()
        engine.learn_fact("my phone number is 555-1234")
        engine.learn_fact("python is a language")

        removed = engine.forget("phone number")
        self.assertEqual(len(removed["facts"]), 1)
        self.assertEqual(len(engine.knowledge_base["learned_facts"]), 1)

    def test_forget_removes_a_skill_and_a_preference(self) -> None:
        engine = self.engine()
        engine.learn_skill("juggling")
        engine.remember_preference("likes", "juggling")

        removed = engine.forget("juggling")
        self.assertEqual(removed["skills"], ["juggling"])
        self.assertEqual(removed["preferences"], ["likes"])

    def test_forget_persists_across_restart(self) -> None:
        engine = self.engine()
        engine.learn_fact("secret thing")
        engine.forget("secret")
        self.assertEqual(self.engine().knowledge_base["learned_facts"], [])

    def test_forget_everything_resets(self) -> None:
        engine = self.engine()
        engine.learn_fact("something")
        engine.learn_skill("something-else")
        engine.forget_everything()

        reloaded = self.engine()
        self.assertEqual(reloaded.knowledge_base["learned_facts"], [])
        self.assertEqual(reloaded.knowledge_base["skills"], [])
        self.assertEqual(reloaded.knowledge_base["total_interactions"], 0)

    def test_forget_unknown_thing_reports_nothing(self) -> None:
        response = self.jimmy().chat("forget the thing I never said")
        self.assertIn("don't have anything", response)


class TestPassiveExtraction(unittest.TestCase):
    def test_extracts_english_name(self) -> None:
        self.assertEqual(extract("Hi, my name is Omer").name, "Omer")

    def test_extracts_hebrew_name(self) -> None:
        self.assertEqual(extract("היי, קוראים לי עומר").name, "עומר")

    def test_extracts_preferences(self) -> None:
        self.assertEqual(extract("I prefer short answers").preferences["prefers"], "short answers")
        self.assertEqual(extract("I love python").preferences["likes"], "python")
        self.assertEqual(extract("אני מעדיף תשובות קצרות").preferences["prefers"], "תשובות קצרות")

    def test_extracts_facts_about_the_user(self) -> None:
        self.assertIn("I work at Google", extract("I work at Google").facts)
        self.assertTrue(extract("אני גר בתל אביב").facts)

    def test_clean_stops_at_sentence_boundary(self) -> None:
        self.assertEqual(extract("I prefer tea. And also coffee.").preferences["prefers"], "tea")

    def test_ignores_ordinary_messages(self) -> None:
        self.assertTrue(extract("what's the weather like?").is_empty())
        self.assertTrue(extract("teach me something").is_empty())

    def test_rejects_non_name(self) -> None:
        self.assertIsNone(extract("my name is not important").name)


class TestOfflineBrain(unittest.TestCase):
    def test_offline_brain_reports_itself(self) -> None:
        brain = Brain(force_offline=True)
        self.assertFalse(brain.online)
        self.assertIn("offline", brain.status_line().lower())

    def test_offline_brain_still_answers(self) -> None:
        brain = Brain(force_offline=True)
        self.assertTrue(brain.respond("hello there").strip())

    def test_offline_brain_uses_memory_context(self) -> None:
        brain = Brain(force_offline=True)
        context = "WHAT I KNOW ABOUT THIS USER:\n- Name: Omer"
        self.assertIn("Omer", brain.respond("hi", memory_context=context))

    def test_offline_brain_refuses_to_guess_on_questions(self) -> None:
        reply = Brain(force_offline=True).respond("what is the capital of Peru?")
        self.assertIn("offline", reply.lower())


class TestJimmyEndToEnd(MemoryTestCase):
    def test_full_session_persists_everything(self) -> None:
        agent = self.jimmy()
        agent.chat("my name is Omer")
        agent.chat("teach the deploy script is ops/deploy.sh")
        agent.chat("learn skill python")

        revived = self.jimmy()
        stats = revived.engine.get_learning_stats()
        self.assertEqual(stats["user_name"], "Omer")
        self.assertEqual(stats["skills_acquired"], 1)
        self.assertEqual(stats["active_skills"], ["python"])
        self.assertGreaterEqual(stats["facts_learned"], 1)
        self.assertGreater(stats["total_conversations"], 0)

    def test_greeting_uses_a_remembered_name(self) -> None:
        agent = self.jimmy()
        agent.chat("my name is Omer")

        with contextlib.redirect_stdout(io.StringIO()):
            greeting = self.jimmy().greet()
        self.assertIn("Omer", greeting)

    def test_commands_do_not_pollute_conversation_memory(self) -> None:
        agent = self.jimmy()
        agent.chat("stats")
        agent.chat("help")
        self.assertEqual(agent.engine.knowledge_base["total_interactions"], 0)

    def test_teach_then_stats_reflects_it(self) -> None:
        agent = self.jimmy()
        agent.chat("teach jimmy is an agent")
        self.assertIn("Facts learned : 1", agent.chat("stats"))

    def test_teaching_twice_is_acknowledged_as_reinforcement(self) -> None:
        agent = self.jimmy()
        agent.chat("teach the sky is blue")
        self.assertIn("already knew", agent.chat("teach the sky is blue"))

    def test_hebrew_commands_work(self) -> None:
        agent = self.jimmy()
        agent.chat("למד השמיים כחולים")
        self.assertEqual(len(agent.engine.knowledge_base["learned_facts"]), 1)
        self.assertIn("🧠", agent.chat("זיכרון"))

    def test_empty_input_is_ignored(self) -> None:
        self.assertEqual(self.jimmy().chat("   "), "")

    def test_export_writes_a_readable_file(self) -> None:
        agent = self.jimmy()
        agent.chat("teach exporting works")
        target = os.path.join(self.tmpdir.name, "export.md")

        response = agent.chat(f"export {target}")
        self.assertIn("exported", response.lower())
        self.assertTrue(os.path.exists(target))
        with open(target, encoding="utf-8") as handle:
            self.assertIn("exporting works", handle.read())

    def test_progress_bar_renders(self) -> None:
        agent = self.jimmy()
        for index in range(3):
            agent.chat(f"teach fact number {index}")

        progress = agent.chat("progress")
        self.assertIn("█", progress)
        self.assertIn("Level:", progress)

    def test_goodbye_mentions_the_memory_file(self) -> None:
        self.assertIn("memory.json", self.jimmy().chat("exit"))

    def test_offline_reply_is_not_swallowed_by_the_learning_note(self) -> None:
        """Regression: the 'noted' note used to fire the stream callback even when
        the brain never streamed, so the interactive loop printed the note and
        dropped the actual reply."""
        agent = self.jimmy()
        chunks: list = []

        response = agent.chat("my name is Omer", on_text=chunks.append)

        self.assertEqual(chunks, [], "offline mode does not stream - nothing should be emitted")
        self.assertIn("Omer", response, "the reply itself must survive")
        self.assertIn("noted", response.lower())

    def test_streaming_callback_receives_the_note_when_it_does_stream(self) -> None:
        """The mirror case: a streaming brain gets the note through the callback."""

        class FakeStreamingBrain:
            online = True

            def respond(self, user_input, memory_context="", history=None,
                        on_text=None, toolbox=None, on_tool=None):
                for chunk in ("Hi ", "there!"):
                    on_text(chunk)
                return "Hi there!"

        agent = self.jimmy()
        agent.brain = FakeStreamingBrain()
        chunks: list = []

        agent.chat("my name is Omer", on_text=chunks.append)
        self.assertIn("Hi ", chunks)
        self.assertTrue(any("noted" in chunk for chunk in chunks))

    def test_history_is_tracked_for_context(self) -> None:
        agent = self.jimmy()
        agent.chat("hello there")
        self.assertEqual(len(agent.history), 2)
        self.assertEqual(agent.history[0]["role"], "user")
        self.assertEqual(agent.history[1]["role"], "assistant")


class TestDefaultMemoryLocation(unittest.TestCase):
    """An installed `jimmy` is run from anywhere - his memory must not follow the cwd."""

    def test_default_is_in_the_home_folder_not_the_cwd(self) -> None:
        from jimmy_agent.agent import default_memory_path

        path = default_memory_path()
        self.assertTrue(os.path.isabs(path), "the default memory path must be absolute")
        self.assertNotEqual(os.path.dirname(path), os.getcwd())

    def test_jimmy_home_overrides_it(self) -> None:
        from jimmy_agent.agent import default_memory_path

        original = os.environ.get("JIMMY_HOME")
        os.environ["JIMMY_HOME"] = "/tmp/jimmy-probe"
        try:
            self.assertEqual(default_memory_path(), "/tmp/jimmy-probe/memory.json")
        finally:
            if original is None:
                del os.environ["JIMMY_HOME"]
            else:
                os.environ["JIMMY_HOME"] = original

    def test_memory_is_shared_between_working_directories(self) -> None:
        import subprocess
        import sys

        repo = os.path.dirname(os.path.abspath(__file__))
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as elsewhere:
            environment = {**os.environ, "JIMMY_HOME": home, "PYTHONPATH": repo}

            subprocess.run(
                [sys.executable, "-c",
                 "from jimmy_agent import Jimmy; Jimmy(offline=True).chat('my name is Omer')"],
                cwd=repo, env=environment, check=True, capture_output=True,
            )
            result = subprocess.run(
                [sys.executable, "-c",
                 "from jimmy_agent import Jimmy; print(Jimmy(offline=True).engine.user_name)"],
                cwd=elsewhere, env=environment, check=True, capture_output=True, text=True,
            )
            self.assertEqual(result.stdout.strip(), "Omer", "he must remember you from any folder")

    def test_an_existing_local_memory_is_adopted_once(self) -> None:
        import json as json_module

        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as workdir:
            legacy = os.path.join(workdir, "memory.json")
            with open(legacy, "w", encoding="utf-8") as handle:
                json_module.dump({"learned_facts": [{"fact": "an older memory"}]}, handle)

            original_cwd, original_home = os.getcwd(), os.environ.get("JIMMY_HOME")
            os.environ["JIMMY_HOME"] = home
            os.chdir(workdir)
            try:
                agent = Jimmy(offline=True)
                facts = [e["fact"] for e in agent.engine.knowledge_base["learned_facts"]]
                self.assertIn("an older memory", facts)
                self.assertEqual(agent.adopted_from, legacy)
                self.assertTrue(os.path.exists(legacy), "the original must not be moved")
            finally:
                os.chdir(original_cwd)
                if original_home is None:
                    del os.environ["JIMMY_HOME"]
                else:
                    os.environ["JIMMY_HOME"] = original_home


class TestFootprint(unittest.TestCase):
    """Jimmy has to start fast on an ordinary laptop.

    The anthropic SDK costs ~700ms and ~55MB to import, edge-tts another ~220ms
    and ~29MB. Neither may be imported until it is actually needed, or startup
    regresses by an order of magnitude.
    """

    def _probe(self, script: str) -> str:
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_offline_startup_imports_neither_heavy_dependency(self) -> None:
        output = self._probe(
            "import sys, tempfile, os\n"
            "from jimmy_agent import Jimmy\n"
            "Jimmy(memory_file=os.path.join(tempfile.mkdtemp(), 'm.json'), offline=True)\n"
            "print('anthropic' in sys.modules, 'edge_tts' in sys.modules)"
        )
        self.assertEqual(output, "False False", "heavy dependencies must stay unimported")

    def test_sdk_is_imported_once_credentials_exist(self) -> None:
        output = self._probe(
            "import sys, os\n"
            "os.environ['ANTHROPIC_API_KEY'] = 'sk-ant-probe'\n"
            "from jimmy_agent.brain import Brain\n"
            "brain = Brain()\n"
            "print('anthropic' in sys.modules, brain.online)"
        )
        self.assertEqual(output, "True True", "the SDK must load when it is actually needed")

    def test_startup_is_fast(self) -> None:
        output = self._probe(
            "import time, tempfile, os\n"
            "start = time.perf_counter()\n"
            "from jimmy_agent import Jimmy\n"
            "Jimmy(memory_file=os.path.join(tempfile.mkdtemp(), 'm.json'), offline=True)\n"
            "print(int((time.perf_counter() - start) * 1000))"
        )
        self.assertLess(int(output), 400, f"offline startup took {output}ms - something heavy crept in")


if __name__ == "__main__":
    unittest.main(verbosity=2)
