# -*- coding: utf-8 -*-
"""Mini-Jarvis local server.

Serves the web UI and exposes a small, whitelisted set of PC tools
that the model can call (open apps, open URLs, web search, time, system stats).
Python stdlib only — no pip installs needed.
"""
import json
import os
import subprocess
import tempfile
import hashlib
import secrets
import time
import threading
import webbrowser
import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

PORT = 8123
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Your notes, projects and training traces live outside the app folder, so
# reinstalling or rebuilding Jarvis never throws them away.
DATA_DIR = os.environ.get("JARVIS_DATA") or os.path.join(
    os.environ.get("APPDATA") or os.path.expanduser("~"), "Jarvis")
os.makedirs(DATA_DIR, exist_ok=True)


def _user_file(name):
    """Path inside DATA_DIR, migrating an older copy from the app folder once."""
    target = os.path.join(DATA_DIR, name)
    legacy = os.path.join(BASE_DIR, name)
    if not os.path.exists(target) and os.path.exists(legacy):
        try:
            import shutil
            shutil.copy2(legacy, target)
        except OSError:
            pass
    return target


NOTES_FILE = _user_file("notes.txt")

# Whitelisted apps only — the model can never run arbitrary commands.
APPS = {
    "notepad":    ("פנקס רשימות", "notepad.exe"),
    "calculator": ("מחשבון",      "calc.exe"),
    "paint":      ("צייר",        "mspaint.exe"),
    "explorer":   ("סייר הקבצים", "explorer.exe"),
    "chrome":     ("כרום",        "chrome"),
    "edge":       ("אדג'",        "msedge"),
    "settings":   ("הגדרות",      "ms-settings:"),
    "camera":     ("מצלמה",       "microsoft.windows.camera:"),
}


def ps(script: str) -> str:
    """Run a short PowerShell snippet and return stdout."""
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=15,
    )
    return out.stdout.strip()


def tool_get_time(_args):
    now = datetime.datetime.now()
    days = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
    return {
        "date": now.strftime("%d/%m/%Y"),
        "time": now.strftime("%H:%M"),
        "weekday": days[now.weekday()],
    }


def tool_open_app(args):
    app = str(args.get("app", "")).lower().strip()
    if app not in APPS:
        return {"error": f"אפליקציה לא מוכרת. אפשרויות: {', '.join(APPS)}"}
    name, target = APPS[app]
    subprocess.Popen(["cmd", "/c", "start", "", target])
    return {"opened": name}


def tool_open_url(args):
    url = str(args.get("url", "")).strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return {"error": "כתובת לא תקינה — חייבת להתחיל ב-http או https"}
    webbrowser.open(url)
    return {"opened": url}


def tool_search_web(args):
    query = str(args.get("query", "")).strip()
    if not query:
        return {"error": "חסרה שאילתת חיפוש"}
    from urllib.parse import quote_plus
    webbrowser.open("https://www.google.com/search?q=" + quote_plus(query))
    return {"searching": query}


def tool_system_stats(_args):
    stats = {}
    try:
        stats["cpu_percent"] = ps("(Get-CimInstance Win32_Processor).LoadPercentage")
        mem = ps("$os=Get-CimInstance Win32_OperatingSystem;"
                 "[math]::Round(($os.TotalVisibleMemorySize-$os.FreePhysicalMemory)/1MB,1);"
                 "[math]::Round($os.TotalVisibleMemorySize/1MB,1)").splitlines()
        if len(mem) >= 2:
            stats["ram_used_gb"], stats["ram_total_gb"] = mem[0], mem[1]
        battery = ps("(Get-CimInstance Win32_Battery).EstimatedChargeRemaining")
        stats["battery_percent"] = battery if battery else "אין סוללה (מחשב נייח)"
        disk = ps("$d=Get-PSDrive C;[math]::Round($d.Free/1GB,0)")
        stats["disk_c_free_gb"] = disk
    except Exception as e:
        stats["error"] = str(e)
    return stats


VOICES_DIR = os.path.join(BASE_DIR, "voices")
VOICE_MODEL = os.environ.get("JARVIS_VOICE", "en_GB-alan-medium")

_voice = None
_voice_lock = threading.Lock()


def get_voice():
    """Load the neural voice once. Windows' built-in SAPI voices sound like a
    2005 satnav; this is a local Piper model, no cloud involved."""
    global _voice
    with _voice_lock:
        if _voice is None:
            from piper import PiperVoice
            path = os.path.join(VOICES_DIR, VOICE_MODEL + ".onnx")
            if not os.path.exists(path):
                raise FileNotFoundError(f"missing voice model: {path}")
            _voice = PiperVoice.load(path)
    return _voice


def synthesize(text):
    """Return WAV bytes for the given text."""
    import io as _io
    import wave
    buf = _io.BytesIO()
    with wave.open(buf, "wb") as wav:
        get_voice().synthesize_wav(text, wav)
    return buf.getvalue()


TRACES_FILE = _user_file("traces.jsonl")


