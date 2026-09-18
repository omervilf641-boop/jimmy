"""
Tests for Jimmy's voice.

This machine has no audio device and its egress policy blocks the TTS host, so
synthesis and playback are stubbed. What is tested is everything around them:
backend selection, voice choice, text cleanup, threading, interruption, the
commands, and the guarantee that a voice failure never breaks the chat.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from typing import List

import voice as voice_module
from jimmy import Jimmy
from voice import Voice, clean_for_speech, pick_voice_for


class TestTextCleanup(unittest.TestCase):
    def test_strips_emoji(self) -> None:
        self.assertEqual(clean_for_speech("Hello 👋 there 🤖"), "Hello there")

    def test_strips_markdown_and_box_drawing(self) -> None:
        self.assertEqual(clean_for_speech("**bold** ═══ `code`"), "bold code")

    def test_replaces_urls(self) -> None:
        self.assertIn("link", clean_for_speech("see https://example.com/x"))
        self.assertNotIn("https", clean_for_speech("see https://example.com/x"))

    def test_collapses_code_blocks(self) -> None:
        self.assertEqual(clean_for_speech("run ```python\nprint(1)\n``` now"), "run code block now")

    def test_keeps_hebrew_intact(self) -> None:
        self.assertEqual(clean_for_speech("שלום 🤖 עולם"), "שלום עולם")

    def test_truncates_very_long_text(self) -> None:
        spoken = clean_for_speech("word " * 500)
        self.assertLessEqual(len(spoken), 620)
        self.assertTrue(spoken.endswith("..."))

    def test_empty_after_cleanup_is_empty(self) -> None:
        self.assertEqual(clean_for_speech("🤖 ═══ 👋"), "")


class TestVoiceSelection(unittest.TestCase):
    def test_hebrew_text_gets_a_hebrew_voice(self) -> None:
        self.assertTrue(pick_voice_for("שלום ג'ימי").startswith("he-"))

    def test_english_text_gets_an_english_voice(self) -> None:
        self.assertTrue(pick_voice_for("hello jimmy").startswith("en-"))

    def test_mixed_text_prefers_hebrew(self) -> None:
        self.assertTrue(pick_voice_for("hello שלום").startswith("he-"))

    def test_explicit_voice_overrides_auto_detection(self) -> None:
        speaker = Voice(voice="en-GB-RyanNeural")
        self.assertEqual(speaker._resolve_voice("שלום"), "en-GB-RyanNeural")


class TestBackendSelection(unittest.TestCase):
    def test_no_player_and_no_system_tts_means_unavailable(self) -> None:
        speaker = Voice()
        speaker._player = None
        speaker._system_tts = None
        speaker._piper = None
        self.assertEqual(speaker._choose_backend(), "none")

    def test_edge_tts_wins_when_a_player_exists(self) -> None:
        speaker = Voice()
        speaker._player = ("/usr/bin/ffplay", [])
        self.assertEqual(speaker._choose_backend(), "edge-tts")

    def test_system_tts_is_used_when_there_is_no_player(self) -> None:
        speaker = Voice()
        speaker._player = None
        speaker._piper = None
        speaker._system_tts = "espeak-ng"
        self.assertEqual(speaker._choose_backend(), "system")

    def test_unavailable_voice_explains_itself(self) -> None:
        speaker = Voice()
        speaker._player = None
        speaker._system_tts = None
        speaker.backend = "none"
        self.assertIn("unavailable", speaker.status_line())
        self.assertTrue(speaker._why_unavailable())


class FakeSpeaker(Voice):
    """A Voice that records what it would have synthesised and played."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.backend = "edge-tts"
        self._player = ("/bin/true", [])
        self.synthesised: List[str] = []
        self.played: List[str] = []
        self.fail_with: Exception | None = None

    def _synthesize_edge(self, text: str, path: str) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.synthesised.append(text)
        with open(path, "wb") as handle:
            handle.write(b"ID3fake-mp3-bytes")

    def _play_file(self, path: str) -> None:
        self.played.append(open(path, "rb").read().decode("latin-1"))


