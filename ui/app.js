const OLLAMA = "http://localhost:11434";
// qwen2.5 reliably emits tool calls; aya-expanse writes nicer Hebrew but returns
// empty responses when tools are attached, so it can't drive the Minecraft bot.
const MODEL = localStorage.getItem("jarvis-model") || "qwen2.5:7b";
const SYSTEM_PROMPT_EN = `You are Jarvis, a smart personal assistant running locally on the user's Windows PC.
Always answer in English, briefly and in a friendly tone. Your replies are read aloud, so write flowing text — no lists, no emoji, no Markdown.
You have real tools on this computer. When you need a tool, output only a single-line JSON: {"name": "tool_name", "arguments": {...}} with no other text.
Tools: get_time (date and time), open_app (arguments: {"app": one of notepad/calculator/paint/explorer/chrome/edge/settings/camera}), open_url ({"url": full address}), search_web ({"query": text}), system_stats (CPU, memory, battery, disk), add_note ({"text": the note}), read_notes, clear_notes (only on explicit request), set_timer ({"minutes": number, "message": what to remind}), volume ({"action": up/down/mute/unmute, "steps": number}), screenshot, lock_computer (only on explicit request).
After a tool runs you get its result — then tell the user briefly what you did or found.

Eyes: you can see the user's screen with see_screen. Use it whenever they ask about something in front of them — "what is this error", "what does this say", "what am I looking at" — instead of guessing or asking them to paste text.

Memory: you remember the person, not just the task. When the user tells you something personal and lasting — a preference, a name, where they study or work, what annoys them — call remember_fact — once per fact, phrased about them in the third person ("Omer studies at high school"), never as an instruction to yourself. Do not announce it every time; just keep it. Never store passwords or payment details.

Projects: you remember what you and the user work on together.
When the user says they are back — "I'm back", "חזרתי", "back", "returned" — immediately call get_last_project, then ASK whether to reopen it, naming the project and when you last worked on it. Do not reopen anything until they say yes; then call resume_project.
While you work together, call save_project to record the project name, what it is about, where you stopped, and which apps, sites or Minecraft belong to it. Update it whenever something meaningful changes, so returning later actually restores the right things.
Always give projects a short ENGLISH name, even when talking Hebrew — you corrupt Hebrew names when repeating them back, and then cannot find the project again. The description may be in any language.

Minecraft: you control your own bot in a live world. mc_start_server (boot the world and your bot — use this first if the world is not running, it takes up to 90 seconds), mc_stop_server (save and shut down), mc_connect (join), mc_status (state), mc_do (one action), mc_skills (what you know), mc_run_skill (run a skill), mc_teach (learn a new skill).
The primitive actions for mc_do are: say, come, follow, stop, goto, collect, craft, place, equip, attack, eat, look_around, inventory.
Always send flat fields to mc_do, never a nested object. Exact examples:
Chop three logs: {"name": "mc_do", "arguments": {"action": "collect", "block": "oak_log", "count": 3}}
Come to the player: {"name": "mc_do", "arguments": {"action": "come"}}
Craft a pickaxe: {"name": "mc_do", "arguments": {"action": "craft", "item": "wooden_pickaxe", "count": 1}}
To teach a skill always use mc_teach with a plain-text recipe, never mc_learn:
{"name": "mc_teach", "arguments": {"name": "make a pickaxe", "recipe": "collect oak_log 3; craft oak_planks 4; craft stick 4; craft crafting_table 1; craft wooden_pickaxe 1"}}
Skills are saved permanently and can be re-run by name with mc_run_skill. Use the exact saved name — call mc_skills first if unsure.`;

const SYSTEM_PROMPT_HE = `אתה ג'רוויס, עוזר אישי חכם שרץ מקומית על מחשב Windows של המשתמש.
ענה תמיד בעברית תקינה בלבד, בקצרה ובטון חברותי. לעולם אל תערבב שפות אחרות. התשובות מוקראות בקול — כתוב טקסט זורם, בלי רשימות, בלי אימוג'י ובלי Markdown.
יש לך כלים אמיתיים על המחשב. כשצריך כלי, כתוב אך ורק JSON בשורה אחת בפורמט: {"name": "שם_הכלי", "arguments": {...}} בלי טקסט נוסף.
הכלים: get_time (שעה ותאריך), open_app (פתיחת אפליקציה, arguments: {"app": אחד מ-notepad/calculator/paint/explorer/chrome/edge/settings/camera}), open_url (arguments: {"url": כתובת מלאה}), search_web (חיפוש בגוגל, arguments: {"query": טקסט}), system_stats (מצב המחשב: מעבד, זיכרון, סוללה, דיסק), add_note (שמירת פתק, arguments: {"text": הפתק}), read_notes (קריאת הפתקים), clear_notes (מחיקת כל הפתקים — רק אם המשתמש ביקש במפורש), set_timer (תזכורת, arguments: {"minutes": מספר, "message": מה להזכיר}), volume (עוצמת שמע, arguments: {"action": up/down/mute/unmute, "steps": מספר}), screenshot (צילום מסך), lock_computer (נעילת המחשב — רק אם המשתמש ביקש במפורש).
אחרי שכלי רץ תקבל את התוצאה — ספר למשתמש בקצרה ובעברית מה עשית או מה גילית.

עיניים: אתה יכול לראות את המסך של המשתמש עם see_screen. השתמש בזה כשהוא שואל על משהו שמולו — "מה השגיאה הזאת", "מה כתוב פה", "מה אני רואה" — במקום לנחש או לבקש ממנו להעתיק טקסט.

זיכרון: אתה זוכר את האדם, לא רק את המשימה. כשהמשתמש מספר משהו אישי ומתמשך — העדפה, שם, איפה הוא לומד או עובד, מה מעצבן אותו — קרא ל-remember_fact — פעם אחת לכל עובדה, מנוסחת עליו בגוף שלישי ("עומר לומד בתיכון"), לא כהוראה לעצמך. אל תכריז על זה בכל פעם, פשוט תזכור. לעולם אל תשמור סיסמאות או פרטי תשלום.

פרויקטים: אתה זוכר על מה אתם עובדים יחד.
כשהמשתמש אומר שהוא חזר — "חזרתי", "אני פה", "back" — קרא מיד ל-get_last_project, ואז **שאל** אם לפתוח את הפרויקט, תוך ציון השם ומתי עבדתם עליו לאחרונה. אל תפתח כלום עד שיאשר; רק אז קרא ל-resume_project.
תוך כדי העבודה קרא ל-save_project כדי לרשום את שם הפרויקט, על מה הוא, איפה עצרתם, ואילו תוכנות, אתרים או מיינקראפט שייכים לו. עדכן כשמשהו משמעותי משתנה.
תן לפרויקטים שם קצר **באנגלית** תמיד, גם בשיחה בעברית — אתה משבש שמות בעברית כשאתה חוזר עליהם ואז לא מוצא את הפרויקט. התיאור יכול להיות בעברית.

מיינקראפט: יש לך בוט משלך בעולם. mc_connect (התחברות), mc_status (מצב), mc_do (פעולה בודדת), mc_skills (מה אתה יודע), mc_run_skill (הפעלת מיומנות), mc_learn (לימוד מיומנות חדשה).
הפעולות הבסיסיות ל-mc_do הן באנגלית בלבד: say, come, follow, stop, goto, collect, craft, place, equip, attack, eat, look_around, inventory.
ל-mc_do תמיד שלח שדות שטוחים, בלי אובייקט מקונן. דוגמאות מדויקות:
לכרות שלושה עצים: {"name": "mc_do", "arguments": {"action": "collect", "block": "עץ", "count": 3}}
לבוא אל השחקן: {"name": "mc_do", "arguments": {"action": "come"}}
ליצור מכוש: {"name": "mc_do", "arguments": {"action": "craft", "item": "מכוש", "count": 1}}
לבדוק מה בתיק: {"name": "mc_do", "arguments": {"action": "inventory"}}
כשהמשתמש מלמד אותך משימה מורכבת, השתמש תמיד ב-mc_teach עם מתכון טקסט פשוט — לא ב-mc_learn.
דוגמה ללימוד מיומנות: {"name": "mc_teach", "arguments": {"name": "להכין מכוש", "recipe": "collect עץ 3; craft לוחות 4; craft מקלות 4; craft שולחן יצירה 1; craft מכוש 1"}}
אחרי שלמדת מיומנות היא נשמרת לתמיד, ואפשר להריץ אותה שוב עם mc_run_skill לפי השם.
כשאתה מריץ מיומנות, השתמש בשם המדויק בעברית כפי שהוא נשמר — לעולם אל תתעתק אותו לאותיות לטיניות. אם אינך בטוח בשם, קרא קודם ל-mc_skills.`;

