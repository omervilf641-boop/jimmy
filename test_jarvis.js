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

function runLoop({ stubborn }) {
  const body = slice("    let rounds = 0;", "  } catch (e) {", "the tool loop");
  const ran = [];
  const shell = { textContent: "…" };
  let call = 0;
  const env = {
    lang: "he", history: [], supportsTools: true, toolsRan: false, nudged: false,
    trace: { tool_calls: [], reply: "", failed: false },
    bubble: shell, saveHistory() {}, speak() {}, setOrb() {},
    addMsg: () => shell, claimsAnAction: () => false, TOOL_LABELS: {},
    runTool: async (n) => { ran.push(n); return { ok: true }; },
    chatOnce: async () => {
      call++;
      if (!stubborn && call > 2) return { content: "done.", toolCalls: [] };
      return { content: "", toolCalls: [{ function: { name: "list_allowed_directories", arguments: {} } }] };
    },
  };
  const fn = new Function(...Object.keys(env),
    "return (async () => {\n" + body + "\nreturn bubble.textContent;\n})();");
  return fn(...Object.values(env)).then((shown) => ({ ran, shown }));
}

async function main() {
  console.log("\nthe tool picker");

  await check("thirteen by default, and no Minecraft among them", () => {
    const got = loadPicker().toolsFor("Jarvis.");
    if (got.length !== 13) throw new Error(`expected 13, got ${got.length}`);
    if (got.some((t) => t.function.name.startsWith("mc_"))) throw new Error("Minecraft leaked");
    return "13 sent";
  });

  await check("asking about the bot brings the whole Minecraft block", () => {
    const got = loadPicker().toolsFor("send the minecraft bot to mine iron");
    if (got.length !== 23) throw new Error(`expected 23, got ${got.length}`);
    if (!got.some((t) => t.function.name === "mc_do")) throw new Error("mc_do missing");
    return "23 sent";
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
