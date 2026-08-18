"""
Learning Engine for Jimmy - Handles memory, knowledge, and skill development
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Any

class LearningEngine:
    """Core learning system for Jimmy"""
    
    def __init__(self, memory_file: str = "memory.json"):
        self.memory_file = memory_file
        self.knowledge_base = self._load_memory()
        self.conversation_count = 0
        self.skills = []
        self.learning_progress = 0
        
    def _load_memory(self) -> Dict[str, Any]:
        """Load existing memory from file"""
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return self._create_empty_memory()
        return self._create_empty_memory()
    
    def _create_empty_memory(self) -> Dict[str, Any]:
        """Create a fresh memory structure"""
        return {
            "created_at": datetime.now().isoformat(),
            "conversations": [],
            "learned_facts": [],
            "skills": [],
            "preferences": {},
            "learning_score": 0,
            "total_interactions": 0
        }
    
    def save_memory(self):
        """Save memory to file"""
        with open(self.memory_file, 'w', encoding='utf-8') as f:
            json.dump(self.knowledge_base, f, indent=2, ensure_ascii=False)
    
    def add_conversation(self, user_input: str, response: str) -> None:
        """Store a conversation for learning"""
        conversation = {
            "timestamp": datetime.now().isoformat(),
            "user": user_input,
            "response": response,
            "interaction_id": self.knowledge_base["total_interactions"] + 1
        }
        self.knowledge_base["conversations"].append(conversation)
        self.knowledge_base["total_interactions"] += 1
        self.conversation_count += 1
        self._update_learning_score()
        self.save_memory()
    
    def learn_fact(self, fact: str, category: str = "general") -> None:
        """Learn and store a new fact"""
        learned_fact = {
            "fact": fact,
            "category": category,
            "learned_at": datetime.now().isoformat(),
            "confidence": 1.0
        }
        self.knowledge_base["learned_facts"].append(learned_fact)
        self.save_memory()
    
    def learn_skill(self, skill_name: str, description: str = "") -> None:
        """Learn a new skill"""
        skill = {
            "name": skill_name,
            "description": description,
            "learned_at": datetime.now().isoformat(),
            "proficiency": 0.5  # Start at 50%
        }
        self.knowledge_base["skills"].append(skill)
        self.skills.append(skill_name)
        self.save_memory()
    
    def improve_skill(self, skill_name: str, improvement_rate: float = 0.1) -> None:
        """Improve proficiency in a skill"""
        for skill in self.knowledge_base["skills"]:
            if skill["name"] == skill_name:
                skill["proficiency"] = min(1.0, skill["proficiency"] + improvement_rate)
                break
        self.save_memory()
    
    def get_learning_stats(self) -> Dict[str, Any]:
        """Get statistics about Jimmy's learning"""
        return {
            "total_conversations": self.knowledge_base["total_interactions"],
            "facts_learned": len(self.knowledge_base["learned_facts"]),
            "skills_acquired": len(self.knowledge_base["skills"]),
            "learning_score": self.knowledge_base["learning_score"],
            "memory_file": self.memory_file,
            "active_skills": self.skills
        }
    
    def _update_learning_score(self) -> None:
        """Calculate and update learning progress score"""
        interactions = self.knowledge_base["total_interactions"]
        facts = len(self.knowledge_base["learned_facts"])
        skills = len(self.knowledge_base["skills"])
        
        # Score calculation: interactions contribute 40%, facts 30%, skills 30%
        interaction_score = min(interactions / 10, 40)  # Max 40 points
        fact_score = min(facts * 3, 30)  # Max 30 points
        skill_score = min(skills * 10, 30)  # Max 30 points
        
        self.knowledge_base["learning_score"] = int(interaction_score + fact_score + skill_score)
        self.learning_progress = self.knowledge_base["learning_score"]
    
    def recall_similar_conversations(self, query: str, limit: int = 3) -> List[Dict]:
        """Recall similar past conversations"""
        conversations = self.knowledge_base["conversations"]
        similar = []
        
        query_words = set(query.lower().split())
        
        for conv in conversations:
            user_message = conv["user"].lower()
            user_words = set(user_message.split())
            overlap = len(query_words & user_words)
            
            if overlap > 0:
                similar.append({
                    "conversation": conv,
                    "relevance_score": overlap
                })
        
        # Sort by relevance
        similar.sort(key=lambda x: x["relevance_score"], reverse=True)
        return similar[:limit]
    
    def get_memory_summary(self) -> str:
        """Get a human-readable summary of Jimmy's memory"""
        stats = self.get_learning_stats()
        summary = f"""
🧠 Jimmy's Learning Summary
{'='*40}
Conversations: {stats['total_conversations']}
Facts Learned: {stats['facts_learned']}
Skills Acquired: {stats['skills_acquired']}
Learning Score: {stats['learning_score']}/100
{'='*40}
"""
        if stats['active_skills']:
            summary += f"Active Skills: {', '.join(stats['active_skills'])}\n"
        
        return summary