// English is the default: tool-calling is markedly more reliable, and the
// browser has an English voice installed while it has no Hebrew one.
let lang = localStorage.getItem("jarvis-lang") || "en";
const SYSTEM_PROMPT = lang === "he" ? SYSTEM_PROMPT_HE : SYSTEM_PROMPT_EN;
const SPEECH_LANG = lang === "he" ? "he-IL" : "en-US";

const TOOL_DEFS = [
  { type: "function", function: { name: "get_time", description: "מחזיר את התאריך, השעה והיום בשבוע הנוכחיים", parameters: { type: "object", properties: {}, required: [] } } },
  { type: "function", function: { name: "open_app", description: "פותח אפליקציה במחשב", parameters: { type: "object", properties: { app: { type: "string", enum: ["notepad","calculator","paint","explorer","chrome","edge","settings","camera"], description: "האפליקציה לפתיחה" } }, required: ["app"] } } },
  { type: "function", function: { name: "open_url", description: "פותח כתובת אינטרנט בדפדפן", parameters: { type: "object", properties: { url: { type: "string", description: "כתובת מלאה כולל https://" } }, required: ["url"] } } },
  { type: "function", function: { name: "search_web", description: "מחפש בגוגל ופותח את תוצאות החיפוש בדפדפן", parameters: { type: "object", properties: { query: { type: "string", description: "מה לחפש" } }, required: ["query"] } } },
  { type: "function", function: { name: "system_stats", description: "מחזיר את מצב המחשב: עומס מעבד, זיכרון, סוללה ומקום פנוי בדיסק", parameters: { type: "object", properties: {}, required: [] } } },
  { type: "function", function: { name: "free_gpu", description: "מפנה את זיכרון כרטיס המסך מכל המודלים הטעונים. השתמש בזה כשהמשתמש מתלונן שהמחשב איטי, שהכרטיס מלא, או לפני משימה כבדה.", parameters: { type: "object", properties: {}, required: [] } } },
  { type: "function", function: { name: "see_screen", description: "מסתכל על המסך של המשתמש ועונה על שאלה לגביו. השתמש בזה כשהמשתמש שואל 'מה זה', 'מה השגיאה הזאת', 'מה כתוב פה', או מתייחס למשהו שהוא רואה.", parameters: { type: "object", properties: { question: { type: "string", description: "מה לבדוק בתמונה, באנגלית" } }, required: [] } } },
  { type: "function", function: { name: "remember_fact", description: "זוכר עובדה על המשתמש לתמיד — העדפות, אנשים, מקומות, מה הוא אוהב או שונא. השתמש בזה כשהמשתמש מספר משהו אישי שכדאי לזכור. אם הוא סיפר כמה דברים, קרא לכלי פעם אחת לכל אחד.", parameters: { type: "object", properties: { facts: { type: "array", items: { type: "string" }, description: "רשימת עובדות על המשתמש, כל אחת בגוף שלישי. למשל: [\"עומר לומד בתיכון\", \"עומר מעדיף שהכל ירוץ מקומית\"]. אם המשתמש סיפר כמה דברים — שים את כולם כאן." }, fact: { type: "string", description: "עובדה בודדת, אם יש רק אחת" }, category: { type: "string", description: "קטגוריה: preference, person, place, work, health, general" } }, required: [] } } },
  { type: "function", function: { name: "recall_facts", description: "מחזיר את מה שאתה יודע על המשתמש", parameters: { type: "object", properties: { about: { type: "string", description: "סינון לפי נושא, ריק להכל" } }, required: [] } } },
  { type: "function", function: { name: "forget_fact", description: "שוכח עובדה על המשתמש", parameters: { type: "object", properties: { about: { type: "string", description: "מה לשכוח" } }, required: ["about"] } } },
  { type: "function", function: { name: "save_project", description: "שומר או מעדכן פרויקט שעובדים עליו יחד — שם, תיאור, אילו תוכנות ואתרים פתוחים, והאם מיינקראפט רץ", parameters: { type: "object", properties: { name: { type: "string", description: "שם קצר לפרויקט" }, description: { type: "string", description: "על מה הפרויקט" }, notes: { type: "string", description: "איפה עצרנו" }, apps: { type: "array", items: { type: "string" }, description: "תוכנות לפתוח בהמשך" }, urls: { type: "array", items: { type: "string" }, description: "אתרים לפתוח בהמשך" }, minecraft: { type: "boolean", description: "האם הפרויקט כולל מיינקראפט" } }, required: ["name"] } } },
  { type: "function", function: { name: "get_last_project", description: "מחזיר את הפרויקט האחרון שעבדנו עליו יחד. השתמש בזה כשהמשתמש אומר שהוא חזר.", parameters: { type: "object", properties: {}, required: [] } } },
  { type: "function", function: { name: "resume_project", description: "משחזר פרויקט — פותח את התוכנות והאתרים שלו ומפעיל מיינקראפט אם צריך", parameters: { type: "object", properties: { name: { type: "string", description: "שם הפרויקט, ריק לאחרון" } }, required: [] } } },
  { type: "function", function: { name: "list_projects", description: "מחזיר את כל הפרויקטים השמורים", parameters: { type: "object", properties: {}, required: [] } } },
  { type: "function", function: { name: "add_note", description: "שומר פתק לרשימת הפתקים של המשתמש", parameters: { type: "object", properties: { text: { type: "string", description: "תוכן הפתק" } }, required: ["text"] } } },
  { type: "function", function: { name: "read_notes", description: "מחזיר את הפתקים השמורים של המשתמש", parameters: { type: "object", properties: {}, required: [] } } },
  { type: "function", function: { name: "clear_notes", description: "מוחק את כל הפתקים — רק לבקשה מפורשת של המשתמש", parameters: { type: "object", properties: {}, required: [] } } },
  { type: "function", function: { name: "set_timer", description: "קובע תזכורת שתישמע בעוד מספר דקות", parameters: { type: "object", properties: { minutes: { type: "number", description: "בעוד כמה דקות" }, message: { type: "string", description: "מה להזכיר" } }, required: ["minutes"] } } },
  { type: "function", function: { name: "volume", description: "שולט בעוצמת השמע של המחשב", parameters: { type: "object", properties: { action: { type: "string", enum: ["up","down","mute","unmute"] }, steps: { type: "number", description: "כמה צעדים (ברירת מחדל 5)" } }, required: ["action"] } } },
  { type: "function", function: { name: "screenshot", description: "מצלם את המסך ושומר בתמונות", parameters: { type: "object", properties: {}, required: [] } } },
  { type: "function", function: { name: "lock_computer", description: "נועל את המחשב — רק לבקשה מפורשת של המשתמש", parameters: { type: "object", properties: {}, required: [] } } },
  { type: "function", function: { name: "mc_start_server", description: "מפעיל את שרת המיינקראפט ואת הבוט. השתמש בזה כשמבקשים לפתוח מיינקראפט או כשהבוט לא מחובר. לוקח עד דקה וחצי.", parameters: { type: "object", properties: {}, required: [] } } },
  { type: "function", function: { name: "mc_stop_server", description: "שומר וסוגר את שרת המיינקראפט", parameters: { type: "object", properties: {}, required: [] } } },
  { type: "function", function: { name: "mc_autopilot", description: "מפעיל או מכבה מצב אוטונומי — הבוט משחק ושורד בעצמו: נלחם, אוסף, בונה מקלט בלילה", parameters: { type: "object", properties: { on: { type: "boolean", description: "true להפעיל, false לכבות" } }, required: ["on"] } } },
  { type: "function", function: { name: "mc_connect", description: "מחבר את הבוט של ג'רוויס לעולם המיינקראפט", parameters: { type: "object", properties: {}, required: [] } } },
  { type: "function", function: { name: "mc_status", description: "מצב הבוט במיינקראפט: חיים, רעב, מיקום, תיק, מיומנויות", parameters: { type: "object", properties: {}, required: [] } } },
  { type: "function", function: { name: "mc_do", description: "מבצע פעולה אחת במיינקראפט. שדות שטוחים — בלי אובייקטים מקוננים.", parameters: { type: "object", properties: {
    action: { type: "string", enum: ["say","come","follow","stop","goto","collect","craft","place","equip","attack","eat","look_around","inventory"], description: "שם הפעולה באנגלית בלבד" },
    block: { type: "string", description: "שם הבלוק לכרייה, למשל עץ או אבן" },
    item: { type: "string", description: "שם הפריט ליצירה או להחזקה" },
    count: { type: "number", description: "כמות" },
    mob: { type: "string", description: "סוג היצור לתקיפה" },
    text: { type: "string", description: "טקסט לצ'אט" },
    x: { type: "number" }, y: { type: "number" }, z: { type: "number" },
  }, required: ["action"] } } },
  { type: "function", function: { name: "mc_learn", description: "מלמד את הבוט מיומנות חדשה — רצף פעולות שנשמר לתמיד", parameters: { type: "object", properties: { name: { type: "string", description: "שם המיומנות בעברית" }, description: { type: "string" }, steps: { type: "array", description: "רשימת צעדים, כל אחד {\"action\":\"...\",\"args\":{...}}", items: { type: "object" } } }, required: ["name","steps"] } } },
  { type: "function", function: { name: "mc_teach", description: "מלמד את הבוט מיומנות חדשה ממתכון טקסט פשוט. השתמש בזה תמיד ללימוד מיומנות.", parameters: { type: "object", properties: { name: { type: "string", description: "שם המיומנות בעברית" }, recipe: { type: "string", description: "צעדים מופרדים בנקודה-פסיק, כל צעד: פעולה מטרה כמות. למשל: collect עץ 3; craft לוחות 4; craft מקלות 4" } }, required: ["name","recipe"] } } },
  { type: "function", function: { name: "mc_run_skill", description: "מריץ מיומנות שהבוט למד", parameters: { type: "object", properties: { name: { type: "string" } }, required: ["name"] } } },
  { type: "function", function: { name: "mc_skills", description: "מחזיר את רשימת המיומנויות שהבוט למד ואת הפעולות הבסיסיות", parameters: { type: "object", properties: {}, required: [] } } },
];

