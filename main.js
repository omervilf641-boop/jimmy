/**
 * Jarvis desktop shell.
 *
 * Wraps the web UI in a real app so it can do what a browser tab cannot:
 * a global hotkey that reaches you inside fullscreen games, a tray icon,
 * an always-on-top overlay, and starting with Windows.
 *
 * The Python tool server (server.py) runs as a child process — it owns all the
 * PC actions (apps, notes, timers, Minecraft bridge) and keeps working unchanged.
 */
const { app, BrowserWindow, Tray, Menu, globalShortcut, ipcMain, shell, nativeImage, screen, clipboard, Notification } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const http = require("http");

const TOOL_PORT = 8123;
const HOTKEY = "Control+Shift+J";
const OVERLAY_HOTKEY = "Control+Shift+O";
const DICTATE_HOTKEY = "Control+Shift+D";

let win = null;
let tray = null;
let toolServer = null;
let overlayMode = false;

/* ---------------- icon ---------------- */
// Drawn in code so the app carries no binary asset around.
function makeIcon(size = 64) {
  const zlib = require("zlib");
  const px = Buffer.alloc(size * size * 4);
  const c = (size - 1) / 2;
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const d = Math.hypot(x - c, y - c) / c;
      const i = (y * size + x) * 4;
      if (d > 1) continue;
      const core = Math.max(0, 1 - d * 1.9);       // bright centre
      const ring = d > 0.72 && d < 0.97 ? 1 : 0;   // outer ring
      const a = Math.min(1, core + ring * 0.95 + Math.max(0, 0.45 - d * 0.45));
      px[i] = Math.round(40 + 200 * core);
      px[i + 1] = Math.round(190 + 60 * core);
      px[i + 2] = 255;
      px[i + 3] = Math.round(a * 255);
    }
  }
  // raw scanlines -> zlib -> PNG chunks
  const raw = Buffer.alloc((size * 4 + 1) * size);
  for (let y = 0; y < size; y++) {
    raw[y * (size * 4 + 1)] = 0;
    px.copy(raw, y * (size * 4 + 1) + 1, y * size * 4, (y + 1) * size * 4);
  }
  const crcTable = [];
  for (let n = 0; n < 256; n++) {
    let c2 = n;
    for (let k = 0; k < 8; k++) c2 = c2 & 1 ? 0xedb88320 ^ (c2 >>> 1) : c2 >>> 1;
    crcTable[n] = c2 >>> 0;
  }
  const crc = (buf) => {
    let c2 = 0xffffffff;
    for (const b of buf) c2 = crcTable[(c2 ^ b) & 0xff] ^ (c2 >>> 8);
    return (c2 ^ 0xffffffff) >>> 0;
  };
  const chunk = (type, data) => {
    const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
    const td = Buffer.concat([Buffer.from(type, "ascii"), data]);
    const cr = Buffer.alloc(4); cr.writeUInt32BE(crc(td));
    return Buffer.concat([len, td, cr]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0); ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; ihdr[9] = 6; // 8-bit RGBA
  const png = Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", zlib.deflateSync(raw)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
  return nativeImage.createFromBuffer(png);
}

/* ---------------- tool server ---------------- */
function serverScriptPath() {
  const packed = path.join(process.resourcesPath || "", "server.py");
  return app.isPackaged && fs.existsSync(packed) ? packed : path.join(__dirname, "server.py");
}

function startToolServer() {
  const script = serverScriptPath();
  if (!fs.existsSync(script)) return;
  for (const cmd of ["python", "py", "python3"]) {
    try {
      toolServer = spawn(cmd, [script], { cwd: path.dirname(script), windowsHide: true });
      toolServer.on("error", () => { toolServer = null; });
      return;
    } catch { /* try the next interpreter */ }
  }
}

