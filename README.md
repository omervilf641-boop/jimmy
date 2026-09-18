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
| 🔧 **He can look** | Reads, lists and searches files in the folder you started him in |
| 🪶 **Light** | ~24ms to start, ~14MB idle — heavy imports load only when used |
| 🔊 **He talks** | Neural text-to-speech, Hebrew and English, picked to match your message |
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
python jimmy.py --voice                  # speak replies out loud
python jimmy.py --voice --voice-name he-IL-HilaNeural
python jimmy.py --no-tools                # don't let him look at files
python jimmy.py --root ~/code/myproject   # point him at a different folder
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
| `voice on` / `voice off` | Start or stop speaking replies out loud |
| `voice <name>` | Switch voice, e.g. `voice he-IL-HilaNeural` |
| `voices [prefix]` | List available voices, e.g. `voices he` |
| `tools` | What he can look at, and where |
| `help` | The command list |
| `exit` | End the session (everything is already saved) |

Hebrew aliases: `למד` · `כישור` · `שכח` · `סטטיסטיקה` · `התקדמות` · `זיכרון` · `קול` · `כלים` · `עזרה` · `יציאה`

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

## 🔧 Tools

Jimmy can look at your files to answer questions about them, instead of asking you to paste
things in. He decides when to use them — you just ask.

| Tool | What it does |
|---|---|
| `list_files` | See what's in a folder |
| `read_file` | Read a text file, paged |
| `search_files` | Regex search across files |
| `remember` | Save something durable into his memory |
| `recall` | Search his own memory |

```
💬 You: what does the tool loop do if the model keeps calling tools?
   🔧 search_files(MAX_TOOL_ROUNDS)
   🔧 read_file(brain.py)
🤖 Jimmy: It caps at 4 rounds, then asks for a plain answer with what it has.
```

**Deliberately small.** Five tools, standard library only, no new dependencies and no
background processes. Everything is bounded so a call costs milliseconds, not seconds:

- Files are read 200 lines and 40KB at a time; any result is capped at 8,000 characters
- A search stops after 600 files or 20 hits, and skips `.git`, `node_modules`, `__pycache__`
  and binaries
- The tool loop is capped at 4 rounds — one question can never run away

**He cannot write to or run anything on your machine.** The tools are read-only, confined to
the folder Jimmy was started in (`..` and absolute paths outside it are refused), and the
only thing he can change is his own memory. `--no-tools` turns them off entirely; `--root`
points him somewhere else.

Tools need the Claude brain — in offline mode there is no model to decide when to use them.

---

## 🪶 Footprint

Jimmy is meant to run on an ordinary laptop, so the expensive imports are deferred until
something actually needs them:

| | offline, no voice | with the Claude brain |
|---|---|---|
| startup | **~24 ms** | ~720 ms (first call only) |
| memory | **~14 MB** | ~67 MB |

A tool call costs 0.3–4 ms and under 200KB. `memory.json` is about 38KB after 200
conversations, and recall over it takes well under a millisecond. Three tests guard this —
if a heavy import creeps back into startup, they fail.

---

## 🔊 Voice

Jimmy can speak his replies. Turn it on with `--voice` at startup or `voice on` mid-chat.

```bash
pip install edge-tts          # the voices
brew install ffmpeg           # or: apt install ffmpeg / mpv / mpg123
python jimmy.py --voice
```

Voices come from **Microsoft Edge's neural TTS** — free, no API key, and genuinely good in
both Hebrew and English. By default Jimmy picks the voice to match the language you wrote
in: Hebrew gets `he-IL-AvriNeural`, everything else gets `en-US-AndrewMultilingualNeural`.
Run `voices he` or `voices en-US` to see the live catalogue and `voice <name>` to switch.

Backends are auto-detected in quality order — `edge-tts`, then `piper` if the binary is on
PATH, then the system engine (`say` on macOS, `espeak-ng` / `spd-say` on Linux, SAPI on
Windows). If none is available Jimmy tells you exactly what to install and stays silent.

Speech runs on a background thread, so you can keep typing while he talks; your next message
cuts him off. Emoji, markdown, box-drawing and URLs are stripped before speaking. **A voice
failure never interrupts the conversation** — worst case he goes quiet and records why.

If you are behind an HTTP proxy, set `HTTPS_PROXY` and Jimmy passes it through (the
underlying HTTP client does not pick it up on its own).

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
├── voice.py               # text to speech, with layered backend fallback
├── tools.py               # the five read-only tools and their sandbox
├── test_jimmy.py          # memory, learning and end-to-end tests
├── test_brain_online.py   # online request shape and failure modes
├── test_voice.py          # voice backends, cleanup and commands
├── test_tools.py          # sandbox, budgets and the tool loop
├── PROMPT.md              # the build brief this project was built from
├── requirements.txt       # one dependency: anthropic
└── memory.json            # created on first run — gitignored, it's yours
```

---

## 🧪 Tests

```bash
python -m unittest discover -p "test_*.py"
```

142 tests, no API key and no network required — the brain and the speaker are stubbed out,
so every test exercises real behaviour deterministically. They cover persistence across
restarts, schema migration from older memory files, corrupt-file recovery, duplicate
handling, skill proficiency growth, forgetting, recall ranking, passive extraction (Hebrew
and English), offline replies, the exact request sent to the API, voice backend selection,
speech cleanup, background speaking and interruption, the tool sandbox and every budget, the
tool loop including its cap, and the startup footprint.

---

## 🔒 Privacy

`memory.json` holds your actual conversations. It is gitignored and never leaves your
machine except as context in your own Claude API calls — and, when voice is on, the text of
his replies is sent to Microsoft's TTS service to be spoken. Turn voice off and nothing
goes there.

His tools are read-only and confined to the folder you start him in, but file contents he
reads do go to the Claude API as context. Use `--root` to narrow that, or `--no-tools` to
switch it off. `forget` and `export` are there so
you stay in control of it.

---

## 📝 License

MIT — use it, change it, make it yours.

---

**Made with ❤️ for learning and growth**