// Words that assert an action was carried out. Kept as plain substring checks:
// a regex mixing these with Hebrew alternatives silently stopped matching.
const CLAIM_PHRASES = [
  "i've noted", "i have noted", "i've saved", "i have saved", "i've remembered",
  "i've stored", "i've opened", "i've set", "i've created", "i've added",
  "i've started", "noted that", "saved it", "saved that", "reminder is set",
  "i'll remember", "got it, i", "רשמתי", "שמרתי", "פתחתי", "זכרתי", "הגדרתי",
];
function claimsAnAction(text) {
  const t = String(text || "").toLowerCase();
  return CLAIM_PHRASES.some((p) => t.includes(p));
}

const TOOL_LABELS = {
  get_time: "🕐 בודק שעה", open_app: "🚀 פותח אפליקציה", open_url: "🌐 פותח אתר",
  search_web: "🔎 מחפש בגוגל", system_stats: "💻 בודק את המחשב",
  add_note: "📝 שומר פתק", read_notes: "📖 קורא פתקים", clear_notes: "🗑 מוחק פתקים",
  set_timer: "⏰ קובע תזכורת", volume: "🔊 משנה עוצמה", screenshot: "📸 מצלם מסך",
  lock_computer: "🔒 נועל את המחשב",
  mc_start_server: "🎮 מפעיל את המיינקראפט…", mc_stop_server: "🎮 סוגר את השרת",
  mc_autopilot: "🤖 מצב אוטונומי",
  mc_connect: "⛏ מתחבר למיינקראפט", mc_status: "⛏ בודק מצב בעולם", mc_do: "⛏ פועל בעולם",
  mc_learn: "🧠 לומד מיומנות חדשה", mc_teach: "🧠 לומד מיומנות חדשה",
  mc_run_skill: "🧠 מפעיל מיומנות", mc_skills: "🧠 בודק מה הוא יודע",
};

const chatEl = document.getElementById("chat");
const orb = document.getElementById("orb");
const orbHint = document.getElementById("orb-hint");
const statusEl = document.getElementById("status");
const statusText = document.getElementById("status-text");
const input = document.getElementById("text-input");
const sendBtn = document.getElementById("send-btn");
const micBtn = document.getElementById("mic-btn");
const speakToggle = document.getElementById("speak-toggle");
const convoToggle = document.getElementById("convo-toggle");
const clearBtn = document.getElementById("clear-btn");
const voiceWarning = document.getElementById("voice-warning");

let history = [{ role: "system", content: SYSTEM_PROMPT }];
let busy = false;
let speakEnabled = localStorage.getItem("jarvis-speak") !== "off";
let convoMode = localStorage.getItem("jarvis-convo") === "on";
let ollamaOnline = false;

/* ---------- starfield background ---------- */
(() => {
  const c = document.getElementById("stars"), ctx = c.getContext("2d");
  let stars = [];
  function resize() {
    c.width = innerWidth; c.height = innerHeight;
    stars = Array.from({ length: 90 }, () => ({
      x: Math.random() * c.width, y: Math.random() * c.height,
      r: Math.random() * 1.4 + 0.3, s: Math.random() * 0.25 + 0.05,
      p: Math.random() * Math.PI * 2,
    }));
  }
  resize(); addEventListener("resize", resize);
  (function draw(t) {
    ctx.clearRect(0, 0, c.width, c.height);
    for (const st of stars) {
      const a = 0.25 + 0.55 * Math.abs(Math.sin(t / 2200 + st.p));
      ctx.fillStyle = `rgba(90, 190, 255, ${a})`;
      ctx.beginPath(); ctx.arc(st.x, st.y, st.r, 0, 7); ctx.fill();
      st.y += st.s; if (st.y > c.height) st.y = -2;
    }
    requestAnimationFrame(draw);
  })(0);
})();

/* ---------- persistence ---------- */
function saveHistory() {
  localStorage.setItem("jarvis-history", JSON.stringify(history.filter(m => m.role === "user" || (m.role === "assistant" && !m.tool_calls))));
}
function loadHistory() {
  try {
    const saved = JSON.parse(localStorage.getItem("jarvis-history") || "[]");
    for (const m of saved.slice(-20)) {
      history.push(m);
      addMsg(m.role === "user" ? "user" : "jarvis", m.content);
    }
    if (saved.length) { hideSuggestions(); return true; }
  } catch {}
  return false;
}
clearBtn.addEventListener("click", () => {
  history = [{ role: "system", content: SYSTEM_PROMPT }];
  localStorage.removeItem("jarvis-history");
  chatEl.innerHTML = "";
  greet();
});

