/**
 * Why is the window black?
 *
 * Run this when Jarvis opens as an empty rectangle. It starts the same window
 * the app does, against the same page, and then writes down what actually
 * happened rather than what should have: every renderer error, whether the page
 * finished loading, what the GPU is doing, and a PNG of the window's own
 * contents.
 *
 * The PNG is the point. A window can be black because the page failed to load,
 * because the page loaded and threw, or because the compositor is handing
 * Windows an empty surface — and from the outside all three look identical.
 * capturePage() asks the renderer what it drew, which distinguishes the last
 * one from the first two: if the file has the interface in it and the screen
 * does not, the problem is not the page.
 *
 *     npx electron diagnose.js
 *
 * Writes diagnose-report.txt and diagnose-window.png next to this file.
 */
const { app, BrowserWindow, ipcMain } = require("electron");
const fs = require("fs");
const path = require("path");
const http = require("http");

const PORT = 8123;
const REPORT = path.join(__dirname, "diagnose-report.txt");
const SHOT = path.join(__dirname, "diagnose-window.png");
const lines = [];
const say = (s) => { lines.push(s); console.log(s); };

function serverAnswers() {
  return new Promise((resolve) => {
    const req = http.get({ host: "127.0.0.1", port: PORT, path: "/", timeout: 2000 },
      (res) => { res.resume(); resolve(res.statusCode); });
    req.on("error", (e) => resolve("no: " + e.code));
    req.on("timeout", () => { req.destroy(); resolve("timed out"); });
  });
}

app.whenReady().then(async () => {
  say("=== jarvis window diagnosis ===");
  say("electron " + process.versions.electron + " · chromium " + process.versions.chrome);
  say("tool server on " + PORT + ": " + (await serverAnswers()));

  // What the compositor is willing to do. "software only" on the two below is
  // the usual reason a window paints nothing after a driver update.
  const gpu = app.getGPUFeatureStatus();
  say("");
  say("gpu features:");
  for (const [k, v] of Object.entries(gpu)) say(`  ${k.padEnd(28)} ${v}`);

  // The page's titlebar asks main for window-action on load. This script is not
  // the app and does not have the app's handlers, so without this the report
  // lists a missing handler as a fault — a fault in the diagnosis, not in
  // Jarvis, and exactly the kind of thing that sends you looking in the wrong
  // place. Answer it and say nothing.
  ipcMain.handle("window-action", () => false);

  const win = new BrowserWindow({
    width: 480, height: 780, show: false, frame: false,
    backgroundColor: "#04070d",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true, nodeIntegration: false,
    },
  });

  const problems = [];
  win.webContents.on("console-message", (_e, level, message, line, src) => {
    if (level >= 2) problems.push(`  [console] ${message}  (${path.basename(src || "?")}:${line})`);
  });
  win.webContents.on("did-fail-load", (_e, code, desc) =>
    problems.push(`  [load failed] ${code} ${desc}`));
  win.webContents.on("render-process-gone", (_e, d) =>
    problems.push(`  [renderer gone] ${d.reason} exit=${d.exitCode}`));
  win.webContents.on("preload-error", (_e, p, err) =>
    problems.push(`  [preload] ${path.basename(p)}: ${err.message}`));

  let finished = false;
  win.webContents.on("did-finish-load", () => { finished = true; });

  say("");
  say("loading http://127.0.0.1:" + PORT + "/ …");
  try {
    await win.loadURL(`http://127.0.0.1:${PORT}/`);
  } catch (e) {
    problems.push("  [loadURL threw] " + e.message);
  }
  await new Promise((r) => setTimeout(r, 6000));    // let the page settle

  say("did-finish-load fired: " + finished);
  say("");

  // Did the page actually build an interface, whatever the screen shows?
  try {
    const dom = await win.webContents.executeJavaScript(`({
      msgs: document.querySelectorAll('.msg').length,
      bodyH: Math.round(document.body.getBoundingClientRect().height),
      bodyW: Math.round(document.body.getBoundingClientRect().width),
      orb: !!document.getElementById('orb-area'),
      appLoaded: typeof send === 'function',
      bg: getComputedStyle(document.body).backgroundColor,
      firstPaintText: (document.body.innerText || '').trim().slice(0, 60)
    })`);
    say("what the page built:");
    for (const [k, v] of Object.entries(dom)) say(`  ${k.padEnd(16)} ${JSON.stringify(v)}`);
  } catch (e) {
    problems.push("  [could not read the page] " + e.message);
  }

  say("");
  if (problems.length) { say("problems:"); problems.forEach(say); }
  else say("no renderer errors at all.");

  try {
    const img = await win.webContents.capturePage();
    fs.writeFileSync(SHOT, img.toPNG());
    const size = img.getSize();
    // A capture that is one flat colour means the renderer drew nothing.
    const bmp = img.toBitmap();
    let distinct = new Set();
    for (let i = 0; i < bmp.length && distinct.size < 50; i += 4 * 977) {
      distinct.add(`${bmp[i]},${bmp[i + 1]},${bmp[i + 2]}`);
    }
    say("");
    say(`captured ${size.width}x${size.height} -> ${path.basename(SHOT)}`);
    say(`distinct colours sampled: ${distinct.size}` +
        (distinct.size <= 2 ? "  <- the renderer drew nothing" : "  <- the renderer drew the interface"));
  } catch (e) {
    say("capturePage failed: " + e.message);
  }

  fs.writeFileSync(REPORT, lines.join("\n") + "\n", "utf8");
  say("");
  say("written to " + path.basename(REPORT));
  app.exit(0);
});
