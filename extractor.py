"""
Passive learning - picks up facts about the user from ordinary conversation.

This runs on every message in both online and offline mode, so Jimmy keeps
learning about you even without an API key. It is deliberately conservative:
a missed fact is better than a wrong one stored forever.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

_MAX_VALUE_LEN = 80

# A name is short and immediately follows an explicit introduction.
_NAME_PATTERNS = [
    r"(?:my name is|call me|i go by|i'm called|i am called)\s+([A-Za-z֐-׿][\w֐-׿'\-]{0,29})",
    r"(?:קוראים לי|שמי|השם שלי הוא|השם שלי)\s+([\w֐-׿'\-]{1,30})",
]

# (preference key, pattern) - the capture group is the value.
_PREFERENCE_PATTERNS = [
    ("likes", r"i (?:really |absolutely )?(?:like|love|enjoy)\s+(.+)"),
    ("likes", r"אני (?:ממש |מאוד )?(?:אוהב|אוהבת)\s+(.+)"),
    ("dislikes", r"i (?:really )?(?:hate|dislike|can't stand|cannot stand)\s+(.+)"),
    ("dislikes", r"אני (?:ממש )?(?:שונא|שונאת|לא אוהב|לא אוהבת)\s+(.+)"),
    ("prefers", r"i (?:would )?prefer\s+(.+)"),
    ("prefers", r"אני (?:מעדיף|מעדיפה)\s+(.+)"),
]

# Whole-sentence facts worth keeping verbatim.
_FACT_PATTERNS = [
    r"i work (?:at|for|as|in)\s+.+",
    r"i live in\s+.+",
    r"i(?:'m| am) (?:a|an)\s+[\w\s\-]{2,40}",
    r"i(?:'m| am) (?:learning|studying|building|working on)\s+.+",
    r"אני (?:עובד|עובדת)\s+.+",
    r"אני (?:גר|גרה)\s+.+",
    r"אני (?:לומד|לומדת|בונה|מפתח|מפתחת)\s+.+",
]


@dataclass
class Extraction:
    """Everything a single message revealed about the user."""

    name: Optional[str] = None
    preferences: Dict[str, str] = field(default_factory=dict)
    facts: List[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return self.name is None and not self.preferences and not self.facts

    def describe(self) -> str:
        """Short human-readable note about what was picked up."""
        parts = []
        if self.name:
            parts.append(f"your name ({self.name})")
        for key, value in self.preferences.items():
            parts.append(f"{key}: {value}")
        parts.extend(self.facts)
        return "; ".join(parts)


def _clean(value: str) -> str:
    """Trim trailing punctuation and clause tails, and cap the length."""
    value = value.strip()
    value = re.split(r"[.!?\n]|,\s+(?:but|and|because|so)\b", value, maxsplit=1)[0]
    value = value.strip(" \t.,!?;:'\"")
    return value[:_MAX_VALUE_LEN].strip()


def extract(text: str) -> Extraction:
    """Find anything worth remembering in a single user message."""
    result = Extraction()
    lowered = text.lower()

    for pattern in _NAME_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            name = _clean(match.group(1))
            # Reject obvious false positives like "my name is not important".
            if name and name.lower() not in {"not", "none", "no", "לא"}:
                result.name = name.title() if name.isascii() else name
                break

    for key, pattern in _PREFERENCE_PATTERNS:
        match = re.search(pattern, lowered, re.IGNORECASE)
        if match:
            value = _clean(match.group(1))
            if len(value) >= 2 and key not in result.preferences:
                result.preferences[key] = value

    for pattern in _FACT_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            fact = _clean(match.group(0))
            if len(fact) >= 6 and fact not in result.facts:
                result.facts.append(fact)

    return result
