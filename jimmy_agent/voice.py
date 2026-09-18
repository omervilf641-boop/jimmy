"""
Jimmy's voice - text to speech, with whatever the machine can actually offer.

Backends are auto-detected in quality order:

  1. edge-tts  Microsoft Edge's online neural voices. Free, no API key, and it
               covers Hebrew and English properly. This is the good one.
  2. piper     Offline neural TTS, if the `piper` binary is on PATH.
  3. system    macOS `say`, Linux `espeak-ng` / `spd-say`, Windows SAPI.
  4. none      Nothing available - Jimmy stays silent and says so.

Speech never blocks the conversation: it runs on a background thread, and the
next thing you say cuts off whatever he is still saying.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from typing import List, Optional, Tuple

import importlib.util

# edge-tts pulls in aiohttp: ~220ms and ~29MB. Loaded only when Jimmy speaks.
EDGE_FALLBACK_VOICE = "en-US-EmmaMultilingualNeural"  # the SDK's own default

_tts_module = None
_tts_loaded = False


def _tts():
    """Import edge-tts on demand. Returns None if it isn't installed."""
    global _tts_module, _tts_loaded
    if not _tts_loaded:
        _tts_loaded = True
        try:
            import edge_tts as module

            _tts_module = module
        except ImportError:  # pragma: no cover - only on bare installs
            _tts_module = None
    return _tts_module


def _tts_installed() -> bool:
    """Is edge-tts available? Checked without importing it."""
    if _tts_loaded:
        return _tts_module is not None
    return importlib.util.find_spec("edge_tts") is not None

# Preferred voices per language. The service's catalogue changes over time, so a
# rejected name falls back to the SDK's own default rather than failing.
HEBREW_VOICE = "he-IL-AvriNeural"
ENGLISH_VOICE = "en-US-AndrewMultilingualNeural"

# Players that can handle an mp3, best first.
_MP3_PLAYERS: List[Tuple[str, List[str]]] = [
    ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"]),
    ("mpv", ["--no-video", "--really-quiet"]),
    ("afplay", []),
    ("mpg123", ["-q"]),
    ("cvlc", ["--play-and-exit", "--intf", "dummy", "--quiet"]),
]

_HEBREW_RANGE = re.compile(r"[֐-׿]")
_MAX_SPOKEN_CHARS = 600


def _proxy() -> Optional[str]:
    """aiohttp does not read the proxy environment on its own, so pass it in."""
    return os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or None


def clean_for_speech(text: str) -> str:
    """Strip everything that sounds wrong when read aloud."""
    text = re.sub(r"```.*?```", " code block ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"https?://\S+", " link ", text)
    text = re.sub(r"[*_#>|]+", " ", text)
    text = re.sub(r"[═║╔╗╚╝─│┌┐└┘█░]+", " ", text)
    # Emoji and pictographs - they read as nothing useful.
    text = re.sub(
        "["
        "\U0001F000-\U0001FAFF"
        "\U00002600-\U000027BF"
        "\U0001F1E6-\U0001F1FF"
        "\U00002190-\U000021FF"
        "\U0000FE00-\U0000FE0F"
        "]+",
        " ",
        text,
    )
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text).strip()
    if len(text) > _MAX_SPOKEN_CHARS:
        text = text[:_MAX_SPOKEN_CHARS].rsplit(" ", 1)[0] + "..."
    return text


def pick_voice_for(text: str) -> str:
    """Hebrew text gets a Hebrew voice, everything else gets the English one."""
    return HEBREW_VOICE if _HEBREW_RANGE.search(text) else ENGLISH_VOICE


def _find_mp3_player() -> Optional[Tuple[str, List[str]]]:
    for name, args in _MP3_PLAYERS:
        path = shutil.which(name)
        if path:
            return path, args
    if sys.platform == "win32":  # pragma: no cover - Windows only
        powershell = shutil.which("powershell")
        if powershell:
            return powershell, ["-NoProfile", "-Command"]
    return None


def _find_system_tts() -> Optional[str]:
    for name in ("say", "espeak-ng", "espeak", "spd-say"):
        if shutil.which(name):
            return name
    return None