// Forty quarter-seconds was ten seconds, and a cold start does not fit in it.
// Measured on this machine: 5.1s warm, 12s the first time after a reboot, with
// Python not yet in the file cache and the MCP server spawning alongside. The
// window opened on nothing and stayed that way.
function waitForServer(tries = 120) {
  return new Promise((resolve) => {
    const attempt = (left) => {
      const req = http.get({ host: "127.0.0.1", port: TOOL_PORT, path: "/", timeout: 500 }, (res) => {
        res.destroy(); resolve(true);
      });
      req.on("error", () => (left > 0 ? setTimeout(() => attempt(left - 1), 250) : resolve(false)));
      req.on("timeout", () => { req.destroy(); left > 0 ? setTimeout(() => attempt(left - 1), 250) : resolve(false); });
    };
    attempt(tries);
  });
}

/**
 * The screen to show instead of a black rectangle.
 *
 * Written inline rather than as a file because the whole problem is that we
 * could not load a file from the server, and a fallback that needs the thing
 * that is broken is not a fallback.
 */
function showStartupTrouble(reason) {
  if (!win || win.isDestroyed()) return;
  const page = `<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
  <style>
    body { margin:0; height:100vh; display:flex; align-items:center; justify-content:center;
           background:#04070d; color:#cfe6ee;
           font-family: "Segoe UI", system-ui, sans-serif; }
    .box { max-width: 30rem; padding: 0 1.6rem; line-height: 1.65; }
    h1 { font-size: 1.15rem; margin: 0 0 .7rem; color:#4ff0ae; letter-spacing:.04em; }
    p { margin: 0 0 .8rem; color:#8ea6b4; font-size:.92rem; }
    code { background:#0d1620; padding:.15rem .45rem; border-radius:3px; color:#cfe6ee;
           direction:ltr; display:inline-block; font-size:.86rem; }
    button { margin-top:.6rem; font:inherit; font-size:.9rem; color:#04070d; background:#4ff0ae;
             border:0; border-radius:4px; padding:.55rem 1.1rem; cursor:pointer; }
    .why { color:#5c6f7c; font-size:.8rem; margin-top:1.2rem; }
  </style></head><body><div class="box">
    <h1>ג'רוויס לא הצליח לעלות</h1>
    <p>שרת הכלים לא ענה, אז אין מה להציג. זה כמעט תמיד אחד משניים:
       פייתון לא מותקן או לא ב־PATH, או שמשהו אחר כבר תופס את הפורט 8123.</p>
    <p>לבדוק מהטרמינל, מתוך תיקיית הפרויקט:</p>
    <p><code>python server.py</code></p>
    <p>מה שייכתב שם יגיד מה חסר. כשהוא רץ — לחץ כאן:</p>
    <button onclick="location.href='http://127.0.0.1:8123/'">נסה שוב</button>
    <p class="why">${String(reason || "").replace(/[<>&]/g, "")}</p>
  </div></body></html>`;
  win.loadURL("data:text/html;charset=utf-8," + encodeURIComponent(page));
}