/* ---------- status ---------- */
async function checkOllama() {
  try {
    const r = await fetch(OLLAMA + "/api/tags");
    const data = await r.json();
    const hasModel = (data.models || []).some(m => m.name.startsWith(MODEL.split(":")[0]));
    ollamaOnline = true;
    statusEl.classList.add("online");
    statusText.textContent = hasModel ? MODEL : "המודל בהורדה…";
  } catch {
    ollamaOnline = false;
    statusEl.classList.remove("online");
    statusText.textContent = "Ollama לא זמין";
  }
}
checkOllama(); setInterval(checkOllama, 5000);

/* ---------- chat UI ---------- */
function addMsg(role, text, isError = false) {
  const div = document.createElement("div");
  div.className = "msg " + role + (isError ? " error" : "");
  div.textContent = text;
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
  if (role === "user") hideSuggestions();
  return div;
}
function hideSuggestions() {
  const s = document.getElementById("suggestions");
  if (s) s.classList.add("hidden");
}
const IDLE_HINT = () => (lang === "he" ? "לחץ על הליבה כדי לדבר, או כתוב למטה" : "Click the core to talk, or type below");
function setOrb(state, hint) {
  orb.className = state || "";
  orbHint.textContent = hint || IDLE_HINT();
}

/* ---------- Ollama chat with tool-calling ---------- */
const TOOL_NAMES = new Set(TOOL_DEFS.map(t => t.function.name));

// Some models emit tool calls as raw text instead of structured tool_calls —
// detect {"name": ..., "arguments": ...} patterns in the content as a fallback.
// Scan for balanced {...} blocks and keep the ones that parse as a tool call.
// A regex can't do this: the argument object nests, and models vary the key names
// ("name"/"tool_name"/"function", "arguments"/"parameters"/"args").
function findJsonObjects(text) {
  const found = [];
  for (let i = 0; i < text.length; i++) {
    if (text[i] !== "{") continue;
    let depth = 0, inStr = false, esc = false;
    for (let j = i; j < text.length; j++) {
      const c = text[j];
      if (esc) { esc = false; continue; }
      if (c === "\\") { esc = true; continue; }
      if (c === '"') { inStr = !inStr; continue; }
      if (inStr) continue;
      if (c === "{") depth++;
      else if (c === "}") {
        depth--;
        if (depth === 0) { found.push({ start: i, end: j + 1, text: text.slice(i, j + 1) }); i = j; break; }
      }
    }
  }
  return found;
}

function asToolCall(obj) {
  if (!obj || typeof obj !== "object") return null;
  const name = obj.name || obj.tool_name || obj.tool || obj.function;
  if (typeof name !== "string" || !TOOL_NAMES.has(name)) return null;
  let args = obj.arguments ?? obj.parameters ?? obj.args ?? obj.input ?? {};
  if (typeof args === "string") { try { args = JSON.parse(args); } catch { args = {}; } }
  if (!args || typeof args !== "object") args = {};
  return { function: { name, arguments: args } };
}

function extractInlineToolCalls(text) {
  const calls = [];
  for (const blob of findJsonObjects(text)) {
    let parsed;
    try { parsed = JSON.parse(blob.text); } catch { continue; }
    const call = asToolCall(parsed);
    if (call) calls.push(call);
  }
  return calls;
}

function stripToolMarkup(text) {
  let out = text.replace(/<\/?tool_call>/g, "");
  const blobs = findJsonObjects(out).filter((b) => {
    try { return !!asToolCall(JSON.parse(b.text)); } catch { return false; }
  });
  for (let i = blobs.length - 1; i >= 0; i--) {
    out = out.slice(0, blobs[i].start) + out.slice(blobs[i].end);
  }
  return out.trim();
}

let supportsTools = true; // flips off automatically if the model rejects the tools param

async function chatOnce(bubble) {
  const payload = {
    model: MODEL, messages: history, stream: true,
    keep_alive: "30m", options: { temperature: 0.6 },
  };
  if (supportsTools) payload.tools = TOOL_DEFS;
  let resp = await fetch(OLLAMA + "/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok && supportsTools) {
    const errText = await resp.text();
    if (/does not support tools/i.test(errText)) {
      supportsTools = false; // retry without native tools — inline JSON parsing still works
      delete payload.tools;
      resp = await fetch(OLLAMA + "/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    }
  }
  if (!resp.ok) throw new Error("HTTP " + resp.status);

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let full = "", buf = "", toolCalls = [];
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split("\n"); buf = lines.pop();
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const j = JSON.parse(line);
        const msg = j.message || {};
        if (msg.content) {
          full += msg.content;
          bubble.textContent = stripToolMarkup(full) || "…";
          bubble.classList.add("typing");     // HUD cursor while tokens arrive
          chatEl.scrollTop = chatEl.scrollHeight;
        }
        if (msg.tool_calls) toolCalls.push(...msg.tool_calls);
      } catch {}
    }
  }
  if (toolCalls.length === 0) toolCalls = extractInlineToolCalls(full);
  return { content: stripToolMarkup(full), toolCalls };
}

function chime() {
  try {
    const ac = new (window.AudioContext || window.webkitAudioContext)();
    const o = ac.createOscillator(), g = ac.createGain();
    o.connect(g); g.connect(ac.destination);
    o.frequency.value = 880;
    g.gain.setValueAtTime(0.18, ac.currentTime);
    g.gain.exponentialRampToValueAtTime(0.001, ac.currentTime + 0.5);
    o.start(); o.stop(ac.currentTime + 0.5);
  } catch {}
}

// timers run in the page so the reminder can chime and speak
function runTimerTool(args) {
  const mins = parseFloat(args.minutes);
  if (!mins || mins <= 0) return { error: "משך לא תקין" };
  const msg = (args.message || "").trim() || "הטיימר הסתיים";
  setTimeout(() => {
    chime();
    addMsg("jarvis", "⏰ תזכורת: " + msg);
    speak("תזכורת: " + msg);
  }, mins * 60000);
  return { timer_set: true, minutes: mins, message: msg };
}

// Models sometimes wrap the real arguments one level deeper, e.g.
// {"tool_name": "mc_do", "parameters": {...}} — unwrap before dispatching.
function unwrapArgs(args) {
  if (!args || typeof args !== "object") return {};
  for (const key of ["parameters", "arguments", "args", "input"]) {
    const inner = args[key];
    if (inner && typeof inner === "object" && !Array.isArray(inner)) {
      const siblings = Object.keys(args).filter((k) => k !== key && k !== "tool_name" && k !== "name");
      if (!siblings.length) return unwrapArgs(inner);
    }
  }
  return args;
}

async function runTool(name, rawArgs) {
  const args = unwrapArgs(rawArgs);
  if (name === "set_timer") return runTimerTool(args);
  const r = await fetch("/tool", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, args }),
  });
  return await r.json();
}

