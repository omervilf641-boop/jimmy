"""
Jimmy - The Learning AI Agent
A smart agent that learns from conversations and grows smarter over time
"""

import os
from learning_engine import LearningEngine
from datetime import datetime

class Jimmy:
    """Main AI Agent class - Jimmy"""
    
    def __init__(self, name: str = "Jimmy"):
        self.name = name
        self.engine = LearningEngine()
        self.active = False
        self.mood = "happy"
        self.learning_mode = True
        
    def greet(self):
        """Greet the user with personality"""
        greeting = f"""
╔════════════════════════════════════════╗
║  🤖 Welcome to {self.name}! 🤖            ║
║     Your Learning AI Agent             ║
╚════════════════════════════════════════╝

Hi! I'm {self.name}. I learn from every conversation we have.
The more you teach me, the smarter I become! 🧠✨

What would you like to teach me today?

Commands:
- teach [fact]        - Teach me something
- learn skill [name]  - Help me acquire a skill
- show my stats       - See my progress
- show my progress    - Visualize growth
- memory              - View my memory
- exit/quit           - End session
"""
        print(greeting)
        return greeting
    
    def chat(self, user_input: str) -> str:
        """Have a conversation with Jimmy"""
        
        if user_input.lower() in ["exit", "quit", "bye"]:
            return self.goodbye()
        
        # Process special commands
        if user_input.lower().startswith("teach "):
            return self.learn_from_user(user_input[6:])
        
        if user_input.lower().startswith("learn skill "):
            return self.acquire_skill(user_input[12:])
        
        if user_input.lower() == "show my stats":
            return self.show_stats()
        
        if user_input.lower() == "show my progress":
            return self.show_progress()
        
        if user_input.lower() == "memory":
            return self.engine.get_memory_summary()
        
        # Regular conversation with learning
        response = self.generate_response(user_input)
        self.engine.add_conversation(user_input, response)
        
        return response
    
    def learn_from_user(self, fact: str) -> str:
        """Learn a fact from the user"""
        self.engine.learn_fact(fact)
        responses = [
            f"✅ Great! I've learned: '{fact}' 📝",
            f"💡 Interesting! I'll remember: '{fact}'",
            f"🎯 Got it! '{fact}' is now in my memory!",
            f"📚 Noted! '{fact}' - I'm getting smarter! 🧠"
        ]
        response = responses[len(fact) % len(responses)]
        self.engine.add_conversation(f"teach {fact}", response)
        return response
    
    def acquire_skill(self, skill: str) -> str:
        """Learn a new skill"""
        skill_name = skill.split()[0] if skill else "new_skill"
        self.engine.learn_skill(skill_name, skill)
        responses = [
            f"🎓 Awesome! I'm now learning '{skill_name}'! Let's practice! 💪",
            f"⚡ New skill acquired: '{skill_name}'! I'll improve with practice!",
            f"🚀 '{skill_name}' is now in my toolkit! Ready to use it!",
            f"🌟 '{skill_name}' skill unlocked! Let's put it to good use!"
        ]
        response = responses[len(skill) % len(responses)]
        self.engine.add_conversation(f"learn skill {skill}", response)
        return response
    
    def generate_response(self, user_input: str) -> str:
        """Generate a response based on input"""
        user_lower = user_input.lower()
        
        # Check for similar past conversations
        similar = self.engine.recall_similar_conversations(user_input)
        
        # Simple response generation with personality
        if any(word in user_lower for word in ["hello", "hi", "hey", "greetings"]):
            return f"Hey there! 👋 I'm {self.name}, and I'm learning! How can I help?"
        
        elif any(word in user_lower for word in ["how are you", "how's it going"]):
            return f"I'm doing great! 🌟 I've learned from {self.engine.knowledge_base['total_interactions']} conversations so far. How about you?"
        
        elif any(word in user_lower for word in ["thanks", "thank you", "appreciate"]):
            return "You're welcome! 😊 Teaching me helps me grow smarter! 🧠"
        
        elif any(word in user_lower for word in ["what can you do", "abilities", "help"]):
            return f"""
Here's what I can do:
📚 Regular chat - I'll remember our conversations
🎓 'teach [fact]' - Teach me something new
⚡ 'learn skill [skill]' - Help me acquire new skills
📊 'show my stats' - See my learning progress
💾 'memory' - View my memory summary
🎯 'show my progress' - Visualize my growth
"""
        
        elif any(word in user_lower for word in ["sorry", "mistake", "wrong"]):
            return "No worries! Everyone makes mistakes. That's how I learn! 🌱 Thanks for the correction!"
        
        else:
            # Generic response
            responses = [
                f"That's interesting! 🤔 I'll remember that.",
                f"Got it! Adding that to my knowledge base. 📝",
                f"I hear you! This helps me learn. Thanks! 🙏",
                f"Cool! I'm storing this information. 💾",
                f"Understood! I'm getting smarter with every conversation! 🚀"
            ]
            return responses[hash(user_input) % len(responses)]
    
    def show_stats(self) -> str:
        """Display learning statistics"""
        stats = self.engine.get_learning_stats()
        output = f"""
📊 {self.name}'s Learning Statistics
{'='*50}
✅ Total Conversations: {stats['total_conversations']}
📚 Facts Learned: {stats['facts_learned']}
🎓 Skills Acquired: {stats['skills_acquired']}
🧠 Learning Score: {stats['learning_score']}/100

Current Skills: {', '.join(stats['active_skills']) if stats['active_skills'] else 'None yet'}
{'='*50}
"""
        return output
    
    def show_progress(self) -> str:
        """Show learning progress visually"""
        score = self.engine.knowledge_base["learning_score"]
        bar_length = 20
        filled = int(bar_length * score / 100)
        bar = "█" * filled + "░" * (bar_length - filled)
        
        level = "Beginner 🌱" if score < 25 else "Growing 🌿" if score < 50 else "Competent 🌳" if score < 75 else "Expert 🌲"
        
        output = f"""
🎯 {self.name}'s Learning Progress
{bar} {score}%

Level: {level}

Keep teaching me and I'll keep growing! 📈✨
"""
        return output
    
    def goodbye(self) -> str:
        """Say goodbye and save progress"""
        message = f"""
👋 Thanks for the great learning session!
I've grown from our {self.engine.knowledge_base['total_interactions']} conversations.
See you next time! Keep exploring! 🚀

💾 All memories saved! I'll remember everything! 🧠
"""
        return message
    
    def interactive_mode(self):
        """Start interactive conversation mode"""
        self.greet()
        self.active = True
        
        while self.active:
            try:
                user_input = input(f"\n💬 You: ").strip()
                
                if not user_input:
                    continue
                
                response = self.chat(user_input)
                print(f"\n🤖 {self.name}: {response}")
                
                if user_input.lower() in ["exit", "quit", "bye"]:
                    self.active = False
                
            except KeyboardInterrupt:
                print(f"\n\n{self.goodbye()}")
                self.active = False
            except Exception as e:
                print(f"❌ Error: {e}")
                continue


def main():
    """Main entry point"""
    # Create Jimmy
    jimmy = Jimmy()
    
    # Start interactive mode
    jimmy.interactive_mode()


if __name__ == "__main__":
    main()