/* ---------------- window ---------------- */
function createWindow(serverUp = true) {
  win = new BrowserWindow({
    width: 480, height: 780,
    minWidth: 380, minHeight: 520,
    show: false,
    frame: false,
    backgroundColor: "#04070d",
    icon: makeIcon(256),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  win.loadURL(`http://127.0.0.1:${TOOL_PORT}/`);
  win.once("ready-to-show", () => win.show());

  // A window that fails to load must not just sit there being black.
  //
  // backgroundColor is #04070d, so a failed load is a near-black rectangle with
  // nothing in it and no way to tell whether the app is starting, broken, or
  // waiting for something. There was no handler here at all: one failed load
  // and that was the session. Now it keeps trying, and if it really cannot
  // reach the server it says so on the screen instead of implying it.
  let reloads = 0;
  win.webContents.on("did-fail-load", (_e, code, desc, url, isMainFrame) => {
    if (!isMainFrame || code === -3) return;          // -3 is an aborted nav, not a failure
    if (++reloads <= 20) {
      setTimeout(() => { if (!win.isDestroyed()) win.loadURL(`http://127.0.0.1:${TOOL_PORT}/`); }, 1000);
      return;
    }
    showStartupTrouble(desc);
  });

  if (serverUp === false) {
    // waitForServer gave up before the window was even made. Say so now rather
    // than leaving the retries to discover it silently.
    setTimeout(() => { if (!win.isDestroyed() && reloads > 3) showStartupTrouble("the tool server did not come up"); }, 8000);
  }

  if (process.argv.includes("--selftest")) {
    win.webContents.on("console-message", (_e, _lvl, msg) => console.log("[renderer]", msg));
    win.webContents.on("did-finish-load", async () => {
      // Does speech recognition merely exist, or does it actually run?
      // Electron builds often lack Google's speech key and fail with "network".
      const report = await win.webContents.executeJavaScript(`(async () => {
        const mics = (await navigator.mediaDevices.enumerateDevices())
          .filter(d => d.kind === "audioinput").length;
        const voices = await new Promise(res => {
          const v = speechSynthesis.getVoices();
          if (v.length) return res(v);
          speechSynthesis.onvoiceschanged = () => res(speechSynthesis.getVoices());
          setTimeout(() => res(speechSynthesis.getVoices()), 2500);
        });
        const stt = await new Promise(res => {
          const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
          if (!SR) return res({ ok: false, error: "no-constructor" });
          const r = new SR(); r.lang = "en-US";
          let done = false;
          const finish = o => { if (!done) { done = true; try { r.stop(); } catch {} res(o); } };
          let opened = false;
          r.onaudiostart = () => { opened = true; };
          r.onresult = () => finish({ ok: true, via: "transcribed speech" });
          // "no-speech" proves the whole pipeline ran and simply heard silence;
          // "network" means the transcription backend is unreachable.
          r.onerror = e => finish({
            ok: e.error === "no-speech" || e.error === "aborted",
            micOpened: opened, error: e.error,
          });
          r.onend = () => finish({ ok: opened, micOpened: opened, error: "ended-after-silence" });
          try { r.start(); } catch (e) { finish({ ok: false, error: "throw:" + e.message }); }
          setTimeout(() => finish({ ok: false, micOpened: opened, error: "timeout" }), 20000);
        });
        // confirm the app wired itself to local Whisper and the route answers
        let sttRoute = "unknown";
        try {
          const r = await fetch("/stt", { method: "POST", body: new Blob([new Uint8Array(10)]) });
          sttRoute = "responded " + r.status;
        } catch (e) { sttRoute = "unreachable: " + e.message; }

        return {
          desktopBridge: !!window.jarvisDesktop,
          usingLocalWhisper: typeof USE_LOCAL_STT !== "undefined" ? USE_LOCAL_STT : "n/a",
          micButtonEnabled: !document.getElementById("mic-btn").disabled,
          sttRoute,
          microphones: mics,
          voiceCount: voices.length,
          englishVoice: voices.filter(v => v.lang.startsWith("en")).map(v => v.name).slice(0, 3),
          hebrewVoice: voices.filter(v => v.lang.startsWith("he")).map(v => v.name),
          speechToText: stt,
        };
      })()`);
      console.log("[selftest]", JSON.stringify(report));
    });
  }

  // Microphone: the shell grants it once so there is no prompt every launch.
  win.webContents.session.setPermissionRequestHandler((_wc, permission, callback) => {
    callback(["media", "audioCapture", "notifications"].includes(permission));
  });

  win.on("close", (e) => {
    if (!app.isQuitting) { e.preventDefault(); win.hide(); } // keep living in the tray
  });

  // External links open in the real browser, never inside the app shell.
  win.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: "deny" }; });
}

