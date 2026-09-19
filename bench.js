/**
 * How long Jarvis takes to answer, on this machine.
 *
 *     node bench.js
 *     node bench.js --lang en --runs 5
 *     node bench.js --warm            (skip the cold first request)
 *
 * The number that matters before a demo is not tokens per second, it is how
 * long the person waits after they stop talking. That is what this measures,
 * and it measures it through the prompt the app actually sends: the system
 * prompt and the tool list come out of `ui/app.js` at run time, by the same
 * slicing `test_jarvis.js` uses, so a prompt that grows here shows up as a
 * slower first request instead of quietly disagreeing with what was measured.
 *
 * The first request is the one to watch. Ollama has to load the model and
 * process the whole tool prompt before it writes a word, and that is the
 * request a demo opens with. It is measured cold on purpose: the model is
 * unloaded first, so "first question" means first, not second.
 *
 * What is NOT measured: the tools themselves (a fraction of a millisecond —
 * they are local function calls), speech-to-text, and speech. This is the
 * model round, which is where the waiting is.
 */
const fs = require("fs");
const path = require("path");

const OLLAMA = process.env.JARVIS_OLLAMA || "http://localhost:11434";
const argv = process.argv.slice(2);
const flag = (name, fallback) => {
  const i = argv.indexOf("--" + name);
  return i < 0 ? fallback : argv[i + 1];
};
const LANG = flag("lang", "he");
const RUNS = Number(flag("runs", 1));
const WARM = argv.includes("--warm");

/* The questions a demo actually opens with: one that needs no tool, one that
 * opens something, one that reads the machine. Each exercises a different part
 * of the tool prompt, and together they are a fair median. */
const QUESTIONS = {
  he: ["מה השעה?", "תפתח לי מחשבון", "כמה סוללה נשארה לי?"],
  en: ["What time is it?", "Open the calculator", "How much battery is left?"],
};

/* ---------- the app's own prompt and tool list, not a copy of them ---------- */

const src = fs.readFileSync(path.join(__dirname, "ui", "app.js"), "utf8")
  .replace(/\r\n/g, "\n");   // the file is stored with Windows line endings

function slice(from, to, what) {
  const a = src.indexOf(from);
  const b = src.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error(`could not find ${what} in ui/app.js`);
  return src.slice(a, b);
}

function loadPicker(lang) {
  const defs = slice("const TOOL_DEFS = [", "\n];", "the tool definitions") + "\n];";
  const prompts = slice("const SYSTEM_PROMPT_EN = `", "const SYSTEM_PROMPT =", "the system prompts");
  const picker = slice("let mcInPlay = false;", "const TOOL_NAMES", "the tool picker");
  // The prompt block reads the language and the model from localStorage, which
  // a browser has and node does not.
  const stub = `const localStorage = { getItem: (k) => (k === "jarvis-lang" ? ${JSON.stringify(lang)} : null), setItem: () => {} };`;
  return new Function(stub + defs + "\n" + prompts + "\n" + picker +
    "\nreturn { toolsFor, promptFor: systemPromptFor };")();
}

/** The model the app defaults to, read from the app rather than repeated here. */
function defaultModel() {
  const m = src.match(/const MODEL = localStorage\.getItem\("jarvis-model"\) \|\| "([^"]+)"/);
  if (!m) throw new Error("could not find the default model in ui/app.js");
  return m[1];
}

/* ---------- talking to Ollama ---------- */

async function ollama(route, body) {
  const res = await fetch(OLLAMA + route, body ? {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  } : undefined);
  if (!res.ok) throw new Error(`${route} → HTTP ${res.status}`);
  return res.json();
}

