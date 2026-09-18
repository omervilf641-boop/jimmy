"""
Jimmy as an app: a tiny local web UI, opened in your browser.

Standard library only - http.server and a single HTML page. No Electron, no web
framework, no build step. It binds to 127.0.0.1 so nothing outside your machine
can reach it, and every request must carry a token minted at startup, because
any web page you have open can otherwise talk to a plain localhost server.
"""

from __future__ import annotations

import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from . import config
from .agent import Jimmy

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Jimmy</title>
<style>
  :root {
    --bg: #f6f6f4; --panel: #fff; --ink: #1c1c1a; --muted: #6b6b66;
    --line: #e3e3de; --me: #2f6f4e; --me-ink: #fff; --accent: #2f6f4e;
    --warn: #8a5a00; --warn-bg: #fdf3e0;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #17171a; --panel: #1f1f23; --ink: #ececea; --muted: #9a9a94;
      --line: #32323a; --me: #3d8a63; --me-ink: #fff; --accent: #6fbf94;
      --warn: #f0c070; --warn-bg: #3a2f18;
    }
  }
  :root[data-theme="dark"] {
    --bg: #17171a; --panel: #1f1f23; --ink: #ececea; --muted: #9a9a94;
    --line: #32323a; --me: #3d8a63; --me-ink: #fff; --accent: #6fbf94;
    --warn: #f0c070; --warn-bg: #3a2f18;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--ink);
    font: 15px/1.55 ui-sans-serif, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
    display: flex; flex-direction: column; height: 100dvh;
  }
  header {
    background: var(--panel); border-bottom: 1px solid var(--line);
    padding: 12px 16px; display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  }
  h1 { font-size: 17px; margin: 0; font-weight: 650; letter-spacing: -0.01em; }
  .status { display: flex; gap: 14px; flex-wrap: wrap; font-size: 12.5px; color: var(--muted); }
  .status b { font-weight: 550; color: var(--ink); }
  .spacer { flex: 1 1 auto; }
  button {
    font: inherit; font-size: 13px; padding: 6px 12px; border-radius: 8px;
    border: 1px solid var(--line); background: var(--panel); color: var(--ink); cursor: pointer;
  }
  button:hover { border-color: var(--accent); }
  button.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
  #log { flex: 1 1 auto; overflow-y: auto; padding: 20px 16px; display: flex; flex-direction: column; gap: 14px; }
  .turn { max-width: min(680px, 92%); }
  .turn.me { align-self: flex-end; }
  .who { font-size: 11.5px; color: var(--muted); margin-bottom: 4px; }
  .turn.me .who { text-align: end; }
  .bubble {
    background: var(--panel); border: 1px solid var(--line); border-radius: 14px;
    padding: 11px 14px; white-space: pre-wrap; overflow-wrap: anywhere;
  }
  .turn.me .bubble { background: var(--me); color: var(--me-ink); border-color: transparent; }
  .tool { font-size: 12.5px; color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  .notice { background: var(--warn-bg); color: var(--warn); border: 1px solid var(--line);
            border-radius: 12px; padding: 12px 14px; max-width: min(680px, 92%); font-size: 14px; }
  .notice a { color: inherit; }
  form { display: flex; gap: 10px; padding: 14px 16px; border-top: 1px solid var(--line); background: var(--panel); }
  input[type=text], input[type=password] {
    flex: 1 1 auto; font: inherit; padding: 11px 14px; border-radius: 10px;
    border: 1px solid var(--line); background: var(--bg); color: var(--ink);
  }
  input:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
  dialog {
    border: 1px solid var(--line); border-radius: 14px; background: var(--panel);
    color: var(--ink); padding: 20px; max-width: 460px; width: calc(100% - 32px);
  }
  dialog::backdrop { background: rgba(0,0,0,.45); }
  dialog h2 { margin: 0 0 6px; font-size: 16px; }
  dialog p { color: var(--muted); font-size: 13.5px; margin: 0 0 14px; }
  .row { display: flex; gap: 8px; margin-top: 14px; justify-content: flex-end; }
  code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12.5px; }
  /* Hebrew and other RTL text reads correctly without flipping the whole app. */
  .bubble, .notice { unicode-bidi: plaintext; text-align: start; }
</style>
</head>
<body>
<header>
  <h1>🤖 Jimmy</h1>
  <div class="status" id="status"></div>
  <div class="spacer"></div>
  <button id="keyBtn">API key</button>
  <button id="voiceBtn">🔇 Voice</button>
</header>

<div id="log"></div>

<form id="form">
  <input type="text" id="input" placeholder="Say something to Jimmy..." autocomplete="off" autofocus>
  <button class="primary" type="submit">Send</button>
</form>

<dialog id="keyDialog">
  <h2>Anthropic API key</h2>
  <p>Stored in <code id="cfgPath"></code>, readable only by you. Jimmy works without one,
     but only in offline mode.</p>
  <input type="password" id="keyInput" placeholder="sk-ant-..." autocomplete="off">
  <div class="row">
    <button id="keyCancel" type="button">Cancel</button>
    <button id="keySave" class="primary" type="button">Save</button>
  </div>
