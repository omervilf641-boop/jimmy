"""
Learning Engine for Jimmy - memory, knowledge, skills and user profile.

Everything Jimmy learns lives in a single JSON file and survives restarts.
The engine is deliberately dependency-free so it can be tested without an
API key and without network access.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 2

# How much each pillar of learning contributes to the 0-100 score.
_MAX_INTERACTION_POINTS = 40
_MAX_FACT_POINTS = 30
_MAX_SKILL_POINTS = 30


def _now() -> str:
    """Timezone-aware ISO timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _normalize(text: str) -> str:
    """Lowercase + collapse whitespace, used for duplicate detection."""
    return re.sub(r"\s+", " ", text.strip().lower())


class LearningEngine:
    """Core learning system for Jimmy."""

    def __init__(self, memory_file: str = "memory.json") -> None:
        self.memory_file = memory_file
        self.knowledge_base = self._load_memory()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_memory(self) -> Dict[str, Any]:
        """Load memory from disk, migrating older schemas when needed."""
        if not os.path.exists(self.memory_file):
            return self._create_empty_memory()

        try:
            with open(self.memory_file, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            # A corrupt or unreadable file must never crash Jimmy; start fresh
            # but keep the damaged file around so nothing is silently lost.
            self._quarantine_corrupt_file()
            return self._create_empty_memory()

        if not isinstance(data, dict):
            self._quarantine_corrupt_file()
            return self._create_empty_memory()

        return self._migrate(data)

    def _quarantine_corrupt_file(self) -> None:
        """Rename an unreadable memory file instead of overwriting it."""
        backup = f"{self.memory_file}.corrupt-{int(datetime.now().timestamp())}"
        try:
            os.replace(self.memory_file, backup)
        except OSError:
            pass

    def _migrate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Bring any older memory file up to the current schema."""
        memory = self._create_empty_memory()
        memory.update({k: v for k, v in data.items() if k in memory})

        # v1 stored a flat "preferences" dict at the top level.
        legacy_prefs = data.get("preferences")
        if isinstance(legacy_prefs, dict) and legacy_prefs:
            memory["user_profile"]["preferences"].update(legacy_prefs)

        # v1 facts/skills lacked the reinforcement + usage counters.
        for fact in memory["learned_facts"]:
            fact.setdefault("times_reinforced", 1)
            fact.setdefault("confidence", 1.0)
            fact.setdefault("category", "general")
            fact.setdefault("learned_at", memory.get("created_at", _now()))
        for skill in memory["skills"]:
            skill.setdefault("times_used", 0)
            skill.setdefault("proficiency", 0.5)
            skill.setdefault("description", "")
            skill.setdefault("learned_at", memory.get("created_at", _now()))

        memory["version"] = SCHEMA_VERSION
        return memory

    def _create_empty_memory(self) -> Dict[str, Any]:
        """A fresh, empty memory structure."""
        return {
            "version": SCHEMA_VERSION,
            "created_at": _now(),
            "updated_at": _now(),
            "user_profile": {"name": None, "preferences": {}},
            "conversations": [],
            "learned_facts": [],
            "skills": [],
            "learning_score": 0,
            "total_interactions": 0,
        }

    def save_memory(self) -> None:
        """Atomically write memory to disk (never leaves a half-written file)."""
        self.knowledge_base["updated_at"] = _now()
        directory = os.path.dirname(os.path.abspath(self.memory_file))
        os.makedirs(directory, exist_ok=True)

        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=directory, delete=False, suffix=".tmp"
        )
        try:
            with handle:
                json.dump(self.knowledge_base, handle, indent=2, ensure_ascii=False)
            os.replace(handle.name, self.memory_file)
        except OSError:
            try:
                os.unlink(handle.name)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def skills(self) -> List[str]:
        """Skill names, always read from stored memory so they survive restarts."""
        return [skill["name"] for skill in self.knowledge_base["skills"]]

    @property
    def user_name(self) -> Optional[str]:
        return self.knowledge_base["user_profile"].get("name")

    # ------------------------------------------------------------------
    # Learning
    # ------------------------------------------------------------------

    def add_conversation(self, user_input: str, response: str) -> None:
        """Store one exchange and refresh the learning score."""
        self.knowledge_base["conversations"].append(
            {
                "timestamp": _now(),
                "user": user_input,
                "response": response,
                "interaction_id": self.knowledge_base["total_interactions"] + 1,
            }
        )
        self.knowledge_base["total_interactions"] += 1
        self._update_learning_score()
        self.save_memory()

    def learn_fact(self, fact: str, category: str = "general") -> Dict[str, Any]:
        """Learn a fact. Teaching the same thing twice reinforces it, not duplicates it."""
        fact = fact.strip()
        if not fact:
            raise ValueError("Cannot learn an empty fact")

        existing = self._find_fact(fact)
        if existing is not None:
            existing["times_reinforced"] += 1
            existing["confidence"] = min(1.0, existing["confidence"] + 0.1)
            existing["last_reinforced_at"] = _now()
            if category != "general":
                existing["category"] = category
            self._update_learning_score()
            self.save_memory()
            return existing

        entry = {
            "fact": fact,
            "category": category,
            "learned_at": _now(),
            "confidence": 0.8,
            "times_reinforced": 1,
        }
        self.knowledge_base["learned_facts"].append(entry)
        self._update_learning_score()
        self.save_memory()
        return entry

    def _find_fact(self, fact: str) -> Optional[Dict[str, Any]]:
        target = _normalize(fact)
        for entry in self.knowledge_base["learned_facts"]:
            if _normalize(entry["fact"]) == target:
                return entry
        return None

    def learn_skill(self, skill_name: str, description: str = "") -> Dict[str, Any]:
        """Acquire a skill, or refresh one Jimmy already has."""
        skill_name = skill_name.strip()
        if not skill_name:
            raise ValueError("Cannot learn an unnamed skill")

        existing = self._find_skill(skill_name)
        if existing is not None:
            if description:
                existing["description"] = description
            self.improve_skill(skill_name)
            return existing

        entry = {
            "name": skill_name,
            "description": description,
            "learned_at": _now(),
            "proficiency": 0.5,
            "times_used": 0,
        }
        self.knowledge_base["skills"].append(entry)
        self._update_learning_score()
        self.save_memory()
        return entry

    def _find_skill(self, skill_name: str) -> Optional[Dict[str, Any]]:
        target = _normalize(skill_name)
        for entry in self.knowledge_base["skills"]:
            if _normalize(entry["name"]) == target:
                return entry
        return None

    def improve_skill(self, skill_name: str, improvement_rate: float = 0.05) -> Optional[float]:
        """Raise proficiency in a skill. Returns the new proficiency, or None."""
        skill = self._find_skill(skill_name)
        if skill is None:
            return None
        skill["proficiency"] = round(min(1.0, skill["proficiency"] + improvement_rate), 4)
        skill["times_used"] += 1
        skill["last_used_at"] = _now()
        self.save_memory()
        return skill["proficiency"]

    def practice_relevant_skills(self, text: str) -> List[str]:
        """Improve every skill mentioned in `text`. This is what makes skills grow."""
        lowered = text.lower()
        practiced: List[str] = []
        for skill in list(self.knowledge_base["skills"]):
            if skill["name"].lower() in lowered:
                self.improve_skill(skill["name"])
                practiced.append(skill["name"])
        return practiced

    def remember_preference(self, key: str, value: str) -> None:
        """Store something about how the user likes to be helped."""
        self.knowledge_base["user_profile"]["preferences"][key] = value
        self.save_memory()

    def set_user_name(self, name: str) -> None:
        self.knowledge_base["user_profile"]["name"] = name.strip()
        self.save_memory()

    # ------------------------------------------------------------------
    # Forgetting - the user owns their memory
    # ------------------------------------------------------------------

    def forget(self, query: str) -> Dict[str, List[str]]:
        """Remove anything matching `query`. Returns what was removed."""
        needle = _normalize(query)
        removed: Dict[str, List[str]] = {"facts": [], "skills": [], "preferences": []}
        if not needle:
            return removed

        kept_facts = []
        for entry in self.knowledge_base["learned_facts"]:
            if needle in _normalize(entry["fact"]):
                removed["facts"].append(entry["fact"])
            else:
                kept_facts.append(entry)
        self.knowledge_base["learned_facts"] = kept_facts

        kept_skills = []
        for entry in self.knowledge_base["skills"]:
            if needle in _normalize(entry["name"]):
                removed["skills"].append(entry["name"])
            else:
                kept_skills.append(entry)
        self.knowledge_base["skills"] = kept_skills

        prefs = self.knowledge_base["user_profile"]["preferences"]
        for key in [k for k in prefs if needle in _normalize(k) or needle in _normalize(str(prefs[k]))]:
            removed["preferences"].append(key)
            del prefs[key]

        name = self.user_name
        if name and needle in _normalize(name):
            self.knowledge_base["user_profile"]["name"] = None
            removed["preferences"].append("name")

        self._update_learning_score()
        self.save_memory()
        return removed

    def forget_everything(self) -> None:
        """Full reset - used by `forget everything`."""
        self.knowledge_base = self._create_empty_memory()
        self.save_memory()

    # ------------------------------------------------------------------
    # Recall - memory that actually reaches the response
    # ------------------------------------------------------------------

    def recall_similar_conversations(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Past exchanges ranked by keyword overlap, freshness as the tiebreaker."""
        query_words = self._keywords(query)
        if not query_words:
            return []

        scored = []
        conversations = self.knowledge_base["conversations"]
        total = len(conversations)
        for position, conv in enumerate(conversations):
            overlap = len(query_words & self._keywords(conv["user"]))
            if not overlap:
                continue
            recency = (position + 1) / total  # 0..1, newer is higher
            scored.append(
                {"conversation": conv, "relevance_score": overlap + recency}
            )

        scored.sort(key=lambda item: item["relevance_score"], reverse=True)
        return scored[:limit]

    def recall_relevant_facts(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Facts ranked by keyword overlap, then by how often they were reinforced."""
        query_words = self._keywords(query)
        scored = []
        for entry in self.knowledge_base["learned_facts"]:
            overlap = len(query_words & self._keywords(entry["fact"]))
            if overlap or entry["category"] == "about_user":
                score = overlap * 2 + entry["times_reinforced"] * 0.5
                if entry["category"] == "about_user":
                    score += 1  # what Jimmy knows about you is always worth surfacing
                scored.append((score, entry))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [entry for _, entry in scored[:limit]]

    @staticmethod
    def _keywords(text: str) -> set:
        """Content words only - stopwords would match everything."""
        stopwords = {
            "the", "a", "an", "is", "are", "was", "were", "to", "of", "and", "or",
            "in", "on", "at", "for", "with", "my", "me", "i", "you", "it", "that",
            "this", "do", "does", "did", "what", "how", "can", "please", "am",
            "אני", "אתה", "את", "של", "עם", "על", "זה", "מה", "איך", "לי", "הוא",
            "היא", "יש", "לא", "כן", "גם", "אבל", "כי", "רק",
        }
        words = re.findall(r"[\w֐-׿]+", text.lower())
        return {word for word in words if word not in stopwords and len(word) > 1}

    def build_context(self, query: str) -> str:
        """The memory block injected into the model's context before every reply."""
        sections: List[str] = []

        profile = self.knowledge_base["user_profile"]
        profile_lines = []
        if profile.get("name"):
            profile_lines.append(f"- Name: {profile['name']}")
        for key, value in profile.get("preferences", {}).items():
            profile_lines.append(f"- {key}: {value}")
        if profile_lines:
            sections.append("WHAT I KNOW ABOUT THIS USER:\n" + "\n".join(profile_lines))

        facts = self.recall_relevant_facts(query)
        if facts:
            sections.append(
                "RELEVANT THINGS I'VE LEARNED:\n"
                + "\n".join(f"- {entry['fact']}" for entry in facts)
            )

        skills = self.knowledge_base["skills"]
        if skills:
            sections.append(
                "MY SKILLS:\n"
                + "\n".join(
                    f"- {s['name']} (proficiency {int(s['proficiency'] * 100)}%)"
                    for s in skills
                )
            )

        similar = self.recall_similar_conversations(query)
        if similar:
            lines = []
            for item in similar:
                conv = item["conversation"]
                lines.append(f"- They said: {conv['user']!r} / I replied: {conv['response'][:120]!r}")
            sections.append("RELATED PAST EXCHANGES:\n" + "\n".join(lines))

        if not sections:
            return ""
        return "\n\n".join(sections)

    # ------------------------------------------------------------------
    # Stats & reporting
    # ------------------------------------------------------------------

    def _update_learning_score(self) -> None:
        """0-100 score: interactions 40%, facts 30%, skills 30%."""
        interactions = self.knowledge_base["total_interactions"]
        facts = len(self.knowledge_base["learned_facts"])
        skills = len(self.knowledge_base["skills"])

        interaction_score = min(interactions * 2, _MAX_INTERACTION_POINTS)
        fact_score = min(facts * 3, _MAX_FACT_POINTS)
        skill_score = min(skills * 10, _MAX_SKILL_POINTS)

        self.knowledge_base["learning_score"] = int(
            interaction_score + fact_score + skill_score
        )

    def get_learning_stats(self) -> Dict[str, Any]:
        return {
            "total_conversations": self.knowledge_base["total_interactions"],
            "facts_learned": len(self.knowledge_base["learned_facts"]),
            "skills_acquired": len(self.knowledge_base["skills"]),
            "learning_score": self.knowledge_base["learning_score"],
            "memory_file": self.memory_file,
            "active_skills": self.skills,
            "user_name": self.user_name,
            "preferences": dict(self.knowledge_base["user_profile"]["preferences"]),
        }

    def get_memory_summary(self) -> str:
        stats = self.get_learning_stats()
        lines = [
            "",
            "🧠 Jimmy's Memory",
            "=" * 44,
            f"Conversations : {stats['total_conversations']}",
            f"Facts learned : {stats['facts_learned']}",
            f"Skills        : {stats['skills_acquired']}",
            f"Learning score: {stats['learning_score']}/100",
            "=" * 44,
        ]
        if stats["user_name"]:
            lines.append(f"You are      : {stats['user_name']}")
        if stats["preferences"]:
            lines.append("Preferences  : " + ", ".join(
                f"{k}={v}" for k, v in stats["preferences"].items()
            ))
        if stats["active_skills"]:
            skills = self.knowledge_base["skills"]
            lines.append("Skills       : " + ", ".join(
                f"{s['name']} ({int(s['proficiency'] * 100)}%)" for s in skills
            ))
        recent = self.knowledge_base["learned_facts"][-3:]
        if recent:
            lines.append("Recent facts :")
            lines.extend(f"  • {entry['fact']}" for entry in recent)
        lines.append("")
        return "\n".join(lines)

    def export(self, path: str = "jimmy_memory_export.md") -> str:
        """Write a human-readable snapshot of everything Jimmy knows."""
        stats = self.get_learning_stats()
        lines = [
            "# Jimmy's Memory Export",
            "",
            f"Exported: {_now()}",
            f"Learning score: {stats['learning_score']}/100",
            "",
            "## User profile",
            "",
            f"- Name: {stats['user_name'] or 'unknown'}",
        ]
        for key, value in stats["preferences"].items():
            lines.append(f"- {key}: {value}")

        lines += ["", "## Facts", ""]
        lines += [
            f"- {e['fact']}  _(x{e['times_reinforced']}, {e['category']})_"
            for e in self.knowledge_base["learned_facts"]
        ] or ["_none yet_"]

        lines += ["", "## Skills", ""]
        lines += [
            f"- **{s['name']}** - {int(s['proficiency'] * 100)}% "
            f"(used {s['times_used']}x) {s['description']}".rstrip()
            for s in self.knowledge_base["skills"]
        ] or ["_none yet_"]

        lines += ["", "## Conversations", ""]
        for conv in self.knowledge_base["conversations"][-50:]:
            lines.append(f"- **{conv['timestamp']}**")
            lines.append(f"  - You: {conv['user']}")
            lines.append(f"  - Jimmy: {conv['response']}")

        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        return path