class TestSpeaking(unittest.TestCase):
    def test_disabled_voice_says_nothing(self) -> None:
        speaker = FakeSpeaker(enabled=False)
        self.assertFalse(speaker.say("hello", block=True))
        self.assertEqual(speaker.synthesised, [])

    def test_enabled_voice_synthesises_and_plays(self) -> None:
        speaker = FakeSpeaker(enabled=True)
        self.assertTrue(speaker.say("Hello there", block=True))
        self.assertEqual(speaker.synthesised, ["Hello there"])
        self.assertEqual(speaker.played, ["ID3fake-mp3-bytes"])

    def test_spoken_text_is_cleaned_first(self) -> None:
        speaker = FakeSpeaker(enabled=True)
        speaker.say("🎓 New skill: **python**!", block=True)
        self.assertEqual(speaker.synthesised, ["New skill: python!"])

    def test_nothing_is_said_when_cleanup_leaves_nothing(self) -> None:
        speaker = FakeSpeaker(enabled=True)
        self.assertFalse(speaker.say("🤖👋", block=True))

    def test_synthesis_failure_never_raises(self) -> None:
        speaker = FakeSpeaker(enabled=True)
        speaker.fail_with = RuntimeError("the TTS host is unreachable")

        speaker.say("hello", block=True)  # must not raise

        self.assertEqual(speaker.played, [])
        self.assertIn("unreachable", speaker.last_error or "")

    def test_temp_file_is_cleaned_up(self) -> None:
        speaker = FakeSpeaker(enabled=True)
        before = len(os.listdir(tempfile.gettempdir()))
        for _ in range(5):
            speaker.say("hello", block=True)
        after = len(os.listdir(tempfile.gettempdir()))
        self.assertLessEqual(after, before + 1, "mp3 temp files should not accumulate")

    def test_stop_is_safe_when_nothing_is_playing(self) -> None:
        FakeSpeaker(enabled=True).stop()  # must not raise

    def test_speaking_does_not_block_the_caller(self) -> None:
        speaker = FakeSpeaker(enabled=True)
        self.assertTrue(speaker.say("hello"))  # block=False
        speaker._thread.join(timeout=5)
        self.assertEqual(speaker.synthesised, ["hello"])


class TestProxySupport(unittest.TestCase):
    def test_proxy_is_read_from_the_environment(self) -> None:
        original = os.environ.get("HTTPS_PROXY")
        os.environ["HTTPS_PROXY"] = "http://127.0.0.1:9999"
        try:
            self.assertEqual(voice_module._proxy(), "http://127.0.0.1:9999")
        finally:
            if original is None:
                del os.environ["HTTPS_PROXY"]
            else:
                os.environ["HTTPS_PROXY"] = original


class TestVoiceCommands(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.agent = Jimmy(
            memory_file=os.path.join(self.tmpdir.name, "m.json"), offline=True
        )
        self.agent.voice = FakeSpeaker(enabled=False)

    def test_voice_on_and_off(self) -> None:
        self.assertIn("on", self.agent.chat("voice on").lower())
        self.assertTrue(self.agent.voice.enabled)

        self.assertIn("off", self.agent.chat("voice off").lower())
        self.assertFalse(self.agent.voice.enabled)

    def test_bare_voice_reports_status(self) -> None:
        self.assertIn("Voice:", self.agent.chat("voice"))

    def test_voice_name_switches_and_enables(self) -> None:
        self.agent.chat("voice he-IL-HilaNeural")
        self.assertEqual(self.agent.voice.voice, "he-IL-HilaNeural")
        self.assertTrue(self.agent.voice.enabled)

    def test_hebrew_voice_command(self) -> None:
        self.agent.chat("קול on")
        self.assertTrue(self.agent.voice.enabled)

    def test_replies_are_spoken_when_voice_is_on(self) -> None:
        self.agent.chat("voice on")
        self.agent.voice.synthesised.clear()

        self.agent.chat("hello there")
        self.agent.voice._thread.join(timeout=5)
        self.assertTrue(self.agent.voice.synthesised, "the reply should have been spoken")

    def test_replies_are_silent_when_voice_is_off(self) -> None:
        self.agent.chat("hello there")
        self.assertEqual(self.agent.voice.synthesised, [])

    def test_voice_command_on_a_mute_machine_explains_itself(self) -> None:
        self.agent.voice.backend = "none"
        self.agent.voice._player = None
        self.agent.voice._system_tts = None
        self.assertIn("can't speak", self.agent.chat("voice on"))

    def test_voices_list_failure_is_reported_not_raised(self) -> None:
        def explode(prefix: str = "") -> List[str]:
            raise RuntimeError("no network")

        self.agent.voice.list_voices = explode
        self.assertIn("Couldn't fetch", self.agent.chat("voices"))

    def test_voices_list_is_rendered(self) -> None:
        self.agent.voice.list_voices = lambda prefix="": ["he-IL-AvriNeural", "he-IL-HilaNeural"]
        response = self.agent.chat("voices he")
        self.assertIn("he-IL-AvriNeural", response)
        self.assertIn("2 voices", response)

    def test_voice_commands_do_not_pollute_memory(self) -> None:
        self.agent.chat("voice on")
        self.agent.chat("voice off")
        self.assertEqual(self.agent.engine.knowledge_base["total_interactions"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