/* ---------------- overlay mode ---------------- */
// A small always-on-top panel, so Jarvis is usable over a fullscreen game.
function setOverlay(on) {
  if (!win) return;
  overlayMode = on;
  if (on) {
    const { width } = screen.getPrimaryDisplay().workAreaSize;
    win.setAlwaysOnTop(true, "screen-saver");
    win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
    win.setSize(380, 460);
    win.setPosition(width - 400, 40);
  } else {
    win.setAlwaysOnTop(false);
    win.setVisibleOnAllWorkspaces(false);
    win.setSize(480, 780);
    win.center();
  }
  win.webContents.send("overlay-changed", on);
  if (tray) tray.setContextMenu(buildTrayMenu());
}

/* ---------------- dictation anywhere ---------------- */
/**
 * Press the hotkey in any app, speak, and the transcript is typed where your
 * cursor already is. The window never takes focus, so the target app keeps it;
 * the text is delivered through the clipboard and a synthetic paste.
 */
let dictating = false;

function toast(body, title = "Jarvis") {
  try {
    if (Notification.isSupported()) new Notification({ title, body, silent: true }).show();
  } catch { /* notifications are a nicety, never a requirement */ }
}

function startDictation() {
  if (!win) return;
  if (dictating) { win.webContents.send("stop-dictation"); return; }
  dictating = true;
  win.webContents.send("start-dictation");   // deliberately does NOT show the window
  toast("Listening… speak now, then pause.");
}

function typerScriptPath() {
  const packed = path.join(process.resourcesPath || "", "type_text.ps1");
  return app.isPackaged && fs.existsSync(packed) ? packed : path.join(__dirname, "type_text.ps1");
}

// Injects the characters straight into the focused window via SendInput.
// SendKeys was tried first and proved unusable: a Ctrl+V arrived as a bare "v",
// and it cannot type Hebrew at all.
function typeText(text) {
  const script = typerScriptPath();
  if (!fs.existsSync(script)) return toast("Missing type_text.ps1 — cannot type.");
  spawn("powershell",
    ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
     "-File", script, "-Text", text],
    { windowsHide: true });
}

/* ---------------- wake word ---------------- */
/**
 * Detection happens in the Python server on a dedicated model; the shell just
 * asks whether it fired. Polling beats a socket here — one tiny local request
 * a second, and nothing to reconnect when the server restarts.
 */
let wakeEnabled = false;
let wakePoll = null;

function postJson(path, payload) {
  return new Promise((resolve) => {
    const body = JSON.stringify(payload || {});
    const req = http.request(
      { host: "127.0.0.1", port: TOOL_PORT, path, method: "POST", timeout: 4000,
        headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) } },
      (res) => {
        let data = "";
        res.on("data", (c) => (data += c));
        res.on("end", () => { try { resolve(JSON.parse(data)); } catch { resolve(null); } });
      });
    req.on("error", () => resolve(null));
    req.on("timeout", () => { req.destroy(); resolve(null); });
    req.end(body);
  });
}

async function setWakeWord(on) {
  const res = await postJson("/tool", { name: "wake_word", args: { on } });
  if (on && res && res.error) {
    toast("Wake word unavailable: " + res.error);
    wakeEnabled = false;
  } else {
    wakeEnabled = !!on;
    toast(on ? 'Listening for "Hey Jarvis".' : "Wake word off.");
  }

  if (wakePoll) { clearInterval(wakePoll); wakePoll = null; }
  if (wakeEnabled) {
    wakePoll = setInterval(async () => {
      const s = await postJson("/wake", {});
      if (s && s.detected) showAndListen(true);
      if (s && !s.listening && s.error) {   // the listener died; stop pretending
        wakeEnabled = false;
        clearInterval(wakePoll); wakePoll = null;
        if (tray) tray.setContextMenu(buildTrayMenu());
      }
    }, 900);
  }
  if (tray) tray.setContextMenu(buildTrayMenu());
  return wakeEnabled;
}

