# ג'רוויס 🔵

עוזר אישי שרץ **מקומית** על המחשב שלך — בלי ענן, בלי מפתחות API, בלי לשלוח שום דבר החוצה.

## התקנה

הרץ את המתקין מתוך `dist/`:

```
Jarvis Setup 2.0.0.exe
```

זה מתקין את ג'רוויס כאפליקציה אמיתית עם קיצור דרך בשולחן העבודה. אפשר גם להריץ מהמקור:

```bash
npm start
```

### מה צריך להיות מותקן

| | למה |
|---|---|
| [Ollama](https://ollama.com) + `qwen2.5:7b` | המוח של ג'רוויס |
| Python 3 | שרת הכלים והתמלול (`server.py`) |
| `pip install faster-whisper` | זיהוי הדיבור המקומי |

## מה ג'רוויס יודע לעשות

- 💬 שיחה בקול או בטקסט
- ⌨️ **Ctrl+Shift+J מכל מקום** — גם מתוך משחק במסך מלא
- 🕐 שעה, תאריך ויום בשבוע
- 🚀 פתיחת תוכנות: פנקס רשימות, מחשבון, צייר, סייר, כרום, אדג', הגדרות, מצלמה
- 🌐 פתיחת אתרים וחיפוש בגוגל
- 📝 פתקים — "תרשום לי לקנות חלב"
- ⏰ תזכורות — "תזכיר לי בעוד 10 דקות"
- 🔊 עוצמת שמע · 📸 צילום מסך · 🔒 נעילת מחשב
- 💻 מצב המחשב: מעבד, זיכרון, סוללה, דיסק
- ⛏ **מיינקראפט** — שולט בבוט ולומד מיומנויות. ראה [mc-jarvis](../mc-jarvis/README.md)

## מילת הערה: "Hey Jarvis" 👂

לחץ על 👂 בסרגל, ואז פשוט אמור **"Hey Jarvis"** — הוא יקפוץ ויתחיל להקשיב, בלי לגעת בכלום.

הזיהוי רץ על מודל ייעודי (openWakeWord, שמגיע עם מודל מאומן ל-"hey jarvis"). האודיו **לא נשמר ולא יוצא מהמחשב** — כל פריים של 80ms מנוקד ונזרק.

> **מה נבדק:** המודל נותן ציון **0.998** להקלטה נקייה של הביטוי (סף 0.55), המיקרופון קולט, והמאזין יציב. **מה לא נבדק:** קול אנושי אמיתי — ניסיתי להשמיע דרך הרמקולים והמיקרופון קלט את זה מעוות מדי (0.060). תנסה ותגיד.

לכיול רגישות: `set JARVIS_WAKE_THRESHOLD=0.4` (נמוך יותר = רגיש יותר, גם ליותר טעויות).

## מקשי קיצור

| מקש | מה קורה |
|---|---|
| `Ctrl+Shift+J` | ג'רוויס קופץ ומתחיל להקשיב — **מכל מקום במחשב** |
| `Ctrl+Shift+D` | **הכתבה**: דבר, והטקסט מוקלד לתוך התוכנה שפתוחה |
| `Ctrl+Shift+O` | מצב שכבה: חלון קטן שנשאר מעל משחקים |

### הכתבה לכל מקום

לחץ `Ctrl+Shift+D` בכל תוכנה — ווטסאפ, וורד, שדה חיפוש — דבר, ועצור. הטקסט יוקלד בדיוק במקום שהסמן שלך נמצא. החלון של ג'רוויס לא נפתח ולא גונב פוקוס.

**זה עובד מצוין בעברית**, בניגוד להקראה. ההקלדה נעשית דרך `SendInput` של Windows ולא דרך הלוח, כי `SendKeys` איבד מקשים בבדיקות (Ctrl+V הגיע כ-`v` בלבד) ולא ידע לכתוב עברית כלל.

## זיכרון פרויקטים

אמור **"I'm back"** (או "חזרתי") וג'רוויס יזכיר לך על מה עבדתם וישאל אם לפתוח מחדש. באישור הוא פותח את התוכנות, האתרים, ומעלה את המיינקראפט ברקע.

תוך כדי עבודה הוא שומר את הפרויקט לבד. השמות נשמרים באנגלית — המודל משבש שמות עבריים כשהוא חוזר עליהם ואז לא מוצא אותם.

## נתוני אימון

כל שיחה נרשמת ל-`traces.jsonl`: מה ביקשת, איזה כלי נקרא ועם אילו ארגומנטים, והאם הצליח. זה החומר לאימון LoRA בהמשך. לבדיקת הכמות שנצברה, שאל את ג'רוויס "how much training data do we have?".

> נתוני המשתמש — פתקים, פרויקטים וטרייסים — נשמרים ב-`%APPDATA%\Jarvis` ולא בתיקיית ההתקנה, כדי שהתקנה מחדש לא תמחק אותם.

הכפתור ✕ סוגר לאזור ההודעות (tray), לא מכבה. לכיבוי מלא: קליק ימני על האייקון ← Quit.

## זיהוי דיבור — למה Whisper ולא הדפדפן

הגרסה הראשונה השתמשה ב-Web Speech API של הדפדפן. שתי בעיות:

1. **הוא שולח את ההקלטות שלך לשרתים של גוגל** — לא בדיוק "עוזר מקומי"
2. **הוא פשוט לא עובד ב-Electron** — נבדק, נכשל עם `error: network`, כי לבניות Electron אין את מפתח ה-API של גוגל

לכן ההקלטה נשלחת ל-`faster-whisper` שרץ אצלך. תמלול פקודה באנגלית לוקח כ-1.2 שניות, והכל נשאר על המחשב.

התמלול רץ על **כרטיס המסך** — כ-280ms לפקודה.

> **מלכודת ששווה לזכור:** על GTX 1660 אין Tensor Cores, ולכן `float16` נמדד ב-**39.9 שניות** מול **0.23 שניות** ל-`int8` על אותה הקלטה. הקוד משתמש ב-`int8` בכוונה. על כרטיס חדש יותר `float16` דווקא עדיף.

**מודל גדול יותר לעברית טובה יותר:**

```bash
set JARVIS_WHISPER=small
```

**לכפות מעבד:**

```bash
set JARVIS_WHISPER_DEVICE=cpu
```

## כלים מבחוץ — MCP 🔌

עד עכשיו כל יכולת של ג'רוויס הייתה כתובה ביד ב-`server.py`. **MCP** (Model Context Protocol) הוא הסטנדרט לשרתי כלים, ועכשיו ג'רוויס יכול להשתמש בכל שרת כזה שהקהילה בנתה.

מוגדר ב-`mcp.json`:

```json
{
  "servers": {
    "files": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:/Users/.../GitHub"]
    }
  }
}
```

השרתים עולים עם ג'רוויס והכלים שלהם מופיעים לו אוטומטית בשם `שרת__כלי`. שאל `what MCP servers do you have?` כדי לראות מה מחובר.

**נבדק:** שרת הקבצים מספק **14 כלים** (קריאה, כתיבה, חיפוש, עץ תיקיות), וקריאה אמיתית דרך האפליקציה החזירה את רשימת קבצי ה-Markdown בפרויקט.

עוד שרתים: [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) — git, בסיסי נתונים, Slack, ועוד. הוסף ל-`mcp.json` והפעל מחדש. `"disabled": true` משאיר שרת מוגדר אבל כבוי.

> **שים לב:** שרת הקבצים מקבל גישת **כתיבה** לתיקייה שתגדיר. תן לו רק מה שאתה מוכן שישתנה.

## הוא רואה את המסך 👁

```
What's this error on my screen?
מה כתוב פה?
```

ג'רוויס מצלם את המסך ושולח אותו למודל ראייה מקומי (`qwen2.5vl:3b`). הכל נשאר במחשב — התמונה לא יוצאת החוצה ונמחקת מיד.

**נבדק:** הוא זיהה נכון את החלונות הפתוחים, את סרגל המשימות, ואפילו קרא התראה קטנה בתחתית המסך.

| | |
|---|---|
| קריאה ראשונה | ~36 שניות (טעינת המודל) |
| אחר כך | ~12 שניות |

להחלפת מודל: `set JARVIS_VISION=llava:7b`

## הוא זוכר אותך 🧠

```
Remember that I study at high school and I prefer everything to run locally
```

העובדות נשמרות ל-`facts.json` ו**נטענות לתוך ההנחיה בכל פתיחה** — כלומר הוא פשוט יודע אותן, בלי לחפש אותן באמצע שיחה. אפשר לשאול `what do you know about me?` או לבקש `forget that I...`.

> **מגבלה ידועה:** בקשה מפורשת ("remember that...") עובדת אמין, כולל כמה עובדות בבת אחת. אמירה אגבית ("I'm in high school") נשמרת רק לפעמים — המודל מסתפק באישור מילולי במקום לקרוא לכלי. יש שומר שתופס חלק מהמקרים ומכריח ניסיון נוסף.

## הקול

ג'רוויס מדבר בקול נוירוני **בריטי** (`en_GB-alan-medium` דרך Piper) שרץ מקומית — לא הקולות הישנים של Windows שנשמעים כמו מכשיר ניווט משנת 2005.

הקול עובר עיבוד קל בדפדפן כדי לתת לו את התחושה של "מדבר מהרמקולים בחדר": סינון תדרים נמוכים, הדגשת נוכחות סביב 2.6kHz, דחיסה קלה ורמז של הד חדר.

**להחליף קול:** הורד מודל מ-[piper-voices](https://huggingface.co/rhasspy/piper-voices) לתיקיית `voices/` והגדר:

```bash
set JARVIS_VOICE=en_GB-northern_english_male-medium
```

**עברית:** יש מודל עברי מותקן — `he_IL-saspeech-medium` — והוא נבחר אוטומטית לפי שפת השיחה.
לשנות אותו: `set JARVIS_VOICE_HE=...`

> את המודלים עצמם (`voices/*.onnx`, כ-60MB כל אחד) לא שומרים בגיט. להוריד מחדש:
> ```bash
> curl -L -o voices/he_IL-saspeech-medium.onnx      https://huggingface.co/rhasspy/piper-voices/resolve/main/he/he_IL/saspeech/medium/he_IL-saspeech-medium.onnx
> curl -L -o voices/he_IL-saspeech-medium.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/main/he/he_IL/saspeech/medium/he_IL-saspeech-medium.onnx.json
> ```

## שפה: אנגלית או עברית

ברירת המחדל **אנגלית**, ולא סתם: המודל המקומי קורא לכלים הרבה יותר אמין באנגלית, ואין קול עברי מותקן במחשב (נבדק — `hebrewVoice: []`). כפתור 🌐 מחליף לעברית ובחזרה.

## קבצים

| קובץ | תפקיד |
|---|---|
| `main.js` | מעטפת הדסקטופ: חלון, tray, מקש קיצור גלובלי, מצב שכבה |
| `preload.js` | הגשר המאובטח בין הדף למעטפת |
| `ui/index.html` · `ui/style.css` · `ui/app.js` | הממשק והלוגיקה |
| `server.py` | שרת הכלים + תמלול Whisper (פורט 8123) |
| `notes.txt` | הפתקים שלך, טקסט רגיל |
| `gen-icon.js` | מייצר את `icon.png` בקוד |

## הגדרות

בראש `ui/app.js`:

- `MODEL` — ברירת מחדל `qwen2.5:7b`. מותקן גם `aya-expanse:8b`, שהעברית שלו יפה יותר **אבל הוא מחזיר תשובות ריקות כשמחוברים כלים** ולכן לא יכול להפעיל כלום.
- `SYSTEM_PROMPT_EN` / `SYSTEM_PROMPT_HE` — האישיות של ג'רוויס.

## פתרון בעיות

- **"Ollama לא זמין"** — הפעל את Ollama מתפריט התחל.
- **תמלול נכשל** — `pip install faster-whisper`. ההרצה הראשונה מורידה את המודל (~140MB).
- **אין קול** — אין קול עברי ב-Windows שלך. השתמש במצב אנגלית, או התקן קול עברי: הגדרות ← זמן ושפה ← דיבור.

## Talking to Jarvis from your phone

The microphone is captured by the browser, not by Python — so the page opened on
a phone uses the *phone's* microphone. No new hardware, and the range is the
whole house.

    set JARVIS_LAN=1
    python server.py

It prints the address to open on the phone and a key. Paste the key once; the
browser remembers it. Without `JARVIS_LAN` nothing changes: the server listens
on localhost only, exactly as before.

Requests from the computer itself never need the key. Requests from anywhere
else always do, on every endpoint — not only the tools. Guarding `/tool` alone
would still have let a stranger on the WiFi make the machine talk through `/tts`
or hand Whisper whatever audio they liked.

## The confirmation gate

Thirty-two tools used to run the instant the model named one. The thing choosing
them is a 7B model running locally, which has already been caught in this
project reporting actions it never performed — and a model that invents a
completed action is a model that can invent `clear_notes`.

Anything destructive, outward-facing or settings-changing now stops and asks.
The check is in the server, because the page is not the only thing that can
reach that endpoint. Approving one action does not approve the next: the token
is tied to those exact arguments, expires in two minutes, and is spent on use.

## The orb on the desk

The printed shell mirrors what the interface already shows. `setOrb` in the page
is called at each of the four moments Jarvis has — listening, thinking,
speaking, waiting — so that one function is the only hook, rather than a second
list of call sites that would quietly go stale.

    set JARVIS_ORB=192.168.1.42
    python server.py

Leave `JARVIS_ORB` unset and nothing changes.

What goes over the wire is the state, not the sound. The board animates the
breathing itself, which keeps the network out of the animation: a dropped packet
costs a state change rather than a stutter, and at a glance nobody can tell a
generic breath from one that follows the syllables.

Repeats are dropped at both ends. The page sends only on a change, and the
server refuses to send the same state twice.

### Testing without the hardware

`orb_stub.py` pretends to be the orb: it listens on the same UDP port and prints
each state with the animation the firmware will have to produce.

    python orb_stub.py

Running it beside Jarvis exercises the whole computer-side path today. When the
board arrives, only the firmware is new — and what it has to reproduce is
already written down.

## Tests

    node test_jarvis.js

Seven checks over the two things that have actually gone wrong: which tools the
model is offered, and what the tool loop does when the model will not stop
asking. No framework, nothing to install.

They were confirmed to be capable of failing — putting a Minecraft tool back
into the always-on list makes the first one fail with "expected 13, got 14" —
because a test that cannot fail is worse than no test at all. Two of these
originally "passed" while returning a promise nobody awaited, which is exactly
that, so `check` now refuses one.
