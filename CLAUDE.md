# mini-jarvis: notes for Claude

Omer's local voice assistant: an Electron UI plus a Python server, with no cloud. Talk to Omer in Hebrew. Code, commit messages and identifiers stay in English.

## Architecture
- **The app:** `main.js`, `preload.js` and `ui/` make up the Electron app. `ui/app.js` talks to Ollama at `localhost:11434`. The model is `qwen3:4b-instruct-2507-q4_K_M`; override it with localStorage `jarvis-model`.
- **The server:** `server.py` is the local server on port 8123. It handles:
  - the tools,
  - Piper TTS, using `voices/*.onnx`,
  - faster-whisper speech-to-text,
  - the openWakeWord `hey_jarvis` wake word.
- **The orb:** `server.py` already defines `ORB_STATES` (idle / listening / thinking / speaking), and `orb_stub.py` simulates the orb. A future ESP32 light should implement that same interface.
- **User data:** lives in `%APPDATA%\Jarvis` (notes, projects.json, traces.jsonl), never in the app folder.
- **Getting the code:** this folder has no git remote. It reaches other machines through OneDrive (`Documents\GitHub\mini-jarvis`) or a USB stick.

## Setting up on the school laptop
The laptop is a Dell Vostro 15 3530: i5-1334U, 16 GB RAM, Intel Iris Xe, **no NVIDIA GPU**. It is what goes to school for the project demo, so Jarvis must run on it with no help from the desktop.

1. Install Node.js LTS, Python 3.13 (on PATH), and [Ollama](https://ollama.com).
2. Pull the model: `ollama pull qwen3:4b-instruct-2507-q4_K_M` (2.5 GB). 16 GB of RAM holds it comfortably.
3. Install the Python packages: `pip install faster-whisper piper-tts openwakeword sounddevice numpy`
4. In this folder, run `npm install`, then `npm start`.
   - **If `voices/` is missing,** the folder arrived as a zip without it (the voices are 111 MB). Download both Piper voices into `voices/`, each as `.onnx` plus `.onnx.json`: `en_GB-alan-medium` and `he_IL-saspeech-medium`. They come from the official repo, huggingface.co/rhasspy/piper-voices (paths like `en/en_GB/alan/medium/`). Check the exact paths there before downloading.
5. **Speech-to-text:** Whisper falls back to CPU int8 automatically when CUDA is missing (see `get_whisper()` in `server.py`), so no code change is needed. Its first run downloads the model.
6. **Wake word:** if "Hey Jarvis" fails to load, openWakeWord may need its pretrained models downloaded once.
7. **Audio:**
   - **Output:** the orb speaker is a Bluetooth speaker lamp paired with the laptop, with a small AUX speaker as backup. Set it as the Windows default output device.
   - **Input:** use the laptop's built-in mic, placed away from the speaker, or Jarvis hears himself.
8. **Measure before the demo.** Everything runs on the CPU here. The desktop's median reply was 0.9 s on its GTX 1660. Time a few typical questions on the laptop, including the first request after startup, which has to process the long tool prompt. If it's too slow, try a smaller model, never a bigger one.
9. **Skip `see_screen` at the demo.** It uses `qwen2.5vl:3b`, which is far too slow on CPU.

## Hard rules
Each of these rules comes from a real failure.
- **Verify in the real state, never by the model's report.** The small model confidently fabricates completed actions.
- **Don't clean up the forgiveness layers:** arg unwrapping, Hebrew/phrase aliases, fuzzy project and skill matching. Each one fixed a malformed tool call that actually happened.
- **Project names stay in English.** The model corrupts Hebrew names when it echoes them, and then can't find them again.
- **Typing into other apps uses SendInput via `type_text.ps1`, never SendKeys.** On x64 the INPUT struct must be padded to 40 bytes, or SendInput silently returns 0.
- **On the desktop's GTX 1660, Whisper must use int8.** float16 took 39.9 s against 0.23 s on the same clip.
- **Don't commit unless Omer says so.**