async function send(text) {
  if (!text.trim() || busy) return;
  busy = true;
  window.speechSynthesis.cancel(); stopVoice();
  addMsg("user", text);
  history.push({ role: "user", content: text });

  // Everything this turn does gets recorded — it is the training corpus.
  const trace = { lang, model: MODEL, user: text, tool_calls: [], failed: false, reply: "" };
  let toolsRan = false;
  let nudged = false;
  setOrb("thinking", "ג'רוויס חושב…");
  let bubble = addMsg("jarvis", "…");

  try {
    let rounds = 0;
    while (rounds++ < 4) {
      let { content, toolCalls } = await chatOnce(bubble);
      if (toolCalls.length === 0) {
        // Caught claiming an action it never performed — the same failure the
        // Minecraft agent had. Make it try again instead of lying.
        if (!toolsRan && !nudged && claimsAnAction(content)) {
          nudged = true;
          history.push({ role: "assistant", content });
          history.push({ role: "user", content:
            "You did not call any tool, so nothing was actually saved or done. " +
            "Call the correct tool now instead of saying you did it." });
          continue;
        }
        history.push({ role: "assistant", content });
        saveHistory();
        trace.reply = content;
        speak(content);
        break;
      }
      toolsRan = true;
      // model wants tools — run them and loop
      if (!/[א-ת]{2,}/.test(content)) { content = ""; bubble.textContent = "…"; } // hide leaked fragments
      const assistantMsg = { role: "assistant", content };
      if (supportsTools) assistantMsg.tool_calls = toolCalls;
      history.push(assistantMsg);
      for (const tc of toolCalls) {
        const fname = tc.function?.name || "?";
        let fargs = tc.function?.arguments || {};
        if (typeof fargs === "string") { try { fargs = JSON.parse(fargs); } catch { fargs = {}; } }
        addMsg("tool-note", (TOOL_LABELS[fname] || "⚙ " + fname) + "…");
        const result = await runTool(fname, fargs);
        const failed = !!(result && (result.error || /FAILED/.test(JSON.stringify(result))));
        trace.tool_calls.push({ name: fname, args: fargs, ok: !failed });
        if (failed) trace.failed = true;
        if (supportsTools) {
          history.push({ role: "tool", tool_name: fname, content: JSON.stringify(result, null, 0) });
        } else {
          history.push({ role: "user", content: "[תוצאת הכלי " + fname + "]: " + JSON.stringify(result, null, 0) });
        }
      }
      if (bubble.textContent === "…" || bubble.textContent === "") bubble.textContent = "…";
      else bubble = addMsg("jarvis", "…");
      setOrb("thinking", "ג'רוויס מעבד את התוצאה…");
    }
  } catch (e) {
    bubble.textContent = ollamaOnline
      ? "שגיאה בשיחה עם המודל: " + e.message
      : "Ollama לא רץ כרגע. פתח את Ollama ונסה שוב.";
    bubble.classList.add("error");
    trace.failed = true;
    trace.error = e.message;
    setOrb("", "");
  } finally {
    busy = false;
    for (const el of chatEl.querySelectorAll(".msg.typing")) el.classList.remove("typing");
    if (!window.speechSynthesis.speaking && !currentVoiceSource) setOrb("", "");
    if (!trace.reply) trace.reply = bubble.textContent || "";
    fetch("/trace", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(trace),
    }).catch(() => { /* logging must never break the conversation */ });
  }
}