def append_trace(entry):
    """One line per exchange. This is the training corpus: what you asked, what
    the model decided to call, and whether it actually worked."""
    entry["ts"] = datetime.datetime.now().isoformat(timespec="seconds")
    with open(TRACES_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def tool_trace_stats(_args):
    """How much training data have we collected, and how clean is it?"""
    total = good = bad = 0
    tools = {}
    try:
        with open(TRACES_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                total += 1
                calls = e.get("tool_calls") or []
                for c in calls:
                    name = c.get("name", "?")
                    tools[name] = tools.get(name, 0) + 1
                if e.get("failed"):
                    bad += 1
                elif calls:
                    good += 1
    except FileNotFoundError:
        return {"exchanges": 0, "message": "עוד לא נאספו נתונים"}
    top = sorted(tools.items(), key=lambda kv: -kv[1])[:6]
    return {
        "exchanges": total,
        "with_successful_tools": good,
        "with_failures": bad,
        "top_tools": [f"{n} x{c}" for n, c in top],
        "file": TRACES_FILE,
    }


"""Wake word.

The browser's speech API can't do this in Electron, so detection runs here on
a dedicated model ("hey jarvis" ships with openWakeWord). Audio never leaves
the machine and is never stored — each 80ms frame is scored and discarded.
"""
WAKE_THRESHOLD = float(os.environ.get("JARVIS_WAKE_THRESHOLD", "0.55"))
_wake_state = {"enabled": False, "detected_at": 0.0, "last_score": 0.0, "error": None}
_wake_thread = None


def _wake_loop():
    import time
    try:
        import numpy as np
        import sounddevice as sd
        from openwakeword.model import Model
    except Exception as e:
        _wake_state["error"] = f"missing dependency: {e}"
        _wake_state["enabled"] = False
        return

    try:
        model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
    except Exception as e:
        _wake_state["error"] = f"model load failed: {e}"
        _wake_state["enabled"] = False
        return

    frame = 1280            # 80ms at 16kHz, what the model expects
    try:
        with sd.InputStream(samplerate=16000, channels=1, dtype="int16",
                            blocksize=frame) as stream:
            _wake_state["error"] = None
            while _wake_state["enabled"]:
                audio, _ = stream.read(frame)
                scores = model.predict(np.squeeze(audio))
                score = float(scores.get("hey_jarvis", 0.0))
                _wake_state["last_score"] = score
                if score > WAKE_THRESHOLD:
                    _wake_state["detected_at"] = time.time()
                    model.reset()          # avoid firing repeatedly on one phrase
                    time.sleep(1.5)
    except Exception as e:
        _wake_state["error"] = str(e)
    finally:
        _wake_state["enabled"] = False


def tool_wake_word(args):
    """Turn always-listening on or off."""
    global _wake_thread
    on = args.get("on")
    if isinstance(on, str):
        on = on.strip().lower() not in ("false", "off", "no", "0")
    if on is None:
        on = not _wake_state["enabled"]

    # Asking to enable something already enabled must not fall through to the
    # disable branch — that turned the listener off on a second "on" call.
    if on and _wake_state["enabled"]:
        return {"listening": True, "message": "כבר מאזין ברקע"}

    if on:
        _wake_state.update(enabled=True, error=None, detected_at=0.0)
        _wake_thread = threading.Thread(target=_wake_loop, daemon=True)
        _wake_thread.start()
        threading.Event().wait(1.0)        # let it fail fast if the mic is busy
        if _wake_state["error"]:
            return {"error": _wake_state["error"]}
        return {"listening": True, "message": 'אמור "Hey Jarvis" ואני אתעורר'}

    _wake_state["enabled"] = False
    return {"listening": False, "message": "הפסקתי להאזין ברקע"}


FACTS_FILE = _user_file("facts.json")


def _load_facts():
    try:
        with open(FACTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return []


def _save_facts(facts):
    with open(FACTS_FILE, "w", encoding="utf-8") as f:
        json.dump(facts, f, ensure_ascii=False, indent=2)


def tool_remember_fact(args):
    """Store something worth knowing about the user, permanently.

    Accepts a list as well as a single fact: a 7B model reliably produces one
    tool call per turn, so asking it to call this twice loses the second fact.
    """
    incoming = args.get("facts") or args.get("fact") or ""
    if isinstance(incoming, str):
        incoming = [incoming]
    items = [str(f).strip() for f in incoming if str(f).strip()]
    if not items:
        return {"error": "אין מה לזכור"}
    if len(items) > 1:
        results = [tool_remember_fact({"fact": f, "category": args.get("category")})
                   for f in items]
        stored = [r.get("remembered") or r.get("updated") for r in results]
        return {"remembered": [s for s in stored if s], "total": len(_load_facts())}

    text = items[0]
    category = str(args.get("category") or "general").strip() or "general"

    facts = _load_facts()
    # Replace a near-duplicate rather than piling up variations of one fact.
    key = "".join(ch for ch in text.lower() if ch.isalnum())
    for existing in facts:
        ekey = "".join(ch for ch in existing["fact"].lower() if ch.isalnum())
        if ekey == key or (len(key) > 12 and (key in ekey or ekey in key)):
            existing.update(fact=text, category=category,
                            updated=datetime.datetime.now().strftime("%d/%m/%Y"))
            _save_facts(facts)
            return {"updated": text}

    facts.append({
        "fact": text,
        "category": category,
        "added": datetime.datetime.now().strftime("%d/%m/%Y"),
    })
    _save_facts(facts)
    return {"remembered": text, "total": len(facts)}


def tool_recall_facts(args):
    """Everything Jarvis knows about the user, optionally filtered."""
    facts = _load_facts()
    query = str(args.get("about", "")).strip().lower()
    if query:
        facts = [f for f in facts
                 if query in f["fact"].lower() or query in f.get("category", "").lower()]
    return {"count": len(facts), "facts": [f["fact"] for f in facts]} if facts \
        else {"count": 0, "message": "עוד לא סיפרת לי כלום על עצמך"}


def tool_forget_fact(args):
    """Drop a fact — wrong, outdated, or simply private."""
    query = str(args.get("about", "")).strip().lower()
    if not query:
        return {"error": "צריך לציין מה לשכוח"}
    facts = _load_facts()
    keep = [f for f in facts if query not in f["fact"].lower()]
    removed = len(facts) - len(keep)
    _save_facts(keep)
    return {"forgot": removed} if removed else {"error": "לא מצאתי עובדה כזאת"}


PROJECTS_FILE = _user_file("projects.json")


def _load_projects():
    try:
        with open(PROJECTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {"last": None, "projects": {}}


def _save_projects(data):
    with open(PROJECTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def tool_save_project(args):
    """Remember what we're working on, so 'I'm back' can pick it up again."""
    name = str(args.get("name", "")).strip()
    if not name:
        return {"error": "צריך שם לפרויקט"}

    data = _load_projects()
    existing = data["projects"].get(name, {})

    def merge_list(key, incoming):
        old = existing.get(key, [])
        if incoming is None:
            return old
        if isinstance(incoming, str):
            incoming = [p.strip() for p in incoming.split(",") if p.strip()]
        return list(dict.fromkeys([*old, *incoming]))

    data["projects"][name] = {
        "name": name,
        "description": args.get("description") or existing.get("description", ""),
        "notes": args.get("notes") or existing.get("notes", ""),
        "apps": merge_list("apps", args.get("apps")),
        "urls": merge_list("urls", args.get("urls")),
        "minecraft": bool(args.get("minecraft", existing.get("minecraft", False))),
        "updated": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
    }
    data["last"] = name
    _save_projects(data)
    return {"saved": name, "message": f'אזכור שעבדנו על "{name}"'}


def tool_get_last_project(_args):
    """What were we doing last time?"""
    data = _load_projects()
    name = data.get("last")
    project = data["projects"].get(name) if name else None
    if not project:
        return {"has_project": False, "message": "עוד לא שמרנו פרויקט משותף"}
    return {"has_project": True, **project}


def _match_project(data, wanted):
    """Find a project by name, forgivingly.

    The model mangles Hebrew names when echoing them back, so an exact-match
    lookup fails on the very names it just read. Fall back to a loose match,
    then to the most recent project.
    """
    projects = data.get("projects", {})
    if not projects:
        return None
    wanted = str(wanted or "").strip()
    if wanted in projects:
        return wanted
    if wanted:
        norm = lambda s: "".join(ch for ch in s.lower() if ch.isalnum())
        target = norm(wanted)
        for key in projects:
            nk = norm(key)
            if target and (nk == target or target in nk or nk in target):
                return key
    return data.get("last") if data.get("last") in projects else next(iter(projects))


def tool_resume_project(args):
    """Reopen everything that project had going: apps, sites, Minecraft."""
    data = _load_projects()
    name = _match_project(data, args.get("name"))
    project = data["projects"].get(name) if name else None
    if not project:
        return {"error": "עוד לא שמרנו שום פרויקט"}

    opened = []
    for app in project.get("apps", []):
        result = tool_open_app({"app": app})
        if "opened" in result:
            opened.append(result["opened"])
    for url in project.get("urls", []):
        tool_open_url({"url": url})
        opened.append(url)

    mc = None
    if project.get("minecraft"):
        # don't block the conversation for a minute and a half
        mc = tool_mc_start_server({"wait": False})

    data["last"] = name
    _save_projects(data)
    return {
        "resumed": name,
        "description": project.get("description", ""),
        "notes": project.get("notes", ""),
        "opened": opened,
        "minecraft": mc,
        "last_worked": project.get("updated"),
    }


def tool_list_projects(_args):
    data = _load_projects()
    return {
        "last": data.get("last"),
        "projects": [
            {"name": p["name"], "description": p.get("description", ""), "updated": p.get("updated")}
            for p in data["projects"].values()
        ],
    }


def tool_add_note(args):
    text = str(args.get("text", "")).strip()
    if not text:
        return {"error": "אין טקסט לפתק"}
    line = datetime.datetime.now().strftime("%d/%m/%Y %H:%M") + " — " + text
    with open(NOTES_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return {"saved": text}


def tool_read_notes(_args):
    try:
        with open(NOTES_FILE, encoding="utf-8") as f:
            lines = f.read().strip().splitlines()
    except FileNotFoundError:
        lines = []
    if not lines:
        return {"notes": [], "message": "אין פתקים שמורים"}
    return {"notes": lines[-20:], "count": len(lines)}


def tool_clear_notes(_args):
    open(NOTES_FILE, "w", encoding="utf-8").close()
    return {"cleared": True}


VOLUME_KEYS = {"up": 175, "down": 174, "mute": 173, "unmute": 173}


def tool_volume(args):
    action = str(args.get("action", "")).lower().strip()
    if action not in VOLUME_KEYS:
        return {"error": "פעולה לא מוכרת. אפשרויות: up, down, mute, unmute"}
    presses = 1
    if action in ("up", "down"):
        try:
            presses = int(args.get("steps", 5))
        except (TypeError, ValueError):
            presses = 5
        presses = max(1, min(presses, 25))
    key = VOLUME_KEYS[action]
    ps("$w = New-Object -ComObject WScript.Shell; "
       f"1..{presses} | ForEach-Object {{ $w.SendKeys([char]{key}) }}")
    return {"volume": action, "steps": presses}


def tool_screenshot(_args):
    pics = os.path.join(os.path.expanduser("~"), "Pictures")
    os.makedirs(pics, exist_ok=True)
    fname = os.path.join(pics, "jarvis_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".png")
    ps("Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
       "$b = [System.Windows.Forms.SystemInformation]::VirtualScreen; "
       "$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height; "
       "$g = [System.Drawing.Graphics]::FromImage($bmp); "
       "$g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size); "
       f"$bmp.Save('{fname}'); $g.Dispose(); $bmp.Dispose()")
    if os.path.exists(fname):
        subprocess.Popen(["cmd", "/c", "start", "", fname])
        return {"saved": fname}
    return {"error": "צילום המסך נכשל"}


VISION_MODEL = os.environ.get("JARVIS_VISION", "qwen2.5vl:3b")


def capture_screen(scale=0.6):
    """Grab the screen to a temp PNG and return the path.

    Downscaled on purpose: a 2560px screenshot costs the vision model a lot of
    tokens for detail it does not need to answer "what am I looking at".
    """
    path = os.path.join(tempfile.gettempdir(), "jarvis_vision.png")
    ps(
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
        "$b = [System.Windows.Forms.SystemInformation]::VirtualScreen; "
        f"$w = [int]($b.Width * {scale}); $h = [int]($b.Height * {scale}); "
        "$full = New-Object System.Drawing.Bitmap $b.Width, $b.Height; "
        "$g = [System.Drawing.Graphics]::FromImage($full); "
        "$g.CopyFromScreen($b.Left, $b.Top, 0, 0, $full.Size); "
        "$small = New-Object System.Drawing.Bitmap $full, (New-Object System.Drawing.Size($w, $h)); "
        f"$small.Save('{path}'); "
        "$g.Dispose(); $full.Dispose(); $small.Dispose()"
    )
    return path if os.path.exists(path) else None


def tool_see_screen(args):
    """Look at the screen and answer a question about it."""
    import base64
    import urllib.request

    question = str(args.get("question", "")).strip() or \
        "Describe what is on this screen concisely. Mention any visible error messages."

    path = capture_screen()
    if not path:
        return {"error": "לא הצלחתי לצלם את המסך"}

    with open(path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("ascii")

    body = json.dumps({
        "model": VISION_MODEL,
        "prompt": question,
        "images": [image_b64],
        "stream": False,
        # Release the 2.9GB as soon as we're done. On a 6GB card the vision
        # model and the chat model cannot both stay resident, and squeezing
        # them together produced corrupted output ("@@@@@@").
        "keep_alive": 0,
        "options": {"temperature": 0.2, "num_ctx": 4096},
    }).encode("utf-8")

    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate", data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            out = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"error": f"מודל הראייה לא זמין ({e}). ודא ש-{VISION_MODEL} מותקן."}
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

    answer = (out.get("response") or "").strip()
    return {"saw": answer} if answer else {"error": "מודל הראייה לא החזיר תשובה"}


# Tools borrowed from Model Context Protocol servers, alongside the built-ins.
MCP = None


def start_mcp():
    global MCP
    try:
        from mcp_bridge import MCPRegistry
    except ImportError as e:
        print(f"MCP disabled ({e})")
        return
    try:
        MCP = MCPRegistry(BASE_DIR)
        status = MCP.start()
        for s in status["servers"]:
            state = s["error"] or f"{s['tools']} tools"
            print(f"  MCP {s['name']}: {state}")
        if status["total_tools"]:
            print(f"MCP ready: {status['total_tools']} extra tools")
    except Exception as e:
        print(f"MCP failed to start: {e}")
        MCP = None


def tool_mcp_status(_args):
    """Which MCP servers are connected and what they offer."""
    if not MCP:
        return {"enabled": False, "message": "MCP לא פעיל. ערוך את mcp.json והפעל מחדש."}
    status = MCP.status()
    return {"enabled": True, **status}


def tool_free_gpu(_args):
    """Unload every model from the graphics card.

    6GB does not fit the chat model and the vision model at once; when they
    collide the vision model starts emitting garbage. This clears the board.
    """
    import urllib.request
    freed = []
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=10) as r:
            loaded = json.loads(r.read()).get("models", [])
    except Exception as e:
        return {"error": f"לא הצלחתי לדבר עם Ollama: {e}"}

    for m in loaded:
        name = m.get("name")
        if not name:
            continue
        try:
            body = json.dumps({"model": name, "keep_alive": 0}).encode()
            req = urllib.request.Request(
                "http://127.0.0.1:11434/api/generate", data=body,
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=30).read()
            freed.append(f"{name} ({m.get('size_vram', 0) / 1e9:.1f}GB)")
        except Exception:
            pass

    used = ps("(nvidia-smi --query-gpu=memory.used --format=csv,noheader)") or "?"
    return {"freed": freed or "כלום לא היה טעון", "vram_now": used}


def tool_lock_computer(_args):
    subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
    return {"locking": True}


MC_BRIDGE = "http://127.0.0.1:8124"


def mc_call(route, payload=None):
    """Forward a request to the Minecraft bot bridge (bot.js)."""
    import urllib.request
    import urllib.error
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        MC_BRIDGE + "/" + route, data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.URLError:
        return {"error": "שרת המיינקראפט לא רץ. הפעל את mc-jarvis (start-minecraft.bat)."}
    except Exception as e:
        return {"error": str(e)}


def _find_mc_dir():
    """Locate mc-jarvis. When packaged, BASE_DIR is inside the app bundle, so
    fall back to the checkout next to this project."""
    candidates = [
        os.path.join(os.path.dirname(BASE_DIR), "mc-jarvis"),
        os.path.join(os.path.expanduser("~"), "OnedriveVilf", "OneDrive",
                     "Documents", "GitHub", "mc-jarvis"),
        os.environ.get("JARVIS_MC_DIR", ""),
    ]
    for path in candidates:
        if path and os.path.exists(os.path.join(path, "start-minecraft.bat")):
            return path
    return candidates[0]


MC_DIR = _find_mc_dir()


def _port_open(port, host="127.0.0.1"):
    import socket
    with socket.socket() as s:
        s.settimeout(0.6)
        return s.connect_ex((host, port)) == 0


def tool_mc_start_server(args=None):
    """Boot the Minecraft world and Jarvis's bot, so he can be told to play
    without anyone touching a terminal first.

    Pass wait=False to launch and return immediately — a chat turn should not
    block for the ~90s the world takes to come up.
    """
    import time
    args = args or {}
    if _port_open(25565) and _port_open(8124):
        return {"already_running": True, "message": "העולם והבוט כבר רצים"}

    bat = os.path.join(MC_DIR, "start-minecraft.bat")
    if not os.path.exists(bat):
        return {"error": f"לא מצאתי את {bat}"}

    subprocess.Popen(["cmd", "/c", "start", "", bat], cwd=MC_DIR)

    if args.get("wait") is False:
        return {"starting": True,
                "message": "מפעיל את העולם ברקע — ייקח בערך דקה וחצי עד שהבוט מחובר"}

    # the world takes a while to generate; the bot joins a few seconds later
    deadline = time.time() + 150
    while time.time() < deadline and not _port_open(25565):
        time.sleep(2)
    if not _port_open(25565):
        return {"error": "השרת לא עלה בזמן. בדוק את החלון שנפתח."}

    bot_deadline = time.time() + 90
    while time.time() < bot_deadline and not _port_open(8124):
        time.sleep(2)

    return {
        "world": "running on localhost:25565",
        "bot": "connected" if _port_open(8124) else "still starting",
        "message": "העולם מוכן. הצטרף מהמשחק: Multiplayer, Direct Connect, localhost",
    }


def tool_mc_stop_server(_args):
    """Save and shut the world down."""
    rcon = os.path.join(MC_DIR, "rcon.py")
    if os.path.exists(rcon) and _port_open(25575):
        subprocess.run(["python", rcon, "save-all", "stop"], cwd=MC_DIR,
                       capture_output=True, timeout=60)
        return {"stopped": True, "message": "העולם נשמר והשרת נסגר"}
    return {"error": "השרת לא רץ, או ש-RCON כבוי"}


def tool_mc_autopilot(args):
    """Let the bot survive on its own until told to stop."""
    on = args.get("on")
    if isinstance(on, str):
        on = on.strip().lower() not in ("false", "off", "no", "0", "stop")
    payload = {} if on is None else {"on": bool(on)}
    return mc_call("autopilot", payload)


def tool_mc_connect(args):
    return mc_call("connect", args)


def tool_mc_status(_args):
    return mc_call("status")


def tool_mc_do(args):
    """Accept flat params (what small models actually emit) or a nested args object."""
    args = args or {}
    nested = args.get("args") if isinstance(args.get("args"), dict) else {}
    action = args.get("action") or nested.get("action") or args.get("name")
    if not action:
        return {"error": "חסר שם פעולה. אפשריות: say, come, follow, stop, goto, "
                         "collect, craft, place, equip, attack, eat, look_around, inventory"}
    payload = {k: v for k, v in args.items()
               if k not in ("action", "args", "name") and v is not None}
    payload.update({k: v for k, v in nested.items() if k != "action" and v is not None})
    return mc_call("act", {"action": action, "args": payload})


def tool_mc_learn(args):
    steps = args.get("steps")
    if isinstance(steps, str):
        try:
            steps = json.loads(steps)
        except Exception:
            return {"error": "steps חייב להיות רשימה"}
    return mc_call("learn_skill", {
        "name": args.get("name"),
        "description": args.get("description", ""),
        "steps": steps,
    })


def tool_mc_teach(args):
    """Teach a skill from a plain-text recipe — far easier for a small model to
    emit than a nested JSON array. The bot parses the recipe (same code path the
    in-game chat agent uses).

    Recipe format: steps separated by ';', each "<action> [target] [count]".
    Example: "collect oak_log 3; craft oak_planks 4; craft stick 4"
    """
    return mc_call("teach_recipe", {
        "name": str(args.get("name", "")).strip(),
        "recipe": str(args.get("recipe", "")).strip(),
        "description": args.get("description", ""),
    })


def tool_mc_run_skill(args):
    return mc_call("run_skill", {"name": args.get("name"), "args": args.get("args") or {}})


def tool_mc_skills(_args):
    return mc_call("list_skills")


TOOLS = {
    "get_time": tool_get_time,
    "open_app": tool_open_app,
    "open_url": tool_open_url,
    "search_web": tool_search_web,
    "system_stats": tool_system_stats,
    "remember_fact": tool_remember_fact,
    "recall_facts": tool_recall_facts,
    "forget_fact": tool_forget_fact,
    "trace_stats": tool_trace_stats,
    "save_project": tool_save_project,
    "get_last_project": tool_get_last_project,
    "resume_project": tool_resume_project,
    "list_projects": tool_list_projects,
    "add_note": tool_add_note,
    "read_notes": tool_read_notes,
    "clear_notes": tool_clear_notes,
    "volume": tool_volume,
    "wake_word": tool_wake_word,
    "mcp_status": tool_mcp_status,
    "free_gpu": tool_free_gpu,
    "see_screen": tool_see_screen,
    "screenshot": tool_screenshot,
    "lock_computer": tool_lock_computer,
    "mc_autopilot": tool_mc_autopilot,
    "mc_start_server": tool_mc_start_server,
    "mc_stop_server": tool_mc_stop_server,
    "mc_connect": tool_mc_connect,
    "mc_status": tool_mc_status,
    "mc_do": tool_mc_do,
    "mc_learn": tool_mc_learn,
    "mc_teach": tool_mc_teach,
    "mc_run_skill": tool_mc_run_skill,
    "mc_skills": tool_mc_skills,
}



# ---------------------------------------------------------------- the gate
#
# Every one of these tools ran the instant the model named it. Thirty-two tools,
# no confirmation anywhere — and the thing choosing them is a 7B model running
# locally, which has already been caught in this project reporting actions it
# never performed. A model that invents a completed action is a model that can
# invent `clear_notes`.
#
# So: destructive, outward-facing and settings-changing tools stop here and ask.
# The check lives in the server rather than the page because the page is not the
# only thing that can reach this endpoint.
NEEDS_OK = {
    "clear_notes":     "למחוק את כל הפתקים",
    "forget_fact":     "למחוק משהו מהזיכרון ארוך הטווח",
    "lock_computer":   "לנעול את המחשב",
    "free_gpu":        "לשחרר את הזיכרון של הכרטיס המסך",
    "mc_stop_server":  "לכבות את שרת המיינקראפט",
    "volume":          "לשנות את עוצמת הקול של המערכת",
    "open_url":        "לפתוח כתובת בדפדפן",
    "open_app":        "להפעיל תוכנה",
    "screenshot":      "לצלם את המסך",
    "see_screen":      "לצלם את המסך ולשלוח אותו למודל",
    "mc_autopilot":    "להפעיל או לכבות את הטייס האוטומטי",
}

_pending = {}
_pending_lock = threading.Lock()
PENDING_TTL = 120          # a request you have not answered in two minutes is stale


def _fingerprint(name, args):
    """A token is good for one exact request, not for the tool in general."""
    blob = json.dumps({"n": name, "a": args}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def gate_check(name, args, token):
    """
    Returns None to let the call through, or a dict to send back instead.

    Approving one `open_app` does not pre-approve the next one: the token is
    tied to these arguments and is thrown away the moment it is spent.
    """
    if name not in NEEDS_OK:
        return None

    now = time.time()
    with _pending_lock:
        for t, (_, exp) in list(_pending.items()):
            if exp < now:
                _pending.pop(t, None)

        if token:
            entry = _pending.get(token)
            if entry and entry[0] == _fingerprint(name, args) and entry[1] >= now:
                _pending.pop(token, None)          # single use
                return None

        fresh = secrets.token_urlsafe(16)
        _pending[fresh] = (_fingerprint(name, args), now + PENDING_TTL)

    detail = ", ".join(f"{k}={v}" for k, v in (args or {}).items())
    return {
        "needs_confirmation": True,
        "token": fresh,
        "tool": name,
        "asks": NEEDS_OK[name] + (f" ({detail})" if detail else ""),
    }



# ------------------------------------------------------ letting the phone in
#
# The microphone is captured by the browser, not by Python, which means the page
# opened on a phone uses the *phone's* microphone. That is the whole trick: talk
# to Jarvis from anywhere in the house, no new hardware at all.
#
# It only needs the server to answer to something other than localhost — and the
# moment it does, everyone on the WiFi can reach a machine that locks screens and
# deletes notes. So opening up is opt-in and comes with a key.
LAN = os.environ.get("JARVIS_LAN", "") == "1"
LAN_KEY = os.environ.get("JARVIS_KEY", "") or secrets.token_hex(4)
BIND = "0.0.0.0" if LAN else "127.0.0.1"


def local_ip():
    """The address the phone should be pointed at."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))          # no packet is sent; this just picks a route
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def key_ok(handler):
    """Loopback is trusted; anything arriving over the network must carry the key."""
    if not LAN:
        return True
    if handler.client_address[0] in ("127.0.0.1", "::1"):
        return True
    given = handler.headers.get("X-Jarvis-Key", "")
    return secrets.compare_digest(given, LAN_KEY)



# ---------------------------------------------------------------- the orb
#
# The printed shell on the desk shows what Jarvis is doing, using the state the
# interface already knows: it listens, it thinks, it speaks, it waits. Those are
# the only four things it ever does, and `setOrb` in the page is called at each
# of them already — so nothing here has to guess.
#
# What goes over the wire is the state, not the sound. The board animates the
# breathing itself, which keeps the network out of the animation: a dropped
# packet costs a state change, not a stutter, and nobody watching can tell a
# generic breath from one that follows the syllables.
ORB_ADDR = os.environ.get("JARVIS_ORB", "")        # "192.168.1.42" or empty to disable
ORB_PORT = int(os.environ.get("JARVIS_ORB_PORT", "8124") or 8124)
ORB_STATES = {"idle", "listening", "thinking", "speaking"}

_orb_sock = None
_orb_last = None


def orb_send(state):
    """Fire a datagram at the orb. Never raises — the desk ornament being
    unplugged must not break a conversation."""
    global _orb_sock, _orb_last
    if not ORB_ADDR:
        return {"orb": "off"}
    state = state if state in ORB_STATES else "idle"
    if state == _orb_last:
        return {"orb": state, "sent": False}      # nothing changed; stay quiet
    try:
        import socket
        if _orb_sock is None:
            _orb_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _orb_sock.sendto(state.encode("ascii"), (ORB_ADDR, ORB_PORT))
        _orb_last = state
        return {"orb": state, "sent": True}
    except Exception as e:
        return {"orb": state, "sent": False, "error": str(e)}


_whisper = None
_whisper_lock = threading.Lock()


# "base" transcribes an English command in ~1.2s on CPU with the same accuracy
# as "small" here. Set JARVIS_WHISPER=small for better Hebrew, at ~2x the time.
# "base" transcribes an English command in ~1.2s on CPU with the same accuracy
# as "small" here. Set JARVIS_WHISPER=small for better Hebrew, at ~2x the time.
WHISPER_SIZE = os.environ.get("JARVIS_WHISPER", "base")


def _enable_cuda_libs():
    """Put the pip-installed cuBLAS/cuDNN DLLs where CTranslate2 can find them.

    Without this, loading a CUDA model raises "cublas64_12.dll is not found"
    and Whisper silently falls back to the CPU.
    """
    if not hasattr(os, "add_dll_directory"):
        return
    import importlib.util
    for pkg in ("nvidia.cublas", "nvidia.cudnn"):
        try:
            spec = importlib.util.find_spec(pkg)
            if not spec:
                continue
            # These are namespace packages: origin is None, so take the search path
            roots = list(spec.submodule_search_locations or [])
            if spec.origin:
                roots.append(os.path.dirname(spec.origin))
            for root in roots:
                bin_dir = os.path.join(root, "bin")
                if os.path.isdir(bin_dir):
                    os.add_dll_directory(bin_dir)
                    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
        except (ImportError, OSError, ValueError):
            pass


_enable_cuda_libs()


def get_whisper(force_cpu=False):
    """Load Whisper once, on first use, so startup stays instant.

    Runs entirely on this machine — unlike the browser's speech API, which
    ships your audio to Google.
    """
    global _whisper
    with _whisper_lock:
        if _whisper is None:
            from faster_whisper import WhisperModel
            if not force_cpu and os.environ.get("JARVIS_WHISPER_DEVICE") != "cpu":
                try:
                    # int8, not float16: this GTX 1660 has no tensor cores, and
                    # float16 measured 39.9s against 0.23s for int8 on the same
                    # clip. float16 is only the right default on newer cards.
                    _whisper = WhisperModel(WHISPER_SIZE, device="cuda", compute_type="int8")
                    return _whisper
                except Exception:
                    pass  # no usable CUDA runtime — CPU it is
            _whisper = WhisperModel(WHISPER_SIZE, device="cpu", compute_type="int8")
    return _whisper


def _run_whisper(model, path, language):
    segments, info = model.transcribe(path, language=language, beam_size=1, vad_filter=True)
    text = " ".join(s.text.strip() for s in segments).strip()
    return {"text": text, "language": info.language}


def transcribe(audio_bytes, language=None):
    global _whisper
    tmp = os.path.join(tempfile.gettempdir(), f"jarvis_stt_{os.getpid()}.webm")
    with open(tmp, "wb") as f:
        f.write(audio_bytes)
    try:
        try:
            return _run_whisper(get_whisper(), tmp, language)
        except Exception as e:
            # CUDA can load fine and then fail at inference (missing cuBLAS/cuDNN),
            # so retry once on the CPU before giving up.
            if not any(k in str(e).lower() for k in ("cuda", "cublas", "cudnn", "gpu")):
                raise
            with _whisper_lock:
                _whisper = None
            return _run_whisper(get_whisper(force_cpu=True), tmp, language)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        # serve the UI from ui/ while keeping tool routes on this same origin
        super().__init__(*args, directory=os.path.join(BASE_DIR, "ui"), **kwargs)

    def _send_json(self, obj, status=200):
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        # Guard the whole router. Guarding /tool alone still left /tts and /stt
        # open — someone on the WiFi could not have deleted a note, but could
        # have made the machine talk, and could have fed Whisper anything.
        if not key_ok(self):
            return self._send_json({"error": "unauthorised", "need_key": True}, 401)
        if self.path == "/stt":
            return self._handle_stt()
        if self.path == "/tts":
            return self._handle_tts()
        if self.path == "/mcp-tools":
            # The UI merges these into the tool list it sends the model.
            return self._send_json({"tools": MCP.tool_definitions() if MCP else []})
        if self.path == "/wake":
            # Electron polls this; report a detection at most once.
            import time
            fired = _wake_state["detected_at"] > 0 and (time.time() - _wake_state["detected_at"]) < 5
            if fired:
                _wake_state["detected_at"] = 0.0
            return self._send_json({
                "detected": fired,
                "listening": _wake_state["enabled"],
                "score": round(_wake_state["last_score"], 3),
                "error": _wake_state["error"],
            })
        if self.path == "/orb":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length)) if length else {}
                return self._send_json(orb_send(str(body.get("state", "idle"))))
            except Exception as e:
                return self._send_json({"error": str(e)}, 500)
        if self.path == "/trace":
            try:
                length = int(self.headers.get("Content-Length", 0))
                append_trace(json.loads(self.rfile.read(length)))
                return self._send_json({"ok": True})
            except Exception as e:
                return self._send_json({"error": str(e)}, 500)
        if self.path != "/tool":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            name = body.get("name", "")
            args = body.get("args") or {}
            hold = gate_check(name, args, body.get("confirm_token"))
            if hold is not None:
                return self._send_json(hold)
            fn = TOOLS.get(name)
            if fn is not None:
                result = fn(args)
            elif MCP and MCP.has(name):
                result = MCP.call(name, args)
            else:
                result = {"error": f"כלי לא מוכר: {name}"}
        except Exception as e:
            result = {"error": str(e)}
        self._send_json(result)

    def _handle_tts(self):
        """Speak a line in Jarvis's own voice, rendered locally."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            text = str(body.get("text", "")).strip()
            if not text:
                return self._send_json({"error": "no text"}, 400)
            audio = synthesize(text[:1200])
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(audio)))
            self.end_headers()
            self.wfile.write(audio)
        except (ImportError, FileNotFoundError) as e:
            self._send_json({"error": str(e)}, 503)   # UI falls back to browser speech
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_stt(self):
        """Transcribe a recorded audio clip locally."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not length:
                return self._send_json({"error": "no audio"}, 400)
            audio = self.rfile.read(length)
            lang = self.headers.get("X-Language") or None
            if lang in ("auto", ""):
                lang = None
            self._send_json(transcribe(audio, lang))
        except ImportError:
            self._send_json({"error": "faster-whisper לא מותקן. הרץ: pip install faster-whisper"}, 500)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def log_message(self, fmt, *args):
        pass  # keep the console quiet


if __name__ == "__main__":
    os.chdir(BASE_DIR)
    start_mcp()
    print(f"Jarvis running at http://localhost:{PORT}")
    if ORB_ADDR:
        print(f"  orb:             {ORB_ADDR}:{ORB_PORT}")
    if LAN:
        print(f"  on the network:  http://{local_ip()}:{PORT}")
        print(f"  access key:      {LAN_KEY}")
        print("  open that address on your phone and paste the key once.")
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()