</dialog>

<script>
const TOKEN = new URLSearchParams(location.search).get("t") || "";
const log = document.getElementById("log");
let busy = false;

function add(cls, who, text) {
  const turn = document.createElement("div");
  turn.className = "turn " + cls;
  if (who) {
    const label = document.createElement("div");
    label.className = "who";
    label.textContent = who;
    turn.appendChild(label);
  }
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  turn.appendChild(bubble);
  log.appendChild(turn);
  log.scrollTop = log.scrollHeight;
  return bubble;
}

function notice(html) {
  const el = document.createElement("div");
  el.className = "notice";
  el.innerHTML = html;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
}

async function api(path, body) {
  const res = await fetch(path + "?t=" + encodeURIComponent(TOKEN), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) throw new Error("Jimmy returned " + res.status);
  return res.json();
}

function renderStatus(s) {
  document.getElementById("status").innerHTML =
    `<span><b>Brain</b> ${s.brain}</span>` +
    `<span><b>Tools</b> ${s.tools}</span>` +
    `<span><b>Memory</b> ${s.facts} facts &middot; ${s.skills} skills &middot; ${s.score}/100</span>`;
  const vb = document.getElementById("voiceBtn");
  vb.textContent = s.voice_on ? "🔊 Voice on" : "🔇 Voice";
  vb.disabled = !s.voice_available;
  vb.title = s.voice_available ? "" : s.voice_detail;
}

async function send(text) {
  if (busy || !text.trim()) return;
  busy = true;
  add("me", "You", text);
  const bubble = add("them", "Jimmy", "...");
  try {
    const out = await api("/api/chat", {message: text});
    (out.tools || []).forEach(t => {
      const el = document.createElement("div");
      el.className = "turn them tool";
      el.textContent = "🔧 " + t;
      log.insertBefore(el, bubble.parentElement);
    });
    bubble.textContent = out.reply;
    renderStatus(out.status);
    if (out.exit) {
      document.getElementById("input").disabled = true;
      notice("Session ended. Everything is saved — close this tab.");
    }
  } catch (err) {
    bubble.textContent = "⚠️ " + err.message;
  } finally {
    busy = false;
    log.scrollTop = log.scrollHeight;
    document.getElementById("input").focus();
  }
}

document.getElementById("form").addEventListener("submit", e => {
  e.preventDefault();
  const input = document.getElementById("input");
  const text = input.value;
  input.value = "";
  send(text);
});

document.getElementById("voiceBtn").addEventListener("click", async () => {
  const out = await api("/api/chat", {message: "voice"});
  send(out.reply.includes("on") && !out.reply.includes("off") ? "voice off" : "voice on");
});

const dialog = document.getElementById("keyDialog");
document.getElementById("keyBtn").addEventListener("click", () => dialog.showModal());
document.getElementById("keyCancel").addEventListener("click", () => dialog.close());
document.getElementById("keySave").addEventListener("click", async () => {
  const value = document.getElementById("keyInput").value;
  const out = await api("/api/key", {key: value});
  dialog.close();
  document.getElementById("keyInput").value = "";
  renderStatus(out.status);
  notice(out.message);
});