/* ---------- text-to-speech ---------- */
function rankVoice(v) {
  const want = lang === "he" ? "he" : "en";
  if (!v.lang || !v.lang.toLowerCase().startsWith(want)) return -1;
  let score = 1;
  if (/natural|online/i.test(v.name)) score += 10;   // Edge natural voices
  if (lang === "he" && /avri|hila/i.test(v.name)) score += 5;
  if (lang === "en" && /aria|jenny|guy|zira|david/i.test(v.name)) score += 3;
  if (v.localService === false) score += 2;
  return score;
}
function pickVoice() {
  const voices = window.speechSynthesis.getVoices();
  let best = null, bestScore = 0;
  for (const v of voices) {
    const s = rankVoice(v);
    if (s > bestScore) { best = v; bestScore = s; }
  }
  return best;
}
function updateVoiceWarning() {
  const voices = window.speechSynthesis.getVoices();
  if (!voices.length) return; // not loaded yet
  if (pickVoice() || lang !== "he") { voiceWarning.style.display = "none"; return; }
  voiceWarning.innerHTML = "⚠️ לא מותקן קול עברי בדפדפן הזה — התשובות יישמעו באנגלית. <b>פתרון מהיר:</b> פתח את הדף ב-<b>Microsoft Edge</b>, או חזור למצב English.";
  voiceWarning.style.display = "block";
}
function cleanForSpeech(text) {
  return text
    .replace(/[*_#`>~\[\]()]/g, " ")
    .replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/gu, "")
    .replace(/\s+/g, " ").trim();
}
function speakWithBrowser(clean) {
  // Fallback only: Windows' SAPI voices, used when Piper isn't available.
  const chunks = clean.match(/[^.!?׃]+[.!?׃]?/g) || [clean];
  const voice = pickVoice();
  let remaining = chunks.length;
  for (const chunk of chunks) {
    const u = new SpeechSynthesisUtterance(chunk.trim());
    if (voice) u.voice = voice;
    u.lang = SPEECH_LANG; u.rate = 1.05;
    u.onend = u.onerror = () => {
      if (--remaining <= 0) { setOrb("", ""); maybeRelisten(); }
    };
    window.speechSynthesis.speak(u);
  }
}

async function speak(text) {
  if (!speakEnabled) { setOrb("", ""); maybeRelisten(); return; }
  const clean = cleanForSpeech(text);
  if (!clean) { setOrb("", ""); maybeRelisten(); return; }

  setOrb("speaking", lang === "he" ? "ג'רוויס מדבר…" : "Jarvis is speaking…");

  // Hebrew has no Piper model installed, so it still goes through the browser.
  if (ttsAvailable && lang !== "he") {
    try {
      await speakWithPiper(clean);
      setOrb("", "");
      maybeRelisten();
      return;
    } catch (e) {
      ttsAvailable = false;      // don't keep retrying a server that can't speak
      console.warn("Piper unavailable, falling back to browser speech:", e.message);
    }
  }

  if (!("speechSynthesis" in window)) { setOrb("", ""); maybeRelisten(); return; }
  speakWithBrowser(clean);
}
speakToggle.classList.toggle("off", !speakEnabled);
speakToggle.addEventListener("click", () => {
  speakEnabled = !speakEnabled;
  speakToggle.classList.toggle("off", !speakEnabled);
  localStorage.setItem("jarvis-speak", speakEnabled ? "on" : "off");
  if (!speakEnabled) { window.speechSynthesis.cancel(); stopVoice(); }
});

/* ---------- speech-to-text ---------- */
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognizing = false, recognition = null;

if (SR) {
  recognition = new SR();
  recognition.lang = SPEECH_LANG;
  recognition.interimResults = true;
  recognition.continuous = false;

  recognition.onstart = () => {
    recognizing = true;
    micBtn.classList.add("on");
    setOrb("listening", "מקשיב… דבר עכשיו");
  };
  recognition.onresult = (e) => {
    let interim = "", final = "";
    for (const res of e.results) {
      if (res.isFinal) final += res[0].transcript;
      else interim += res[0].transcript;
    }
    if (interim) orbHint.textContent = "שומע: " + interim;
    if (final) send(final);
  };
  recognition.onend = () => {
    recognizing = false;
    micBtn.classList.remove("on");
    if (!busy && !window.speechSynthesis.speaking) setOrb("", "");
  };
  recognition.onerror = (e) => {
    recognizing = false;
    micBtn.classList.remove("on");
    if (e.error === "not-allowed") addMsg("jarvis", "אין הרשאת מיקרופון. אשר את המיקרופון בדפדפן, או כתוב לי.", true);
    setOrb("", "");
  };
} else {
  micBtn.disabled = true;
  micBtn.title = "זיהוי דיבור לא נתמך בדפדפן הזה — נסה Chrome או Edge";
}

function startListening() {
  if (!recognition || recognizing || busy) return;
  window.speechSynthesis.cancel(); stopVoice();
  if (wakeRec && wakeActive) { try { wakeRec.stop(); } catch {} } // only one recognizer may hold the mic
  setTimeout(() => { try { recognition.start(); } catch {} }, wakeActive ? 250 : 0);
}
function toggleMic() {
  if (!recognition) return;
  if (window.speechSynthesis.speaking || currentVoiceSource) { window.speechSynthesis.cancel(); stopVoice(); setOrb("", ""); return; }
  if (recognizing) recognition.stop();
  else startListening();
}
// Wrapped, not passed directly: the local-Whisper path replaces toggleMic
// later, and a directly-bound listener would keep calling the old one.
micBtn.addEventListener("click", () => toggleMic());
orb.addEventListener("click", () => toggleMic());

/* ---------- wake word: "היי ג'רוויס" ---------- */
let wakeMode = localStorage.getItem("jarvis-wake") === "on";
let wakeActive = false, wakeRec = null;
// tolerant: speech recognition spells the name many ways (ג'רוויס / ג'ארוויס / ג'רביס …)
const WAKE_RE = lang === "he"
  ? /(?:היי?\s*)?ג['׳]?[אי]?ר[ובו]{1,2}י?ס/
  : /(?:hey\s*|hi\s*|ok\s*)?jarvis/i;

if (SR) {
  wakeRec = new SR();
  wakeRec.lang = "he-IL";
  wakeRec.continuous = true;
  wakeRec.interimResults = false;
  wakeRec.onstart = () => { wakeActive = true; updateWakeHint(); };
  wakeRec.onend = () => { wakeActive = false; updateWakeHint(); };
  wakeRec.onerror = (e) => {
    wakeActive = false;
    if (e.error === "not-allowed") { wakeMode = false; updateWakeUI(); }
  };
  wakeRec.onresult = (e) => {
    const t = e.results[e.results.length - 1][0].transcript.trim();
    const m = t.match(WAKE_RE);
    if (!m) return;
    const command = t.slice(t.indexOf(m[0]) + m[0].length).trim();
    try { wakeRec.stop(); } catch {}
    chime();
    if (command.length > 2) send(command);
    else startListening();
  };
}

function updateWakeHint() {
  if (wakeActive && !busy && !recognizing && !window.speechSynthesis.speaking) {
    orbHint.textContent = lang === "he" ? "👂 מחכה ל\"היי ג'רוויס\"…" : "👂 Waiting for \"Hey Jarvis\"…";
  }
}
const wakeToggle = document.getElementById("wake-toggle");
function updateWakeUI() { wakeToggle.classList.toggle("active", wakeMode); }
if (!SR) { wakeToggle.disabled = true; wakeToggle.title = "לא נתמך בדפדפן הזה"; }
updateWakeUI();
wakeToggle.addEventListener("click", () => {
  wakeMode = !wakeMode;
  localStorage.setItem("jarvis-wake", wakeMode ? "on" : "off");
  updateWakeUI();
  if (!wakeMode && wakeActive) { try { wakeRec.stop(); } catch {} setOrb("", ""); }
});

// keep the wake listener alive when idle, paused while Jarvis works or speaks
setInterval(() => {
  if (!wakeRec) return;
  const shouldRun = wakeMode && !recognizing && !busy && !window.speechSynthesis.speaking;
  if (shouldRun && !wakeActive) { try { wakeRec.start(); } catch {} }
  if (!shouldRun && wakeActive) { try { wakeRec.stop(); } catch {} }
}, 800);

/* conversation mode: auto-listen again after Jarvis finishes speaking */
function maybeRelisten() {
  if (convoMode && recognition && !busy) setTimeout(startListening, 350);
}
convoToggle.classList.toggle("active", convoMode);
convoToggle.addEventListener("click", () => {
  convoMode = !convoMode;
  convoToggle.classList.toggle("active", convoMode);
  localStorage.setItem("jarvis-convo", convoMode ? "on" : "off");
});

/* ---------- input events ---------- */
sendBtn.addEventListener("click", () => { send(input.value); input.value = ""; });
input.addEventListener("keydown", (e) => { if (e.key === "Enter") { send(input.value); input.value = ""; } });

/* ---------- init ---------- */
if (window.speechSynthesis) {
  window.speechSynthesis.getVoices();
  window.speechSynthesis.onvoiceschanged = updateVoiceWarning;
  setTimeout(updateVoiceWarning, 1500);
}
function greet() {
  // revealed a character at a time — the HUD "booting up" moment
  const el = addMsg("jarvis", "");
  typewrite(el, lang === "he"
    ? "שלום! אני ג'רוויס. אני יכול לפתוח תוכנות, לרשום פתקים, לקבוע תזכורות, ולשחק מיינקראפט. נסה: \"מה השעה?\" או \"תכרות עץ במיינקראפט\"."
    : "Hi! I'm Jarvis. I can open apps, take notes, set reminders, check your PC, and play Minecraft with you. Try: \"what time is it?\", \"chop some wood in Minecraft\", or \"teach yourself to make a pickaxe\".");
}

/* ---------- language switch ---------- */
const langToggle = document.getElementById("lang-toggle");
document.getElementById("lang-label").textContent = lang === "he" ? "עב" : "EN";
document.getElementById("wake-label").textContent = lang === "he" ? "היי ג'רוויס" : "Hey Jarvis";
document.getElementById("text-input").placeholder = lang === "he" ? "כתוב הודעה לג'רוויס…" : "Type a message to Jarvis…";
document.getElementById("send-btn").textContent = lang === "he" ? "שלח" : "Send";
if (lang !== "he") {
  document.documentElement.lang = "en";
  document.documentElement.dir = "ltr";
  orbHint.textContent = "Click the core to talk, or type below";
}
langToggle.addEventListener("click", () => {
  localStorage.setItem("jarvis-lang", lang === "he" ? "en" : "he");
  localStorage.removeItem("jarvis-history");
  location.reload();
});
if (!loadHistory()) greet();

/* ================= desktop shell integration ================= */
// Present only when running inside the Electron app; the page still works
// as a plain browser tab without it.
const desktop = window.jarvisDesktop || null;
document.body.classList.toggle("web", !desktop);

if (desktop) {
  document.getElementById("min-btn").addEventListener("click", () => desktop.minimize());
  document.getElementById("close-btn").addEventListener("click", () => desktop.close());
  document.getElementById("overlay-btn").addEventListener("click", () => desktop.toggleOverlay());

  // The global hotkey lands here — start listening straight away.
  desktop.onStartListening(() => startListening());
  desktop.onOverlayChanged((on) => document.body.classList.toggle("overlay", on));
  desktop.isOverlay().then((on) => document.body.classList.toggle("overlay", !!on));
} else {
  // no shell to drive: hide the window controls, keep the overlay button out
  for (const id of ["min-btn", "close-btn", "overlay-btn"]) {
    const el = document.getElementById(id);
    if (el) el.style.display = "none";
  }
}

/* starter suggestion chips */
for (const btn of document.querySelectorAll(".suggestion")) {
  btn.addEventListener("click", () => {
    const text = btn.dataset.say || "";
    if (text.endsWith(": ")) {           // an open-ended prompt: let them finish it
      input.value = text;
      input.focus();
      hideSuggestions();
    } else {
      hideSuggestions();
      send(text);
    }
  });
}

/* localise the chrome that lives outside app logic */
if (lang === "he") {
  document.getElementById("convo-toggle").innerHTML = "🔁 מצב שיחה";
  document.getElementById("orb").title = "לחץ כדי לדבר — או Ctrl+Shift+J מכל מקום";
  const map = {
    "What's my PC status?": "💻 מה מצב המחשב?",
    "Remind me in 10 minutes to take a break": "⏰ תזכיר לי בעוד 10 דקות",
    "Take a note: ": "📝 רשום פתק",
    "What's in your Minecraft inventory?": "⛏ מצב מיינקראפט",
  };
  for (const btn of document.querySelectorAll(".suggestion")) {
    if (map[btn.dataset.say]) btn.textContent = map[btn.dataset.say];
  }
}

/* ================= local speech-to-text (Whisper) ================= */
// The browser's speech API sends audio to Google and does not work at all in
// Electron (no API key). Recording here and transcribing on the local server
// keeps voice input private and makes it work in the desktop app.
const USE_LOCAL_STT = !!desktop || localStorage.getItem("jarvis-local-stt") === "on";

let mediaRecorder = null;
let recordedChunks = [];
let recordingStream = null;

async function startLocalRecording() {
  if (mediaRecorder || busy) return;
  try {
    recordingStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch {
    addMsg("jarvis", lang === "he" ? "אין הרשאת מיקרופון." : "No microphone permission.", true);
    return;
  }
  recordedChunks = [];
  mediaRecorder = new MediaRecorder(recordingStream, { mimeType: "audio/webm" });
  mediaRecorder.ondataavailable = (e) => { if (e.data.size) recordedChunks.push(e.data); };
  mediaRecorder.onstop = onLocalRecordingStopped;
  mediaRecorder.start();
  recognizing = true;
  micBtn.classList.add("on");
  setOrb("listening", lang === "he" ? "מקשיב… לחץ שוב כדי לסיים" : "Listening… click again to finish");
  silenceWatch();
}

function stopLocalRecording() {
  if (!mediaRecorder) return;
  try { mediaRecorder.stop(); } catch {}
  if (recordingStream) recordingStream.getTracks().forEach((t) => t.stop());
  mediaRecorder = null;
  recordingStream = null;
  recognizing = false;
  micBtn.classList.remove("on");
  resetMicLevel();
}

// Stop on a couple of seconds of quiet so you don't have to click twice.
function silenceWatch() {
  if (!recordingStream) return;
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const src = ctx.createMediaStreamSource(recordingStream);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 512;
  src.connect(analyser);
  const data = new Uint8Array(analyser.frequencyBinCount);
  const started = Date.now();
  let lastLoud = Date.now();

  const tick = () => {
    if (!mediaRecorder) { ctx.close().catch(() => {}); return; }
    analyser.getByteFrequencyData(data);
    const level = data.reduce((a, b) => a + b, 0) / data.length;
    setMicLevel(level / 60);          // feed the HUD ring
    if (level > 12) lastLoud = Date.now();
    const quietFor = Date.now() - lastLoud;
    const elapsed = Date.now() - started;
    if ((elapsed > 1500 && quietFor > 1800) || elapsed > 20000) {
      ctx.close().catch(() => {});
      stopLocalRecording();
      return;
    }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

async function onLocalRecordingStopped() {
  const blob = new Blob(recordedChunks, { type: "audio/webm" });
  recordedChunks = [];
  if (blob.size < 2000) { setOrb("", ""); return; }   // too short to be speech
  setOrb("thinking", lang === "he" ? "מתמלל…" : "Transcribing…");
  try {
    const res = await fetch("/stt", {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream", "X-Language": lang === "he" ? "he" : "en" },
      body: blob,
    });
    const out = await res.json();
    if (out.error) {
      addMsg("jarvis", (lang === "he" ? "תמלול נכשל: " : "Transcription failed: ") + out.error, true);
      setOrb("", "");
    } else if (out.text) {
      send(out.text);
    } else {
      setOrb("", lang === "he" ? "לא שמעתי כלום" : "I didn't catch that");
      maybeRelisten();
    }
  } catch (e) {
    addMsg("jarvis", (lang === "he" ? "תמלול נכשל: " : "Transcription failed: ") + e.message, true);
    setOrb("", "");
  }
}

// Route the existing controls through whichever engine is active.
if (USE_LOCAL_STT) {
  startListening = function () {
    if (busy || mediaRecorder) return;
    window.speechSynthesis.cancel(); stopVoice();
    startLocalRecording();
  };
  toggleMic = function () {
    if (window.speechSynthesis.speaking || currentVoiceSource) { window.speechSynthesis.cancel(); stopVoice(); setOrb("", ""); return; }
    if (mediaRecorder) stopLocalRecording();
    else startListening();
  };
  micBtn.disabled = false;
  micBtn.title = lang === "he" ? "הקלטה קולית (Whisper מקומי)" : "Voice input (local Whisper)";
}

// The browser wake word can't work in Electron, but the server now runs a real
// local detector ("hey jarvis" via openWakeWord), so the button drives that.
if (desktop) {
  wakeMode = false;
  wakeToggle.disabled = false;
  wakeToggle.classList.remove("active");
  wakeToggle.title = lang === "he"
    ? 'האזנה מקומית ברקע — אמור "Hey Jarvis"'
    : 'Local background listening — say "Hey Jarvis"';
  document.getElementById("wake-label").textContent = "Hey Jarvis";

  let localWakeOn = false;
  wakeToggle.addEventListener("click", async (e) => {
    e.stopImmediatePropagation();          // don't also run the browser handler
    localWakeOn = !localWakeOn;
    wakeToggle.disabled = true;
    try {
      const res = await fetch("/tool", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "wake_word", args: { on: localWakeOn } }),
      });
      const out = await res.json();
      if (out.error) {
        localWakeOn = false;
        addMsg("jarvis", (lang === "he" ? "מילת ההערה לא זמינה: " : "Wake word unavailable: ") + out.error, true);
      }
    } catch { localWakeOn = false; }
    wakeToggle.disabled = false;
    wakeToggle.classList.toggle("active", localWakeOn);
  }, true);
}

/* ================= HUD: telemetry, level ring, typewriter ================= */

/* --- live readouts along the top --- */
const tCpu = document.getElementById("t-cpu");
const tMem = document.getElementById("t-mem");
const tModel = document.getElementById("t-model");
const tClock = document.getElementById("t-clock");

if (tModel) tModel.textContent = MODEL.split(":")[0];

function tickClock() {
  if (!tClock) return;
  const d = new Date();
  tClock.textContent = String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
}
tickClock();
setInterval(tickClock, 20000);

// system_stats shells out to PowerShell, so poll it gently
async function pollTelemetry() {
  try {
    const r = await fetch("/tool", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "system_stats", args: {} }),
    });
    const s = await r.json();
    if (tCpu && s.cpu_percent != null) {
      tCpu.textContent = s.cpu_percent + "%";
      tCpu.classList.toggle("warn", parseInt(s.cpu_percent, 10) > 85);
    }
    if (tMem && s.ram_used_gb && s.ram_total_gb) {
      tMem.textContent = s.ram_used_gb + "/" + s.ram_total_gb + "G";
      tMem.classList.toggle("warn", parseFloat(s.ram_used_gb) / parseFloat(s.ram_total_gb) > 0.9);
    }
  } catch { /* server not up yet; try again next tick */ }
}
pollTelemetry();
setInterval(pollTelemetry, 20000);

