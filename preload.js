/**
 * The only bridge between the page and the shell. Nothing else is exposed —
 * the UI keeps running as a plain web page, and simply gains a few desktop verbs.
 */
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("jarvisDesktop", {
  isDesktop: true,
  minimize: () => ipcRenderer.invoke("window-action", "minimize"),
  close: () => ipcRenderer.invoke("window-action", "close"),
  toggleOverlay: () => ipcRenderer.invoke("window-action", "toggle-overlay"),
  isOverlay: () => ipcRenderer.invoke("window-action", "is-overlay"),

  // main -> renderer events
  onStartListening: (fn) => ipcRenderer.on("start-listening", () => fn()),
  onOverlayChanged: (fn) => ipcRenderer.on("overlay-changed", (_e, on) => fn(on)),

  // dictation: record without showing the window, hand the transcript back
  onStartDictation: (fn) => ipcRenderer.on("start-dictation", () => fn()),
  onStopDictation: (fn) => ipcRenderer.on("stop-dictation", () => fn()),
  sendDictationResult: (payload) => ipcRenderer.send("dictation-result", payload),
});