(async () => {
  const out = await api("/api/hello", {});
  document.getElementById("cfgPath").textContent = out.config_path;
  renderStatus(out.status);
  add("them", "Jimmy", out.greeting);
  if (!out.status.online) {
    notice('No API key yet, so Jimmy is in <b>offline mode</b> — he remembers and learns, ' +
           'but he will not reason. Get a key at ' +
           '<a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noopener">' +
           'console.anthropic.com</a>, then click <b>API key</b> above.');
  }
})();
</script>
</body>
</html>
"""


class JimmyApp:
    """Serves the page and a small JSON API over one Jimmy instance."""

    def __init__(self, jimmy: Jimmy) -> None:
        self.jimmy = jimmy
        self.token = secrets.token_urlsafe(24)
        self._lock = threading.Lock()

    # -- state -----------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        stats = self.jimmy.engine.get_learning_stats()
        brain = self.jimmy.brain
        voice = self.jimmy.voice
        return {
            "online": brain.online,
            "brain": brain.model if brain.online else f"offline ({brain.offline_reason})",
            "tools": "on" if (self.jimmy.toolbox and brain.online) else "off",
            "facts": stats["facts_learned"],
            "skills": stats["skills_acquired"],
            "score": stats["learning_score"],
            "voice_on": voice.enabled and voice.available,
            "voice_available": voice.available,
            "voice_detail": voice.status_line(),
        }

    # -- endpoints -------------------------------------------------------

    def hello(self, _: Dict[str, Any]) -> Dict[str, Any]:
        stats = self.jimmy.engine.get_learning_stats()
        who = f", {stats['user_name']}" if stats["user_name"] else ""
        if stats["total_conversations"]:
            greeting = (
                f"Hi again{who}! We've talked {stats['total_conversations']} times. "
                "Pick up wherever you like."
            )
        else:
            greeting = (
                "Hi! I'm Jimmy. I learn from our conversations and remember them. "
                "Tell me your name, or type `help` to see what I understand."
            )
        return {
            "greeting": greeting,
            "status": self.status(),
            "config_path": str(config.config_path()),
        }

    def chat(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        message = str(payload.get("message", ""))
        tools: list = []
        with self._lock:  # one conversation at a time - the memory file is shared
            reply = self.jimmy.chat(message, on_tool=tools.append)
        return {
            "reply": reply or "",
            "tools": tools,
            "exit": message.strip().lower() in {"exit", "quit", "bye"},
            "status": self.status(),
        }

    def set_key(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        key = str(payload.get("key", "")).strip()
        if key and not key.startswith("sk-ant-"):
            return {
                "message": "⚠️ That doesn't look like an Anthropic key - they start with <code>sk-ant-</code>. Nothing was saved.",
                "status": self.status(),
            }

        path = config.set_api_key(key)
        self.jimmy.brain = type(self.jimmy.brain)()  # rebuild against the new key
        if not key:
            return {"message": f"Key removed from {path}. Jimmy is offline now.",
                    "status": self.status()}

        ok, detail = self.jimmy.brain.verify()
        if ok:
            message = f"✅ Key saved and verified — {detail}. Ask him something real."
        elif ok is None:
            message = f"Key saved to {path}, but {detail}."
        else:
            # A bad key is worse than none: it would fail on every message.
            config.set_api_key("")
            self.jimmy.brain = type(self.jimmy.brain)()
            message = (
                f"❌ {detail.capitalize()}, so it was not kept. "
                'Check it at <a href="https://console.anthropic.com/settings/keys" '
                'target="_blank" rel="noopener">console.anthropic.com</a>.'
            )
        return {"message": message, "status": self.status()}


def _handler(app: JimmyApp):
    routes = {"/api/hello": app.hello, "/api/chat": app.chat, "/api/key": app.set_key}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:
            pass  # the terminal belongs to Jimmy, not to access logs

        def _authorized(self) -> bool:
            token = parse_qs(urlparse(self.path).query).get("t", [""])[0]
            return secrets.compare_digest(token, app.token)

        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if urlparse(self.path).path != "/":
                self._send(404, b"not found", "text/plain; charset=utf-8")
                return
            if not self._authorized():
                self._send(403, b"Open the link Jimmy printed in the terminal.",
                           "text/plain; charset=utf-8")
                return
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")

        def do_POST(self) -> None:
            route = routes.get(urlparse(self.path).path)
            if route is None:
                self._send(404, b"{}", "application/json")
                return
            if not self._authorized():
                self._send(403, b'{"error":"bad token"}', "application/json")
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length) or b"{}")
                result = route(payload if isinstance(payload, dict) else {})
                body = json.dumps(result).encode("utf-8")
            except (ValueError, TypeError, KeyError) as exc:
                body = json.dumps({"error": str(exc)}).encode("utf-8")
                self._send(400, body, "application/json")
                return
            except Exception as exc:  # noqa: BLE001 - never kill the server on one bad turn
                body = json.dumps({"error": f"{type(exc).__name__}: {exc}"}).encode("utf-8")
                self._send(500, body, "application/json")
                return
            self._send(200, body, "application/json")

    return Handler


def serve(jimmy: Jimmy, port: int = 0, open_browser: bool = True) -> ThreadingHTTPServer:
    """Start the app. Port 0 picks a free one."""
    app = JimmyApp(jimmy)
    server = ThreadingHTTPServer(("127.0.0.1", port), _handler(app))
    server.jimmy_url = f"http://127.0.0.1:{server.server_address[1]}/?t={app.token}"  # type: ignore[attr-defined]
    server.jimmy_app = app  # type: ignore[attr-defined]

    # Default poll interval is 0.5s, which is how long shutdown() then blocks.
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()

    if open_browser:
        try:
            webbrowser.open(server.jimmy_url)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - headless machines have no browser
            pass
    return server


def run(jimmy: Jimmy, port: int = 0, open_browser: bool = True) -> int:
    """Run the app until Ctrl-C."""
    server = serve(jimmy, port=port, open_browser=open_browser)
    url = server.jimmy_url  # type: ignore[attr-defined]
    print("\n🤖 Jimmy is running as an app.\n")
    print(f"   {url}\n")
    print(f"   Memory: {jimmy.engine.memory_file}")
    print("   Press Ctrl-C to stop.\n")
    if not open_browser:
        print("   (Open that link yourself - it carries the access token.)\n")
    try:
        while True:
            import time

            time.sleep(3600)
    except KeyboardInterrupt:
        print("\n👋 Stopped. Everything is saved.\n")
    finally:
        server.shutdown()
        server.server_close()  # shutdown() stops serving; this releases the port
    return 0
