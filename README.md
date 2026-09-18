# 🤖 Jimmy — The Learning AI Agent

Jimmy is a personal AI agent that learns from **you** and remembers it. Every conversation,
fact, skill and preference is stored on disk and fed back into his next reply — so the more
you talk to him, the more useful he actually gets.

He runs on **Claude** when credentials are available, and keeps working without them.

---

## ✨ What Jimmy does

| | |
|---|---|
| 🧠 **Real reasoning** | Powered by the Claude API (`claude-opus-5`), streamed to your terminal |
| 💾 **Persistent memory** | Everything lives in `memory.json` and survives restarts |
| 🎯 **Memory that matters** | Relevant facts, preferences and past exchanges are injected before every reply |
| 🌱 **Passive learning** | He picks up your name, job and preferences from normal conversation |
| 🎓 **Skills that grow** | Proficiency rises each time a skill actually gets used |
| 🧹 **Your memory, your rules** | `forget` anything, or wipe it all |
| 💤 **Offline mode** | No API key? He still remembers, learns and responds |
| 🌍 **Bilingual** | Hebrew and English, commands included |

---

## 🚀 Getting started

```bash
git clone https://github.com/omervilf641-boop/jimmy.git
cd jimmy
pip install -r requirements.txt

export ANTHROPIC_API_KEY="sk-ant-..."   # optional - see Offline mode below
python jimmy.py
```

### Command-line options

```bash
python jimmy.py                          # interactive chat
python jimmy.py --ask "what do you know about me?"   # one question, then exit
python jimmy.py --offline                # never call the API
python jimmy.py --memory work.json       # keep separate memories
```

---

## 💬 Commands

| Command | What it does |
|---|---|
| `teach <fact>` | Store a fact. Teaching it twice reinforces it instead of duplicating it |
| `learn skill <name>` | Acquire a skill — it starts at 50% and improves with use |
| `forget <thing>` | Remove any fact, skill or preference matching it |
| `forget everything` | Wipe his memory completely |
| `stats` | Conversations, facts, skills, learning score |
| `progress` | The growth bar and current level |
| `memory` | Everything Jimmy currently remembers |
| `export [file]` | Write his memory out as readable Markdown |
| `help` | The command list |
| `exit` | End the session (everything is already saved) |

Hebrew aliases: `למד` · `כישור` · `שכח` · `סטטיסטיקה` · `התקדמות` · `זיכרון` · `עזרה` · `יציאה`

Anything that isn't a command is just conversation — and Jimmy learns from that too.

---

## 🧠 How the memory works

```
your message
   ↓
passive extraction     ← picks up name / job / preferences automatically
   ↓
recall                 ← relevant facts, preferences and past exchanges, ranked
   ↓
Claude                 ← memory injected as a mid-conversation system message
   ↓
skill practice         ← any skill mentioned gets a proficiency bump
   ↓
saved to memory.json   ← atomic write, survives restarts
```

**Learning score (0–100):** conversations 40% · facts 30% · skills 30%.
Levels: Beginner 🌱 → Growing 🌿 → Competent 🌳 → Expert 🌲

---

## 💤 Offline mode

Without an `ANTHROPIC_API_KEY` (or without the `anthropic` package), Jimmy tells you so and
switches to rule-based replies. **Everything else is unchanged** — memory, facts, skills,
preferences and commands all work identically. He will not bluff an answer he can't reason
out; he says he's offline instead.

If credentials are rejected mid-session, he switches to offline mode without losing anything.

---

## 📁 Project structure

```
jimmy/
├── jimmy.py               # the agent, CLI and command handling
├── brain.py               # Claude API integration + offline fallback
├── learning_engine.py     # memory, facts, skills, recall, persistence
├── extractor.py           # passive learning from ordinary conversation
├── test_jimmy.py          # memory, learning and end-to-end tests
├── test_brain_online.py   # online request shape and failure modes
├── PROMPT.md              # the build brief this project was built from
├── requirements.txt       # one dependency: anthropic
└── memory.json            # created on first run — gitignored, it's yours
```

---

## 🧪 Tests

```bash
python -m unittest discover -p "test_*.py"
```

61 tests, no API key and no network required — the brain is stubbed out, so every test
exercises real memory behaviour deterministically. They cover persistence across restarts,
schema migration from older memory files, corrupt-file recovery, duplicate handling, skill
proficiency growth, forgetting, recall ranking, passive extraction (Hebrew and English),
offline replies, the exact request sent to the API, and every failure branch around it.

---

## 🔒 Privacy

`memory.json` holds your actual conversations. It is gitignored and never leaves your
machine except as context in your own Claude API calls. `forget` and `export` are there so
you stay in control of it.

---

## 📝 License

MIT — use it, change it, make it yours.

---

**Made with ❤️ for learning and growth**
