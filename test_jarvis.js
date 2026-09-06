/**
 * The tests this project did not have.
 *
 * Everything here had been verified once, by hand, by watching it run — which
 * proves it worked that afternoon and nothing about tomorrow. These cover the
 * failures that actually happened, so that changing something in six months
 * tells you what you broke instead of leaving you to find out from a screenshot.
 *
 *     node test_jarvis.js
 *
 * Two things in here are scar tissue, and both are worth keeping. The line
 * endings are normalised because the first version of one of these tests
 * silently matched nothing and reported a clean pass — the file is stored with
 * Windows line endings and the search string was not. And `check` refuses a
 * promise it was not asked to await, because two of these once "passed" while
 * returning a promise nobody looked at, which is a test that cannot fail.
 */
const fs = require("fs");

const src = fs.readFileSync("ui/app.js", "utf8").replace(/\r\n/g, "\n");
let failures = 0;

async function check(name, fn) {
  try {
    const detail = await fn();
    if (detail && typeof detail.then === "function") {
      throw new Error("the check returned a promise nobody awaited");
    }
    console.log(`  PASS  ${name}${detail ? " — " + detail : ""}`);
  } catch (e) {
    failures++;
    console.log(`  FAIL  ${name}\n        ${e.message}`);
  }
}

function slice(from, to, what) {
  const a = src.indexOf(from);
  const b = src.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error(`could not find ${what} in ui/app.js`);
  return src.slice(a, b);
}

function loadPicker() {
  const defs = slice("const TOOL_DEFS = [", "\n];", "the tool definitions") + "\n];";
  const prompts = slice("const SYSTEM_PROMPT_EN = `", "const SYSTEM_PROMPT =", "the system prompts");
  const picker = slice("let mcInPlay = false;", "const TOOL_NAMES", "the tool picker");
  // The prompt block reads `lang` from localStorage, which a browser has
  // and node does not. Standing one in is enough — nothing here tests storage.
  const stub = "const localStorage = { getItem: () => null, setItem: () => {} };";
  return new Function(stub + defs + "\n" + prompts + "\n" + picker +
    "\nreturn { toolsFor, promptFor: systemPromptFor };")();
}

function loadTrim() {
  const body = slice("const KEEP_VERBATIM", "\nfunction saveHistory()", "trimHistory");
  return new Function("history", body + "\ntrimHistory();\nreturn history;");
}

/** A session with real shape: twenty turns, each with a fat tool result in it. */
function longConversation(turns) {
  const fat = JSON.stringify({ connected: true, goal: "mining",
    inventory: Array(10).fill("cobblestone x64") });
  const h = [{ role: "system", content: "PROMPT" }];
  for (let t = 0; t < turns; t++) {
    h.push({ role: "user", content: "q" + t });
    h.push({ role: "assistant", content: "", tool_calls: [{ function: { name: "mc_status" } }] });
    h.push({ role: "tool", tool_name: "mc_status", content: fat });
    h.push({ role: "assistant", content: "a" + t });
  }
  return h;
}

function loadSummarise() {
  const body = slice("function summarise(result) {", "\nfunction chime()", "summarise");
  return new Function(body + "\nreturn { summarise };")();
}