class Voice:
    """Speaks Jimmy's replies out loud, if the machine can."""

    def __init__(self, enabled: bool = False, voice: str = "auto", rate: str = "+0%") -> None:
        self.enabled = enabled
        self.voice = voice
        self.rate = rate
        self.last_error: Optional[str] = None

        self._player = _find_mp3_player()
        self._system_tts = _find_system_tts()
        self._piper = shutil.which("piper")
        self._process: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        self.backend = self._choose_backend()

    def _choose_backend(self) -> str:
        if _tts_installed() and self._player is not None:
            return "edge-tts"
        if self._piper and self._player is not None:
            return "piper"
        if self._system_tts:
            return "system"
        return "none"

    @property
    def available(self) -> bool:
        return self.backend != "none"

    def status_line(self) -> str:
        if not self.available:
            return "🔇 Voice: unavailable - " + self._why_unavailable()
        state = "on" if self.enabled else "off (type `voice on`)"
        return f"🔊 Voice: {self.backend}, {state}"

    def _why_unavailable(self) -> str:
        if not _tts_installed() and not self._system_tts:
            return "install edge-tts (pip install edge-tts) and an audio player like ffmpeg"
        if self._player is None and not self._system_tts:
            return "no audio player found (install ffmpeg, mpv or mpg123)"
        return "no text-to-speech engine found"

    # ------------------------------------------------------------------
    # Speaking
    # ------------------------------------------------------------------

    def say(self, text: str, block: bool = False) -> bool:
        """Speak `text`. Returns False if nothing was said, and never raises."""
        if not self.enabled or not self.available:
            return False

        spoken = clean_for_speech(text)
        if not spoken:
            return False

        self.stop()
        self._thread = threading.Thread(target=self._speak, args=(spoken,), daemon=True)
        self._thread.start()
        if block:
            self._thread.join()
        return True

    def _speak(self, text: str) -> None:
        try:
            if self.backend == "edge-tts":
                self._speak_edge(text)
            elif self.backend == "piper":
                self._speak_piper(text)
            elif self.backend == "system":
                self._speak_system(text)
        except Exception as exc:  # noqa: BLE001 - a voice failure must never break the chat
            self.last_error = str(exc)

    def _resolve_voice(self, text: str) -> str:
        return pick_voice_for(text) if self.voice == "auto" else self.voice

    def _synthesize_edge(self, text: str, path: str) -> None:
        """Write an mp3, retrying once with the SDK default if the voice is rejected."""
        edge_tts = _tts()
        if edge_tts is None:  # pragma: no cover - guarded by backend selection
            raise RuntimeError("edge-tts is not installed")

        chosen = self._resolve_voice(text)
        try:
            edge_tts.Communicate(text, chosen, rate=self.rate, proxy=_proxy()).save_sync(path)
        except Exception as exc:  # noqa: BLE001 - retry once, then let it surface
            self.last_error = f"voice '{chosen}' failed ({exc}); falling back to {EDGE_FALLBACK_VOICE}"
            edge_tts.Communicate(
                text, EDGE_FALLBACK_VOICE, rate=self.rate, proxy=_proxy()
            ).save_sync(path)

    def _speak_edge(self, text: str) -> None:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as handle:
            path = handle.name
        try:
            self._synthesize_edge(text, path)
            self._play_file(path)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _speak_piper(self, text: str) -> None:  # pragma: no cover - needs the binary
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            path = handle.name
        try:
            subprocess.run(
                [self._piper, "--output_file", path],
                input=text.encode("utf-8"),
                check=True,
                capture_output=True,
            )
            self._play_file(path)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _speak_system(self, text: str) -> None:  # pragma: no cover - needs the binary
        engine = self._system_tts
        if engine == "say":
            command = ["say", text]
        elif engine in ("espeak-ng", "espeak"):
            language = "he" if _HEBREW_RANGE.search(text) else "en"
            command = [engine, "-v", language, text]
        else:
            command = ["spd-say", "--wait", text]
        self._run(command)

    def _play_file(self, path: str) -> None:
        if self._player is None:
            return
        player, args = self._player
        if player.endswith("powershell") or player.endswith("powershell.exe"):  # pragma: no cover
            script = f"(New-Object Media.SoundPlayer '{path}').PlaySync()"
            self._run([player, *args, script])
        else:
            self._run([player, *args, path])

    def _run(self, command: List[str]) -> None:
        with self._lock:
            self._process = subprocess.Popen(
                command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            process = self._process
        process.wait()
        with self._lock:
            if self._process is process:
                self._process = None

    def stop(self) -> None:
        """Cut off whatever Jimmy is currently saying."""
        with self._lock:
            process = self._process
            self._process = None
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def list_voices(self, language: str = "") -> List[str]:
        """Live voice catalogue from the service. Needs network."""
        edge_tts = _tts()
        if edge_tts is None:
            return []
        import asyncio

        voices = asyncio.run(edge_tts.list_voices(proxy=_proxy()))
        names = sorted(
            entry["ShortName"]
            for entry in voices
            if not language or entry["ShortName"].lower().startswith(language.lower())
        )
        return names