/* ---------------- tray ---------------- */
function buildTrayMenu() {
  return Menu.buildFromTemplate([
    { label: "Show Jarvis", click: () => showAndListen(false) },
    { label: "Talk to Jarvis\t" + HOTKEY, click: () => showAndListen(true) },
    { label: "Dictate into any app\t" + DICTATE_HOTKEY, click: startDictation },
    { type: "separator" },
    { label: 'Wake word — "Hey Jarvis"', type: "checkbox", checked: wakeEnabled,
      click: (i) => setWakeWord(i.checked) },
    { type: "separator" },
    { label: "Overlay mode (over games)", type: "checkbox", checked: overlayMode, click: (i) => setOverlay(i.checked) },
    {
      label: "Start with Windows", type: "checkbox",
      checked: app.getLoginItemSettings().openAtLogin,
      click: (i) => app.setLoginItemSettings({ openAtLogin: i.checked, args: ["--hidden"] }),
    },
    { type: "separator" },
    { label: "Quit", click: () => { app.isQuitting = true; app.quit(); } },
  ]);
}

function showAndListen(listen) {
  if (!win) return;
  if (!win.isVisible()) win.show();
  win.focus();
  if (listen) win.webContents.send("start-listening");
}

/* ---------------- lifecycle ---------------- */
// A window that draws everything and shows nothing.
//
// Electron hands the finished frame to Windows through the GPU compositor, and
// when that link is broken — a driver update is the usual cause — the window
// presents as a flat rectangle of backgroundColor while the renderer is happily
// drawing the whole interface behind it. Diagnosed exactly that way here:
// capturePage() came back with the HUD in it and fifty distinct colours, while
// the screen showed nothing at all.
//
// Software compositing costs this app nothing worth measuring — it is a small
// HUD with a CSS-animated ring, not a game — so the switch is cheap insurance.
// It has to be thrown before the app is ready, which is why it cannot be
// decided from getGPUFeatureStatus(): by the time that answers, it is too late.
if (process.argv.includes("--no-gpu") || process.env.JARVIS_NO_GPU === "1") {
  app.disableHardwareAcceleration();
  console.log("[jarvis] hardware acceleration off");
}

const singleInstance = app.requestSingleInstanceLock();
if (!singleInstance) {
  app.quit();
} else {
  app.on("second-instance", () => showAndListen(false));

  app.whenReady().then(async () => {
    startToolServer();
    const serverUp = await waitForServer();
    createWindow(serverUp);

    tray = new Tray(makeIcon(32));
    tray.setToolTip("Jarvis");
    tray.setContextMenu(buildTrayMenu());
    tray.on("click", () => (win.isVisible() ? win.hide() : showAndListen(false)));

    // The point of the desktop app: reach Jarvis from inside a fullscreen game.
    globalShortcut.register(HOTKEY, () => showAndListen(true));
    globalShortcut.register(OVERLAY_HOTKEY, () => setOverlay(!overlayMode));
    globalShortcut.register(DICTATE_HOTKEY, startDictation);

    if (process.argv.includes("--hidden")) win.hide();
  });

  ipcMain.on("dictation-result", (_e, payload) => {
    dictating = false;
    const text = (payload && payload.text || "").trim();
    if (payload && payload.error) return toast("Dictation failed: " + payload.error);
    if (!text) return toast("I didn't catch anything.");
    typeText(text);
    toast("Typed: " + (text.length > 60 ? text.slice(0, 60) + "…" : text));
  });

  ipcMain.handle("window-action", (_e, action) => {
    if (!win) return;
    if (action === "minimize") win.minimize();
    else if (action === "close") win.hide();
    else if (action === "toggle-overlay") setOverlay(!overlayMode);
    else if (action === "is-overlay") return overlayMode;
  });

  app.on("will-quit", () => {
    globalShortcut.unregisterAll();
    if (toolServer) { try { toolServer.kill(); } catch {} }
  });

  app.on("window-all-closed", () => { /* stay in the tray */ });
}
