"""
Tests for Jimmy's toolbox and the tool loop.

Every budget and every sandbox rule is asserted here, because those are what
keep Jimmy cheap enough to run on a normal laptop.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from typing import Any, Dict, List

from jimmy_agent.brain import MAX_TOOL_ROUNDS, Brain
from jimmy_agent.learning_engine import LearningEngine
from jimmy_agent.tools import (
    MAX_LIST_ENTRIES,
    MAX_RESULT_CHARS,
    MAX_SEARCH_HITS,
    Toolbox,
)


class ToolboxTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.root = self.tmpdir.name

        self.write("hello.py", "def greet():\n    return 'hi'\n\n# TODO: translate\n")
        self.write("notes.txt", "remember the milk\n")
        os.makedirs(os.path.join(self.root, "sub"))
        self.write("sub/deep.py", "SECRET_MARKER = 1\n")
        os.makedirs(os.path.join(self.root, "__pycache__"))
        self.write("__pycache__/junk.pyc", "ignored")

        self.engine = LearningEngine(os.path.join(self.root, "memory.json"))
        self.box = Toolbox(self.engine, root=self.root)

    def write(self, name: str, content: str) -> str:
        path = os.path.join(self.root, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return path

    def run_tool(self, name: str, **arguments: Any) -> str:
        output, failed = self.box.run(name, arguments)
        self.assertFalse(failed, f"{name} failed: {output}")
        return output

    def expect_error(self, name: str, **arguments: Any) -> str:
        output, failed = self.box.run(name, arguments)
        self.assertTrue(failed, f"{name} should have failed but returned: {output}")
        return output


class TestDefinitions(ToolboxTestCase):
    def test_every_tool_has_a_valid_schema(self) -> None:
        for definition in self.box.definitions():
            self.assertIn("name", definition)
            self.assertTrue(definition["description"].strip())
            schema = definition["input_schema"]
            self.assertEqual(schema["type"], "object")
            for field in schema.get("required", []):
                self.assertIn(field, schema["properties"], f"{definition['name']}: {field}")

    def test_every_defined_tool_is_dispatchable(self) -> None:
        for definition in self.box.definitions():
            output, failed = self.box.run(definition["name"], {})
            self.assertNotIn("there is no tool called", output)

    def test_unknown_tool_is_an_error_not_a_crash(self) -> None:
        output, failed = self.box.run("rm_rf", {"path": "/"})
        self.assertTrue(failed)
        self.assertIn("no tool called", output)


class TestSandbox(ToolboxTestCase):
    def test_cannot_escape_with_dot_dot(self) -> None:
        self.assertIn("outside", self.expect_error("read_file", path="../../../etc/passwd"))

    def test_cannot_escape_with_an_absolute_path(self) -> None:
        self.assertIn("outside", self.expect_error("read_file", path="/etc/passwd"))

    def test_cannot_list_outside_the_root(self) -> None:
        self.assertIn("outside", self.expect_error("list_files", path="/etc"))

    def test_paths_inside_the_root_are_fine(self) -> None:
        self.assertIn("greet", self.run_tool("read_file", path="hello.py"))


class TestReadFile(ToolboxTestCase):
    def test_reads_with_line_numbers(self) -> None:
        output = self.run_tool("read_file", path="hello.py")
        self.assertIn("def greet():", output)
        self.assertIn("1  ", output)

    def test_paging_with_start_line(self) -> None:
        self.write("long.txt", "\n".join(f"line {n}" for n in range(1, 101)) + "\n")
        output = self.run_tool("read_file", path="long.txt", start_line=50, max_lines=3)
        self.assertIn("line 50", output)
        self.assertNotIn("line 54", output)
        self.assertIn("start_line=53", output, "should say how to get the next page")

    def test_missing_file_is_an_error(self) -> None:
        self.assertIn("does not exist", self.expect_error("read_file", path="nope.txt"))

    def test_directory_is_an_error_that_suggests_list_files(self) -> None:
        self.assertIn("list_files", self.expect_error("read_file", path="sub"))

    def test_binary_file_is_refused(self) -> None:
        with open(os.path.join(self.root, "blob.bin"), "wb") as handle:
            handle.write(b"\x00\x01\x02binary")
        self.assertIn("binary", self.expect_error("read_file", path="blob.bin"))

    def test_start_line_past_the_end_is_an_error(self) -> None:
        self.assertIn("past the end", self.expect_error("read_file", path="hello.py", start_line=999))

    def test_output_is_capped(self) -> None:
        self.write("huge.txt", "x" * 200 + "\n" * 5000)
        output = self.run_tool("read_file", path="huge.txt")
        self.assertLessEqual(len(output), MAX_RESULT_CHARS + 120)


class TestListFiles(ToolboxTestCase):
    def test_lists_files_and_folders(self) -> None:
        output = self.run_tool("list_files")
        self.assertIn("hello.py", output)
        self.assertIn("sub/", output)

    def test_skips_noise_directories(self) -> None:
        self.assertNotIn("__pycache__", self.run_tool("list_files"))

    def test_glob_filter(self) -> None:
        output = self.run_tool("list_files", pattern="*.py")
        self.assertIn("hello.py", output)
        self.assertNotIn("notes.txt", output)

    def test_entry_count_is_capped(self) -> None:
        for index in range(MAX_LIST_ENTRIES + 25):
            self.write(f"file{index:03d}.tmp", "x")
        output = self.run_tool("list_files")
        self.assertIn("and ", output)
        self.assertLessEqual(output.count("\n"), MAX_LIST_ENTRIES + 4)

    def test_missing_folder_is_an_error(self) -> None:
        self.assertIn("does not exist", self.expect_error("list_files", path="nowhere"))


class TestSearchFiles(ToolboxTestCase):
    def test_finds_a_match_with_file_and_line(self) -> None:
        output = self.run_tool("search_files", query="SECRET_MARKER")
        self.assertIn("deep.py:1", output)

    def test_reports_no_matches_without_failing(self) -> None:
        self.assertIn("No matches", self.run_tool("search_files", query="zzz-not-here"))

    def test_filename_filter(self) -> None:
        self.assertIn("No matches", self.run_tool("search_files", query="milk", pattern="*.py"))

    def test_hits_are_capped(self) -> None:
        self.write("many.txt", "needle\n" * (MAX_SEARCH_HITS * 3))
        output = self.run_tool("search_files", query="needle")
        self.assertIn("result limit", output)

    def test_invalid_regex_is_an_error_not_a_crash(self) -> None:
        self.assertIn("Error", self.expect_error("search_files", query="[unclosed"))

    def test_empty_query_is_an_error(self) -> None:
        self.expect_error("search_files", query="  ")


class TestMemoryTools(ToolboxTestCase):
    def test_remember_writes_to_real_memory(self) -> None:
        self.run_tool("remember", fact="the user ships on Fridays", category="about_user")
        facts = [e["fact"] for e in self.engine.knowledge_base["learned_facts"]]
        self.assertIn("the user ships on Fridays", facts)

    def test_remember_survives_a_restart(self) -> None:
        self.run_tool("remember", fact="jimmy lives in this repo")
        reloaded = LearningEngine(os.path.join(self.root, "memory.json"))
        self.assertEqual(len(reloaded.knowledge_base["learned_facts"]), 1)

    def test_remembering_twice_reinforces(self) -> None:
        self.run_tool("remember", fact="same thing")
        self.assertIn("reinforced", self.run_tool("remember", fact="same thing"))

    def test_recall_finds_what_was_remembered(self) -> None:
        self.run_tool("remember", fact="the deploy script is ops/deploy.sh")
        self.assertIn("deploy.sh", self.run_tool("recall", query="deploy"))

    def test_recall_on_an_empty_memory_is_graceful(self) -> None:
        self.assertIn("Nothing in memory", self.run_tool("recall", query="anything"))

    def test_empty_fact_is_an_error(self) -> None:
        self.expect_error("remember", fact="   ")


class TestCallDescription(ToolboxTestCase):
    def test_describes_a_call_for_the_transcript(self) -> None:
        self.assertEqual(self.box.describe_call("read_file", {"path": "a.py"}), "read_file(a.py)")

    def test_falls_back_to_any_argument(self) -> None:
        self.assertEqual(
            self.box.describe_call("list_files", {"pattern": "*.py"}), "list_files(*.py)"
        )

    def test_truncates_a_long_description(self) -> None:
        description = self.box.describe_call("remember", {"fact": "x" * 200})
        self.assertLessEqual(len(description), 80)


# ----------------------------------------------------------------------
# The tool loop
# ----------------------------------------------------------------------


class FakeBlock:
    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


class FakeMessage:
    def __init__(self, content: List[Any], stop_reason: str = "end_turn") -> None:
        self.content = content
        self.stop_reason = stop_reason


class ScriptedStream:
    def __init__(self, message: FakeMessage) -> None:
        self._message = message
        self.text_stream = [b.text for b in message.content if b.type == "text"]

    def __enter__(self) -> "ScriptedStream":
        return self

    def __exit__(self, *args: Any) -> bool:
        return False

    def get_final_message(self) -> FakeMessage:
        return self._message


class ScriptedMessages:
    """Replays a scripted list of model turns and records each request."""

    def __init__(self, turns: List[FakeMessage]) -> None:
        self.turns = list(turns)
        self.requests: List[Dict[str, Any]] = []

    def stream(self, **kwargs: Any) -> ScriptedStream:
        self.requests.append(kwargs)
        turn = self.turns.pop(0) if self.turns else FakeMessage([FakeBlock(type="text", text="done")])
        return ScriptedStream(turn)


class ScriptedClient:
    def __init__(self, turns: List[FakeMessage]) -> None:
        self.messages = ScriptedMessages(turns)


class TestToolLoop(ToolboxTestCase):
    def _brain(self, turns: List[FakeMessage]) -> Brain:
        self.client = ScriptedClient(turns)
        return Brain(client=self.client)

    def test_tools_are_sent_only_when_a_toolbox_is_given(self) -> None:
        brain = self._brain([FakeMessage([FakeBlock(type="text", text="hi")])])
        brain.respond("hi")
        self.assertNotIn("tools", self.client.messages.requests[0])

        brain = self._brain([FakeMessage([FakeBlock(type="text", text="hi")])])
        brain.respond("hi", toolbox=self.box)
        self.assertEqual(len(self.client.messages.requests[0]["tools"]), 5)

    def test_a_tool_call_is_executed_and_fed_back(self) -> None:
        brain = self._brain([
            FakeMessage(
                [
                    FakeBlock(type="text", text="Let me look."),
                    FakeBlock(type="tool_use", id="t1", name="read_file", input={"path": "hello.py"}),
                ],
                stop_reason="tool_use",
            ),
            FakeMessage([FakeBlock(type="text", text="It defines greet().")]),
        ])

        reply = brain.respond("what is in hello.py?", toolbox=self.box)

        self.assertIn("Let me look.", reply)
        self.assertIn("It defines greet().", reply)

        followup = self.client.messages.requests[1]["messages"]
        result = followup[-1]["content"][0]
        self.assertEqual(result["type"], "tool_result")
        self.assertEqual(result["tool_use_id"], "t1")
        self.assertFalse(result["is_error"])
        self.assertIn("def greet():", result["content"])

    def test_parallel_tool_calls_return_in_one_message(self) -> None:
        brain = self._brain([
            FakeMessage(
                [
                    FakeBlock(type="tool_use", id="a", name="list_files", input={}),
                    FakeBlock(type="tool_use", id="b", name="read_file", input={"path": "notes.txt"}),
                ],
                stop_reason="tool_use",
            ),
            FakeMessage([FakeBlock(type="text", text="Both done.")]),
        ])

        brain.respond("look around", toolbox=self.box)

        results = self.client.messages.requests[1]["messages"][-1]["content"]
        self.assertEqual([r["tool_use_id"] for r in results], ["a", "b"])

    def test_a_failing_tool_is_reported_as_is_error_not_raised(self) -> None:
        brain = self._brain([
            FakeMessage(
                [FakeBlock(type="tool_use", id="t1", name="read_file", input={"path": "../escape"})],
                stop_reason="tool_use",
            ),
            FakeMessage([FakeBlock(type="text", text="I couldn't read that.")]),
        ])

        reply = brain.respond("read it", toolbox=self.box)

        result = self.client.messages.requests[1]["messages"][-1]["content"][0]
        self.assertTrue(result["is_error"])
        self.assertIn("outside", result["content"])
        self.assertIn("couldn't", reply)

    def test_the_loop_is_capped(self) -> None:
        """A model that only ever calls tools must still terminate."""
        looping = [
            FakeMessage(
                [FakeBlock(type="tool_use", id=f"t{n}", name="list_files", input={})],
                stop_reason="tool_use",
            )
            for n in range(MAX_TOOL_ROUNDS + 5)
        ]
        brain = self._brain(looping)

        reply = brain.respond("go", toolbox=self.box)

        self.assertLessEqual(len(self.client.messages.requests), MAX_TOOL_ROUNDS + 1)
        self.assertTrue(reply.strip(), "should still produce an answer, never silence")
        self.assertIn("empty", reply, "with no text at all, say so rather than returning nothing")
        self.assertIsNone(self.client.messages.requests[-1].get("tools"),
                          "the final forced answer should not offer tools again")

    def test_tool_calls_are_announced(self) -> None:
        brain = self._brain([
            FakeMessage(
                [FakeBlock(type="tool_use", id="t1", name="list_files", input={"path": "sub"})],
                stop_reason="tool_use",
            ),
            FakeMessage([FakeBlock(type="text", text="ok")]),
        ])
        announced: List[str] = []

        brain.respond("look", toolbox=self.box, on_tool=announced.append)

        self.assertEqual(announced, ["list_files(sub)"])

    def test_refusal_short_circuits_the_loop(self) -> None:
        brain = self._brain([FakeMessage([], stop_reason="refusal")])
        self.assertIn("rather not", brain.respond("hi", toolbox=self.box))


class TestAgentIntegration(unittest.TestCase):
    def test_tools_are_off_when_requested(self) -> None:
        from jimmy_agent import Jimmy

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = Jimmy(memory_file=os.path.join(tmpdir, "m.json"), offline=True, use_tools=False)
            self.assertIsNone(agent.toolbox)
            self.assertIn("off", agent.chat("tools"))

    def test_tools_command_lists_them(self) -> None:
        from jimmy_agent import Jimmy

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = Jimmy(memory_file=os.path.join(tmpdir, "m.json"), offline=True, root=tmpdir)
            response = agent.chat("tools")
            for name in ("read_file", "list_files", "search_files", "remember", "recall"):
                self.assertIn(name, response)

    def test_tools_command_does_not_pollute_memory(self) -> None:
        from jimmy_agent import Jimmy

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = Jimmy(memory_file=os.path.join(tmpdir, "m.json"), offline=True, root=tmpdir)
            agent.chat("tools")
            self.assertEqual(agent.engine.knowledge_base["total_interactions"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