/* --- the ring that swells with your voice --- */
const levelRing = document.getElementById("level-ring");
function setMicLevel(level01) {
  if (!levelRing) return;
  const s = 0.9 + Math.min(1, level01) * 0.42;
  levelRing.style.transform = `scale(${s})`;
  levelRing.style.opacity = String(0.35 + Math.min(1, level01) * 0.5);
}
function resetMicLevel() {
  if (levelRing) { levelRing.style.transform = "scale(0.9)"; levelRing.style.opacity = ""; }
}

/* --- reveal Jarvis's replies a character at a time --- */
// Default parameter, not a module-level const: greet() calls this during the
// initial pass, before the consts down here have been initialised.
function typewrite(el, text, revealMs = 12) {
  el.classList.add("typing");
  let i = 0;
  const chunk = Math.max(1, Math.round(text.length / 220)); // keep long replies snappy
  const step = () => {
    if (!el.isConnected) return;
    i = Math.min(text.length, i + chunk);
    el.textContent = text.slice(0, i);
    chatEl.scrollTop = chatEl.scrollHeight;
    if (i < text.length) setTimeout(step, revealMs);
    else el.classList.remove("typing");
  };
  step();
}

// project tool labels for the activity chips
Object.assign(TOOL_LABELS, {
  save_project: "💾 שומר את הפרויקט",
  get_last_project: "📂 נזכר במה עבדנו",
  resume_project: "▶ משחזר את הפרויקט",
  list_projects: "📂 בודק פרויקטים",
});

/* ================= dictation into any app ================= */
// Records with the window hidden and hands the transcript to the shell, which
// types it wherever your cursor already is. Separate from the chat recorder so
// the two can never fight over the microphone.
let dictateRecorder = null;
let dictateStream = null;
let dictateChunks = [];

