"""
Jimmy's hands - a deliberately small toolbox.

Five stdlib-only tools, no new dependencies and no background processes. Every
one is bounded: capped output, capped file sizes, a capped directory walk and a
path sandbox, so a tool call costs a few milliseconds and a few kilobytes rather
than pinning the machine.

Nothing here writes to or executes anything on your filesystem. The only thing
Jimmy can change is his own memory.
"""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Budgets. These exist to keep Jimmy light on a normal laptop.
MAX_FILE_BYTES = 40_000
MAX_LINES = 200
MAX_LINE_CHARS = 300
MAX_LIST_ENTRIES = 60
MAX_SEARCH_HITS = 20
MAX_FILES_WALKED = 600
MAX_RESULT_CHARS = 8_000

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", ".mypy_cache", ".pytest_cache", ".idea", ".tox",
}
SKIP_SUFFIXES = {
    ".pyc", ".so", ".dll", ".dylib", ".zip", ".tar", ".gz", ".png", ".jpg",
    ".jpeg", ".gif", ".pdf", ".mp3", ".mp4", ".woff", ".woff2", ".ico",
}


class ToolError(Exception):
    """A tool failed in a way Claude should see and can recover from."""


def _truncate(text: str, limit: int = MAX_RESULT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... (truncated at {limit} characters)"


def _looks_binary(path: Path) -> bool:
    if path.suffix.lower() in SKIP_SUFFIXES:
        return True
    try:
        with open(path, "rb") as handle:
            return b"\0" in handle.read(1024)
    except OSError:
        return True


class Toolbox:
    """The tools Jimmy can call, and the sandbox they run in."""

    def __init__(self, engine: Any, root: str = ".") -> None:
        self.engine = engine
        self.root = Path(root).resolve()
        self.call_log: List[str] = []

    # ------------------------------------------------------------------
    # Sandbox
    # ------------------------------------------------------------------

    def _resolve(self, path: str) -> Path:
        """Resolve inside the sandbox root, or refuse."""
        candidate = (self.root / path).resolve() if not os.path.isabs(path) else Path(path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError:
            raise ToolError(
                f"'{path}' is outside {self.root}. I can only look inside the folder I was started in."
            ) from None
        return candidate

    def _relative(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)

    # ------------------------------------------------------------------
    # Definitions
    # ------------------------------------------------------------------

    def definitions(self) -> List[Dict[str, Any]]:
        """The tool schemas sent to the model."""
        return [
            {
                "name": "read_file",
                "description": (
                    "Read a text file from the folder Jimmy was started in. "
                    f"Returns at most {MAX_LINES} lines per call - use start_line to page through a longer file."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path relative to the working folder."},
                        "start_line": {"type": "integer", "description": "1-indexed first line to return. Default 1."},
                        "max_lines": {"type": "integer", "description": f"Lines to return, up to {MAX_LINES}."},
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "list_files",
                "description": (
                    "List files and folders at a path. Use this to find out what exists "
                    "before reading anything."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Folder to list. Default '.'."},
                        "pattern": {"type": "string", "description": "Optional glob filter, e.g. '*.py'."},
                    },
                    "required": [],
                },
            },
            {
                "name": "search_files",
                "description": (
                    "Search file contents for a regular expression and return matching lines "
                    "with their file and line number. Good for finding where something is defined."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Regular expression to search for."},
                        "path": {"type": "string", "description": "Folder to search in. Default '.'."},
                        "pattern": {"type": "string", "description": "Optional filename glob, e.g. '*.py'."},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "remember",
                "description": (
                    "Save something worth keeping about this user or their project into your "
                    "permanent memory. Use it when you learn something that should outlive this session."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "fact": {"type": "string", "description": "The fact, in one clear sentence."},
                        "category": {
                            "type": "string",
                            "description": "'about_user' for personal details, 'project' for code and repo facts, otherwise 'general'.",
                        },
                    },
                    "required": ["fact"],
                },
            },
            {
                "name": "recall",
                "description": (
                    "Search your own memory for what you already know. Use it before saying "
                    "you don't know something."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "What to look for."},
                    },
                    "required": ["query"],
                },
            },
        ]

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def run(self, name: str, arguments: Dict[str, Any]) -> Tuple[str, bool]:
        """Execute a tool. Returns (result_text, is_error) and never raises."""
        self.call_log.append(f"{name}({arguments})")
        handler = {
            "read_file": self._read_file,
            "list_files": self._list_files,
            "search_files": self._search_files,
            "remember": self._remember,
            "recall": self._recall,
        }.get(name)

        if handler is None:
            return f"Error: there is no tool called '{name}'.", True

        try:
            return _truncate(handler(arguments)), False
        except ToolError as exc:
            return f"Error: {exc}", True
        except OSError as exc:
            return f"Error: {exc}", True
        except (re.error, ValueError, TypeError) as exc:
            return f"Error: {exc}", True

    def describe_call(self, name: str, arguments: Dict[str, Any]) -> str:
        """A one-line, human-readable version of a call, for the transcript."""
        key = {"read_file": "path", "list_files": "path", "search_files": "query",
               "remember": "fact", "recall": "query"}.get(name)
        value = str(arguments.get(key, "")) if key else ""
        if not value:
            # Fall back to whatever argument was actually passed, so a call is
            # never shown as a bare `list_files()` when it had a filter.
            value = next((str(v) for v in arguments.values() if str(v).strip()), "")
        if len(value) > 60:
            value = value[:57] + "..."
        return f"{name}({value})" if value else f"{name}()"

    # ------------------------------------------------------------------
    # Implementations
    # ------------------------------------------------------------------

    def _read_file(self, arguments: Dict[str, Any]) -> str:
        path = self._resolve(str(arguments.get("path", "")))
        if not path.exists():
            raise ToolError(f"'{self._relative(path)}' does not exist.")
        if path.is_dir():
            raise ToolError(f"'{self._relative(path)}' is a folder - use list_files.")
        if _looks_binary(path):
            raise ToolError(f"'{self._relative(path)}' looks binary, so there is nothing to read.")

        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            note = f"\n(file is {size:,} bytes; only the first {MAX_FILE_BYTES:,} were read)"
        else:
            note = ""

        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            content = handle.read(MAX_FILE_BYTES)

        lines = content.splitlines()
        start = max(1, int(arguments.get("start_line", 1) or 1))
        count = min(int(arguments.get("max_lines", MAX_LINES) or MAX_LINES), MAX_LINES)
        window = lines[start - 1 : start - 1 + count]

        if not window:
            raise ToolError(f"'{self._relative(path)}' has {len(lines)} lines; line {start} is past the end.")

        numbered = "\n".join(
            f"{number:>5}  {line[:MAX_LINE_CHARS]}"
            for number, line in enumerate(window, start=start)
        )
        footer = ""
        if start - 1 + len(window) < len(lines):
            footer = f"\n... ({len(lines) - (start - 1 + len(window))} more lines - call again with start_line={start + len(window)})"
        return f"{self._relative(path)} (lines {start}-{start + len(window) - 1} of {len(lines)}){note}\n{numbered}{footer}"

    def _list_files(self, arguments: Dict[str, Any]) -> str:
        path = self._resolve(str(arguments.get("path", ".") or "."))
        if not path.exists():
            raise ToolError(f"'{self._relative(path)}' does not exist.")
        if not path.is_dir():
            raise ToolError(f"'{self._relative(path)}' is a file, not a folder.")

        pattern = str(arguments.get("pattern", "") or "")
        entries = []
        for entry in sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if entry.name in SKIP_DIRS or entry.name.startswith(".") and entry.is_dir():
                continue
            if pattern and entry.is_file() and not fnmatch.fnmatch(entry.name, pattern):
                continue
            if entry.is_dir():
                entries.append(f"  {entry.name}/")
            else:
                try:
                    entries.append(f"  {entry.name}  ({entry.stat().st_size:,} bytes)")
                except OSError:
                    entries.append(f"  {entry.name}")

        if not entries:
            return f"{self._relative(path)}/ is empty (or nothing matched '{pattern}')."

        shown = entries[:MAX_LIST_ENTRIES]
        more = f"\n  ... and {len(entries) - len(shown)} more" if len(entries) > len(shown) else ""
        return f"{self._relative(path)}/ contains {len(entries)} entries:\n" + "\n".join(shown) + more

    def _search_files(self, arguments: Dict[str, Any]) -> str:
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise ToolError("search_files needs a query.")
        regex = re.compile(query, re.IGNORECASE)

        root = self._resolve(str(arguments.get("path", ".") or "."))
        pattern = str(arguments.get("pattern", "") or "")

        hits: List[str] = []
        walked = 0
        for directory, subdirs, filenames in os.walk(root):
            subdirs[:] = [d for d in subdirs if d not in SKIP_DIRS and not d.startswith(".")]
            for filename in sorted(filenames):
                if walked >= MAX_FILES_WALKED or len(hits) >= MAX_SEARCH_HITS:
                    break
                if pattern and not fnmatch.fnmatch(filename, pattern):
                    continue
                candidate = Path(directory) / filename
                if _looks_binary(candidate):
                    continue
                walked += 1
                try:
                    with open(candidate, "r", encoding="utf-8", errors="replace") as handle:
                        for number, line in enumerate(handle, start=1):
                            if regex.search(line):
                                hits.append(
                                    f"  {self._relative(candidate)}:{number}: {line.strip()[:MAX_LINE_CHARS]}"
                                )
                                if len(hits) >= MAX_SEARCH_HITS:
                                    break
                except OSError:
                    continue
            if walked >= MAX_FILES_WALKED or len(hits) >= MAX_SEARCH_HITS:
                break

        if not hits:
            return f"No matches for /{query}/ in {self._relative(root)}/ ({walked} files searched)."
        capped = " (stopped at the result limit)" if len(hits) >= MAX_SEARCH_HITS else ""
        return f"{len(hits)} matches for /{query}/{capped}:\n" + "\n".join(hits)

    def _remember(self, arguments: Dict[str, Any]) -> str:
        fact = str(arguments.get("fact", "")).strip()
        if not fact:
            raise ToolError("remember needs a fact.")
        category = str(arguments.get("category", "general") or "general")

        entry = self.engine.learn_fact(fact, category=category)
        if entry["times_reinforced"] > 1:
            return f"Already knew that - reinforced it (now x{entry['times_reinforced']})."
        return f"Saved to permanent memory under '{category}'."

    def _recall(self, arguments: Dict[str, Any]) -> str:
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise ToolError("recall needs a query.")

        facts = self.engine.recall_relevant_facts(query)
        conversations = self.engine.recall_similar_conversations(query)

        sections = []
        if facts:
            sections.append("Facts:\n" + "\n".join(f"  - {f['fact']}" for f in facts))
        if conversations:
            sections.append(
                "Past exchanges:\n"
                + "\n".join(
                    f"  - they said {item['conversation']['user']!r}" for item in conversations
                )
            )
        if not sections:
            return f"Nothing in memory about '{query}'."
        return "\n".join(sections)