/** Ask one question. Returns the wait, in seconds, split at the first word. */
async function ask(model, picker, question) {
  const payload = {
    model,
    messages: [
      { role: "system", content: picker.promptFor(question) },
      { role: "user", content: question },
    ],
    tools: picker.toolsFor(question),
    stream: true,
    keep_alive: "30m",
    options: { temperature: 0.15 },
  };

  const started = Date.now();
  let firstToken = 0, reply = "", toolCall = null, stats = {};

  const res = await fetch(OLLAMA + "/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`/api/chat → HTTP ${res.status}: ${await res.text()}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop();
    for (const line of lines) {
      if (!line.trim()) continue;
      let j;
      try { j = JSON.parse(line); } catch { continue; }
      const msg = j.message || {};
      if (!firstToken && (msg.content || msg.tool_calls)) firstToken = Date.now();
      if (msg.content) reply += msg.content;
      if (msg.tool_calls && !toolCall) toolCall = msg.tool_calls[0].function.name;
      if (j.done) stats = j;
    }
  }

  const total = (Date.now() - started) / 1000;
  return {
    total,
    ttfb: firstToken ? (firstToken - started) / 1000 : total,
    load: (stats.load_duration || 0) / 1e9,
    prompt: (stats.prompt_eval_duration || 0) / 1e9,
    tokens: stats.eval_count || 0,
    tps: stats.eval_count && stats.eval_duration
      ? stats.eval_count / (stats.eval_duration / 1e9) : 0,
    answered: toolCall ? `→ ${toolCall}()` : reply.trim().replace(/\s+/g, " ").slice(0, 60),
  };
}

const secs = (n) => n.toFixed(1).padStart(5) + "s";

function median(xs) {
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

async function main() {
  const picker = loadPicker(LANG);
  const model = process.env.JARVIS_MODEL || defaultModel();
  const questions = QUESTIONS[LANG] || QUESTIONS.en;

  /* Fail with the reason, not with a stack trace, because the two things that
   * go wrong here — Ollama not running, model not pulled — have one fix each. */
  let tags;
  try {
    tags = await ollama("/api/tags");
  } catch (e) {
    console.error(`Ollama is not answering on ${OLLAMA}.`);
    console.error("Start it (it runs as a service after install), then try again.");
    process.exit(1);
  }
  const have = (tags.models || []).map((m) => m.name);
  if (!have.includes(model)) {
    console.error(`The model ${model} is not on this machine.`);
    console.error(`Pull it:  ollama pull ${model}`);
    if (have.length) console.error(`Installed: ${have.join(", ")}`);
    process.exit(1);
  }

  const tools = picker.toolsFor(questions[0]).length;
  const promptChars = picker.promptFor(questions[0]).length;
  console.log(`\nmodel     ${model}`);
  console.log(`prompt    ${promptChars} chars + ${tools} tools, in ${LANG === "he" ? "Hebrew" : "English"}`);
  console.log(`ollama    ${OLLAMA}\n`);

  if (!WARM) {
    // Unload the model, so the first question below is honestly the first one
    // after a startup — prompt processing and model load included.
    await ollama("/api/chat", { model, messages: [], keep_alive: 0 }).catch(() => {});
    await new Promise((r) => setTimeout(r, 1500));
    console.log("(model unloaded — question 1 is measured cold)\n");
  }

  const results = [];
  for (let run = 0; run < RUNS; run++) {
    for (const [i, q] of questions.entries()) {
      const cold = run === 0 && i === 0 && !WARM;
      const r = await ask(model, picker, q);
      results.push({ q, cold, ...r });
      const mark = cold ? " ← first request after startup" : "";
      console.log(`${secs(r.total)}  (first word ${secs(r.ttfb).trim()})  ${q}${mark}`);
      console.log(`         ${r.answered}`);
      if (r.load > 0.05) console.log(`         model load ${r.load.toFixed(1)}s · prompt ${r.prompt.toFixed(1)}s`);
      if (r.tps) console.log(`         ${r.tokens} tokens at ${r.tps.toFixed(0)}/s`);
    }
  }

  const warm = results.filter((r) => !r.cold);
  const cold = results.find((r) => r.cold);
  console.log("\n--------------------------------------------------");
  if (cold) console.log(`first request after startup   ${secs(cold.total).trim()}`);
  console.log(`median once warm              ${secs(median(warm.map((r) => r.total))).trim()}`);
  console.log(`slowest once warm             ${secs(Math.max(...warm.map((r) => r.total))).trim()}`);
  console.log("\nThe desktop's median on its GTX 1660 was 0.9s. If this is far");
  console.log("above that, try a smaller model — never a bigger one.\n");
}

main().catch((e) => { console.error(e.message); process.exit(1); });