async function beginDictation() {
  if (dictateRecorder || mediaRecorder) return;
  try {
    dictateStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) {
    desktop.sendDictationResult({ error: "no microphone permission" });
    return;
  }
  dictateChunks = [];
  dictateRecorder = new MediaRecorder(dictateStream, { mimeType: "audio/webm" });
  dictateRecorder.ondataavailable = (e) => { if (e.data.size) dictateChunks.push(e.data); };
  dictateRecorder.onstop = finishDictation;
  dictateRecorder.start();
  watchDictationSilence();
}

function endDictation() {
  if (!dictateRecorder) return;
  try { dictateRecorder.stop(); } catch {}
  if (dictateStream) dictateStream.getTracks().forEach((t) => t.stop());
  dictateRecorder = null;
  dictateStream = null;
}

function watchDictationSilence() {
  if (!dictateStream) return;
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 512;
  ctx.createMediaStreamSource(dictateStream).connect(analyser);
  const data = new Uint8Array(analyser.frequencyBinCount);
  const started = Date.now();
  let lastLoud = Date.now();

  const tick = () => {
    if (!dictateRecorder) { ctx.close().catch(() => {}); return; }
    analyser.getByteFrequencyData(data);
    const level = data.reduce((a, b) => a + b, 0) / data.length;
    if (level > 12) lastLoud = Date.now();
    const elapsed = Date.now() - started;
    // dictation runs longer than a chat command, so allow more silence
    if ((elapsed > 1500 && Date.now() - lastLoud > 2200) || elapsed > 60000) {
      ctx.close().catch(() => {});
      endDictation();
      return;
    }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

async function finishDictation() {
  const blob = new Blob(dictateChunks, { type: "audio/webm" });
  dictateChunks = [];
  if (blob.size < 2000) return desktop.sendDictationResult({ text: "" });
  try {
    const res = await fetch("/stt", {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream", "X-Language": lang === "he" ? "he" : "en" },
      body: blob,
    });
    const out = await res.json();
    desktop.sendDictationResult(out.error ? { error: out.error } : { text: out.text || "" });
  } catch (e) {
    desktop.sendDictationResult({ error: e.message });
  }
}

if (desktop) {
  desktop.onStartDictation(beginDictation);
  desktop.onStopDictation(endDictation);
}

/* ================= Jarvis's voice ================= */
// Windows' built-in voices sound like a satnav. This plays a local Piper
// neural voice instead, through a small audio chain that gives it the
// "speaking from the room's speakers" quality rather than from a phone.

let ttsAvailable = true;          // flipped off if the server can't synthesise
let voiceCtx = null;
let currentVoiceSource = null;

function voiceContext() {
  if (!voiceCtx) voiceCtx = new (window.AudioContext || window.webkitAudioContext)();
  return voiceCtx;
}

// A short synthetic room, so the voice sits in a space instead of on your face.
function makeRoomImpulse(ctx, seconds = 0.9, decay = 3.2) {
  const rate = ctx.sampleRate;
  const len = Math.floor(rate * seconds);
  const impulse = ctx.createBuffer(2, len, rate);
  for (let ch = 0; ch < 2; ch++) {
    const data = impulse.getChannelData(ch);
    for (let i = 0; i < len; i++) {
      data[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, decay);
    }
  }
  return impulse;
}

function buildVoiceChain(ctx, source) {
  // gentle high-pass: takes the boxiness out and suggests a speaker
  const highpass = ctx.createBiquadFilter();
  highpass.type = "highpass";
  highpass.frequency.value = 130;

  // small presence lift around speech intelligibility
  const presence = ctx.createBiquadFilter();
  presence.type = "peaking";
  presence.frequency.value = 2600;
  presence.Q.value = 0.9;
  presence.gain.value = 3.5;

  const compressor = ctx.createDynamicsCompressor();
  compressor.threshold.value = -22;
  compressor.ratio.value = 3;
  compressor.attack.value = 0.004;
  compressor.release.value = 0.18;

  const dry = ctx.createGain(); dry.gain.value = 0.88;
  const wet = ctx.createGain(); wet.gain.value = 0.14;   // just a hint of room
  const reverb = ctx.createConvolver();
  reverb.buffer = makeRoomImpulse(ctx);

  source.connect(highpass);
  highpass.connect(presence);
  presence.connect(compressor);
  compressor.connect(dry).connect(ctx.destination);
  compressor.connect(reverb).connect(wet).connect(ctx.destination);
}

function stopVoice() {
  if (currentVoiceSource) {
    try { currentVoiceSource.onended = null; currentVoiceSource.stop(); } catch {}
    currentVoiceSource = null;
  }
}

async function speakWithPiper(text) {
  const res = await fetch("/tts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, lang }),
  });
  if (!res.ok) throw new Error("tts " + res.status);
  const buf = await res.arrayBuffer();
  const ctx = voiceContext();
  if (ctx.state === "suspended") await ctx.resume();
  const audio = await ctx.decodeAudioData(buf);

  return new Promise((resolve) => {
    stopVoice();
    const source = ctx.createBufferSource();
    source.buffer = audio;
    buildVoiceChain(ctx, source);
    source.onended = () => { currentVoiceSource = null; resolve(); };
    currentVoiceSource = source;
    source.start();
  });
}

/* ================= what Jarvis knows about you ================= */
// Facts are loaded once and folded into the system prompt, so Jarvis simply
// knows you rather than having to look you up mid-sentence.
async function loadUserFacts() {
  try {
    const res = await fetch("/tool", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "recall_facts", args: {} }),
    });
    const out = await res.json();
    if (!out.facts || !out.facts.length) return;

    const header = lang === "he"
      ? "\n\nמה שאתה יודע על המשתמש (השתמש בזה בטבעיות, אל תצטט אותו):\n"
      : "\n\nWhat you know about the user (use it naturally, never recite it back):\n";
    const block = header + out.facts.map((f) => "- " + f).join("\n");

    // history[0] is the system message the conversation runs on
    if (history[0] && history[0].role === "system") history[0].content += block;
  } catch { /* no memory is survivable; a broken startup is not */ }
}
loadUserFacts();

Object.assign(TOOL_LABELS, {
  see_screen: "👁 מסתכל על המסך…",
  free_gpu: "🧹 מפנה את הכרטיס",
  remember_fact: "🧠 זוכר את זה",
  recall_facts: "🧠 נזכר במה שאני יודע עליך",
  forget_fact: "🧠 שוכח",
});

/* ================= tools borrowed from MCP servers ================= */
// Everything Jarvis could do used to be hand-written in server.py. MCP servers
// publish their own tools, so this pulls them in at startup and hands them to
// the model alongside the built-ins.
async function loadMcpTools() {
  try {
    const res = await fetch("/mcp-tools", { method: "POST" });
    const out = await res.json();
    if (!out.tools || !out.tools.length) return;

    for (const def of out.tools) {
      if (TOOL_DEFS.some((t) => t.function.name === def.function.name)) continue;
      TOOL_DEFS.push(def);
      TOOL_NAMES.add(def.function.name);
      const [server] = def.function.name.split("__");
      TOOL_LABELS[def.function.name] = `🔌 ${server}: ${def.function.name.split("__")[1] || ""}`;
    }

    const names = out.tools.map((t) => t.function.name).join(", ");
    const note = lang === "he"
      ? `\n\nכלים נוספים משרתי MCP (השתמש בהם כמו בכל כלי אחר): ${names}`
      : `\n\nExtra tools from MCP servers (use them like any other tool): ${names}`;
    if (history[0] && history[0].role === "system") history[0].content += note;

    console.log(`MCP: added ${out.tools.length} tools`);
  } catch { /* MCP is optional; Jarvis works fine without it */ }
}
loadMcpTools();