function runLoop({ stubborn, failing, sequence }) {
  const body = slice("    let rounds = 0;", "  } catch (e) {", "the tool loop");
  const summariser = slice("function summarise(result) {", "\nfunction chime()", "summarise");
  const ran = [];
  // The loop now labels each tool line with what came back and marks the
  // failed ones, so the stub needs a classList like a real element has.
  const shell = { textContent: "…", classList: { toggle() {}, add() {}, remove() {} } };
  let call = 0;
  const env = {
    lang: "he", history: [], supportsTools: true, toolsRan: false, nudged: false,
    trace: { tool_calls: [], reply: "", failed: false },
    bubble: shell, saveHistory() {}, speak() {}, setOrb() {},
    addMsg: () => shell, claimsAnAction: () => false, TOOL_LABELS: {},
    // The loop moves the reply below the tool lines, and labels each with what
    // the tool actually returned.
    chatEl: { appendChild() {}, scrollTop: 0, scrollHeight: 0, querySelectorAll: () => [] },
    runTool: async (n) => { ran.push(n); return failing ? { error: "לא הצלחתי" } : { ok: true }; },
    chatOnce: async () => {
      call++;
      // A model working through a real multi-step request: a different tool
      // each round, then an answer.
      if (sequence) {
        if (call > sequence.length) return { content: "done.", toolCalls: [] };
        return { content: "", toolCalls: [{ function: { name: sequence[call - 1], arguments: {} } }] };
      }
      if (!stubborn && call > 2) return { content: "done.", toolCalls: [] };
      return { content: "", toolCalls: [{ function: { name: "list_allowed_directories", arguments: {} } }] };
    },
  };
  const fn = new Function(...Object.keys(env),
    summariser + "\nreturn (async () => {\n" + body + "\nreturn bubble.textContent;\n})();");
  return fn(...Object.values(env)).then((shown) => ({ ran, shown, history: env.history }));
}

async function main() {
  console.log("\nthe tool picker");

  await check("sixteen by default, and no Minecraft among them", () => {
    const got = loadPicker().toolsFor("Jarvis.");
    // Thirteen, plus the three that arrived with reminders and the watcher:
    // list_reminders, watch_status and watch_log. The rest of each of those
    // groups is destructive or a settings change and waits to be asked for.
    if (got.length !== 16) throw new Error(`expected 16, got ${got.length}`);
    if (got.some((t) => t.function.name.startsWith("mc_"))) throw new Error("Minecraft leaked");
    return "16 sent";
  });

  await check("asking about the bot brings the whole Minecraft block", () => {
    const got = loadPicker().toolsFor("send the minecraft bot to mine iron");
    if (got.length !== 26) throw new Error(`expected 26, got ${got.length}`);
    if (!got.some((t) => t.function.name === "mc_do")) throw new Error("mc_do missing");
    return "26 sent";
  });

  await check("a word summons the tool it means, and only then", () => {
    const { toolsFor } = loadPicker();
    const has = (text, name) => toolsFor(text).some((t) => t.function.name === name);
    if (!has("forget that I like coffee", "forget_fact")) throw new Error("forget_fact not summoned");
    if (!has("turn the volume down", "volume")) throw new Error("volume not summoned");
    if (has("what time is it", "volume")) throw new Error("volume summoned unasked");
    return "summoned, not over-summoned";
  });

  await check("the prompt stops describing tools it is not sending", () => {
    const { promptFor } = loadPicker();
    if (/mc_do/.test(promptFor("what time is it"))) throw new Error("still describes mc_do");
    if (!/mc_do/.test(promptFor("start the minecraft server"))) throw new Error("dropped it when asked");
    return "prompt follows the tools";
  });

  console.log("\nwhat the tool actually returned");

  await check("a result is summarised, not dumped as JSON", () => {
    const { summarise } = loadSummarise();
    const line = summarise({ set: true, id: "r1", message: "לבדוק", when: "עוד 45 דקות" });
    if (line.includes("{") || line.includes('"')) throw new Error("that is JSON: " + line);
    if (!line.includes("עוד 45 דקות")) throw new Error("lost the value: " + line);
    if (line.includes("r1")) throw new Error("kept the machine detail: " + line);
    return line;
  });

  await check("an error is shown as an error", () => {
    const { summarise } = loadSummarise();
    const line = summarise({ error: "אין תנור בסביבה" });
    if (!line.startsWith("❌")) throw new Error("not marked as a failure: " + line);
    return line;
  });

  await check("a failed tool is told to the model in words", async () => {
    const out = await runLoop({ stubborn: false, failing: true });
    const told = out.history.filter(
      (m) => typeof m.content === "string" && m.content.includes("did NOT succeed"));
    if (!told.length) throw new Error("nothing warned the model it failed");
    if (!told[0].content.includes("לא הצלחתי")) throw new Error("the reason was dropped");
    return "told once, with the reason";
  });

  await check("a tool that works is not warned about", async () => {
    const out = await runLoop({ stubborn: false, failing: false });
    const told = out.history.filter(
      (m) => typeof m.content === "string" && m.content.includes("did NOT succeed"));
    if (told.length) throw new Error("warned about a tool that worked");
    return "quiet";
  });

  console.log("\nthe conversation does not grow forever");

  await check("a long session is cut down, not carried whole", () => {
    const before = longConversation(20);
    const beforeChars = JSON.stringify(before).length;
    const after = loadTrim()(before);
    const afterChars = JSON.stringify(after).length;
    if (afterChars >= beforeChars * 0.6) {
      throw new Error("only " + Math.round(100 - afterChars / beforeChars * 100) + "% smaller");
    }
    return beforeChars + " -> " + afterChars + " chars";
  });

  await check("the system prompt is never touched", () => {
    const after = loadTrim()(longConversation(20));
    if (after[0].role !== "system" || after[0].content !== "PROMPT") {
      throw new Error("lost the system prompt");
    }
    return "intact";
  });

  await check("the newest exchange survives verbatim", () => {
    const after = loadTrim()(longConversation(20));
    if (after[after.length - 1].content !== "a19") {
      throw new Error("last reply was " + after[after.length - 1].content);
    }
    if (!after.some((m) => m.role === "tool")) throw new Error("every tool result was dropped");
    return "kept";
  });

  await check("it never opens on an orphaned tool result", () => {
    const after = loadTrim()(longConversation(60));
    if (after[1] && after[1].role === "tool") throw new Error("starts on a tool result");
    if (after.length > 42) throw new Error("over the ceiling: " + after.length);
    return after.length + " messages";
  });

  await check("a short conversation is left alone", () => {
    const short = longConversation(2);
    const before = JSON.stringify(short);
    if (JSON.stringify(loadTrim()(short)) !== before) {
      throw new Error("trimmed something it should not have");
    }
    return "untouched";
  });

  console.log("\nrounds");

  await check("a request needing several different tools gets to run them", async () => {
    const out = await runLoop({ sequence: ["see_screen", "add_note", "set_timer", "system_stats", "get_time"] });
    if (out.ran.length !== 5) throw new Error("only ran " + out.ran.join(", "));
    // The shared stub the harness uses for every message means the last tool
    // line overwrites the bubble, so the text is not the thing to assert on.
    // What matters is that it was never cut off for running out of turns.
    if (/נתקעתי|stuck/.test(out.shown)) throw new Error("hit the ceiling: " + out.shown);
    return out.ran.length + " tools in sequence, no ceiling";
  });

  await check("but a model going in circles is cut off early", async () => {
    const out = await runLoop({ stubborn: true });
    // The same call every round: the loop should give up on the wasted rounds
    // long before the eight-round ceiling.
    if (out.ran.length !== 1) throw new Error("ran the same tool " + out.ran.length + " times");
    if (!/נתקעתי|stuck/.test(out.shown)) throw new Error("said: " + out.shown);
    return "stopped and said so";
  });

  console.log("\nthe tool loop");

  await check("one tool, asked for four times, runs once", async () => {
    const out = await runLoop({ stubborn: true });
    if (out.ran.length !== 1) throw new Error(`ran ${out.ran.length} times`);
    return "ran once";
  });

  await check("a dead end is spoken, not left as three dots", async () => {
    const out = await runLoop({ stubborn: true });
    if (!out.shown || out.shown === "…") throw new Error("the user was told nothing");
    return "explained";
  });

  await check("a model that answers is not interfered with", async () => {
    const out = await runLoop({ stubborn: false });
    if (out.ran.length !== 1) throw new Error(`ran ${out.ran.length} times`);
    return "ordinary path intact";
  });

  console.log(failures ? `\n${failures} failed\n` : "\nall passed\n");
  process.exit(failures ? 1 : 0);
}

main();
