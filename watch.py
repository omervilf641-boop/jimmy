"""
The part of Jarvis that notices things without being asked.

Everything else in this project waits to be spoken to. This runs on its own
clock, looks at a handful of things that are worth looking at, and almost always
finds nothing — which is the point. A background loop that talks is a background
loop you turn off within a week.

Four rules it is built around, each of them a way this normally fails:

  Only speak when something *changes*. A disk that has been full for three days
  is not news three days running. Every check reports ok or not-ok, and a notice
  is raised on the edge between them — and again on the way back, quietly, so
  you know it recovered.

  Hold what nobody was there to hear. A notice raised while the window was shut
  is still waiting when it opens. This is the same mechanism the reminders use,
  and for the same reason: the alternative is a proactive feature that silently
  does nothing, which is worse than not having one.

  Remember when each check is next due, on disk. A restart that refires every
  check is a restart that tells you the disk is full for the fourth time.

  Never stack. If a check is still running when its next turn comes round, it
  is skipped rather than started twice.

The checks themselves live at the bottom and are deliberately few. A watcher
that watches twenty things is a watcher nobody reads.
"""
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request

WATCH_TICK = 20            # seconds between looks at the schedule


# ---------------------------------------------------------------- storage

class Store:
    """Small JSON files, written whole. There is no concurrency here worth a
    database, and a file you can open in Notepad is a file you can fix."""

    def __init__(self, path, empty):
        self.path = path
        self.empty = empty
        self.lock = threading.Lock()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, ValueError):
            return json.loads(json.dumps(self.empty))

    def save(self, data):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)


DEFAULT_CONFIG = {
    "_comment": "Edit this file to change what Jarvis watches. It is re-read on "
                "every tick, so no restart is needed.",
    "paused": False,
    "quiet_hours": {"from": "23:00", "to": "07:30"},
    "checks": {
        "disk":      {"every_minutes": 30, "free_gb_below": 20},
        "gpu":       {"every_minutes": 5,  "used_percent_above": 92},
        "ollama":    {"every_minutes": 5},
        "minecraft": {"every_minutes": 2,  "deaths_per_check_above": 2},
    },
}


class Watch:
    def __init__(self, data_dir, log):
        self.config = Store(os.path.join(data_dir, "watch.json"), DEFAULT_CONFIG)
        self.state = Store(os.path.join(data_dir, "watch_state.json"),
                           {"checks": {}, "paused": False})
        self.notices = Store(os.path.join(data_dir, "notices.json"), [])
        self.log = log
        self.running = set()          # checks in flight, so none is started twice
        self.thread = None

        if not os.path.exists(self.config.path):
            self.config.save(DEFAULT_CONFIG)

    # ------------------------------------------------------------ notices

    def raise_notice(self, check, text, level="notice"):
        now = time.time()
        item = {
            "id": f"n{int(now * 1000)}",
            "check": check,
            "text": text,
            "level": level,          # "notice" surfaces; "log" only ever sits in the log
            "made": now,
            "delivered": False,
            "dismissed": False,
        }
        with self.notices.lock:
            items = self.notices.load()
            items.append(item)
            # A month of history is plenty and keeps the file readable.
            cutoff = now - 30 * 86400
            items = [n for n in items if n["made"] > cutoff]
            self.notices.save(items)
        self.log("watch", f"{check}: {text}")
        return item

    def due_notices(self, claim=True):
        """What is waiting to be said. Claiming stops two windows both saying it."""
        out = []
        with self.notices.lock:
            items = self.notices.load()
            changed = False
            for n in items:
                if n["delivered"] or n["dismissed"] or n["level"] != "notice":
                    continue
                # Nothing wakes you up at three in the morning. It waits.
                if self.in_quiet_hours():
                    continue
                out.append({"id": n["id"], "check": n["check"], "text": n["text"],
                            "waited": int(time.time() - n["made"])})
                if claim:
                    n["delivered"] = True
                    changed = True
            if changed:
                self.notices.save(items)
        return out

    def recent(self, limit=25):
        with self.notices.lock:
            items = [n for n in self.notices.load() if not n["dismissed"]]
        items.sort(key=lambda n: -n["made"])
        return [{"id": n["id"], "check": n["check"], "text": n["text"],
                 "level": n["level"], "ago_minutes": int((time.time() - n["made"]) / 60)}
                for n in items[:limit]]

    def dismiss(self, notice_id):
        with self.notices.lock:
            items = self.notices.load()
            hit = next((n for n in items if n["id"] == notice_id), None)
            if not hit:
                return False
            hit["dismissed"] = True
            self.notices.save(items)
        return True

    # ------------------------------------------------------------ schedule

    def in_quiet_hours(self):
        cfg = self.config.load().get("quiet_hours") or {}
        start, end = cfg.get("from"), cfg.get("to")
        if not start or not end:
            return False
        try:
            now = time.localtime()
            mins = now.tm_hour * 60 + now.tm_min
            sh, sm = (int(x) for x in start.split(":"))
            eh, em = (int(x) for x in end.split(":"))
            a, b = sh * 60 + sm, eh * 60 + em
        except (ValueError, AttributeError):
            return False
        return (a <= mins or mins < b) if a > b else (a <= mins < b)

    def paused(self):
        return bool(self.config.load().get("paused") or self.state.load().get("paused"))

    def set_paused(self, value):
        st = self.state.load()
        st["paused"] = bool(value)
        self.state.save(st)
        return st["paused"]

    def status(self):
        cfg, st = self.config.load(), self.state.load()
        now = time.time()
        checks = []
        for name, opts in (cfg.get("checks") or {}).items():
            saved = (st.get("checks") or {}).get(name, {})
            due = saved.get("next_due", 0)
            checks.append({
                "name": name,
                "every_minutes": opts.get("every_minutes"),
                "next_in_minutes": max(0, int((due - now) / 60)) if due else 0,
                "last": saved.get("last_result", "not run yet"),
                "ok": saved.get("ok", True),
            })
        return {
            "paused": self.paused(),
            "quiet_now": self.in_quiet_hours(),
            "quiet_hours": cfg.get("quiet_hours"),
            "checks": sorted(checks, key=lambda c: c["name"]),
            "waiting": len(self.due_notices(claim=False)),
        }

    # ------------------------------------------------------------ the loop

    def start(self):
        if self.thread:
            return
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        while True:
            try:
                self.tick()
            except Exception as e:                    # a watcher must not die
                self.log("watch", f"tick failed: {e}")
            time.sleep(WATCH_TICK)

    def tick(self):
        if self.paused():
            return
        cfg = self.config.load()
        st = self.state.load()
        st.setdefault("checks", {})
        now = time.time()
        ran = False

        for name, opts in (cfg.get("checks") or {}).items():
            fn = CHECKS.get(name)
            if not fn or name in self.running:
                continue                              # unknown, or still going
            saved = st["checks"].setdefault(name, {})
            if saved.get("next_due", 0) > now:
                continue

            self.running.add(name)
            try:
                ok, detail = fn(opts, saved)
            except Exception as e:
                ok, detail = True, f"check failed: {e}"   # a broken check is not an alarm
            finally:
                self.running.discard(name)

            was_ok = saved.get("ok", True)
            saved["ok"] = ok
            saved["last_result"] = detail
            saved["checked"] = now
            saved["next_due"] = now + max(1, int(opts.get("every_minutes", 10))) * 60
            ran = True

            # The whole design in three lines: speak on the edge, not the state.
            if was_ok and not ok:
                self.raise_notice(name, detail, "notice")
            elif not was_ok and ok:
                self.raise_notice(name, f"בסדר שוב — {detail}", "log")

        if ran:
            self.state.save(st)


# ---------------------------------------------------------------- the checks
#
# Each returns (ok, detail). `opts` is that check's block from watch.json and
# `memo` is its own slice of saved state, for anything it needs to compare
# against last time.

def _ps(script):
    out = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                         capture_output=True, text=True, timeout=20)
    return out.stdout.strip()


def check_disk(opts, _memo):
    free = _ps("$d=Get-PSDrive C;[math]::Round($d.Free/1GB,0)")
    if not free:
        return True, "לא הצלחתי לקרוא את הדיסק"
    gb = int(float(free))
    floor = int(opts.get("free_gb_below", 20))
    return gb >= floor, f"נשארו {gb}GB פנויים בכונן C (הסף {floor})"


def check_gpu(opts, _memo):
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return True, "אין nvidia-smi"
    line = (out.stdout or "").strip().splitlines()
    if not line:
        return True, "אין תשובה מ-nvidia-smi"
    used, total = (int(x) for x in line[0].split(",")[:2])
    pct = round(used * 100 / max(1, total))
    ceiling = int(opts.get("used_percent_above", 92))
    return pct <= ceiling, f"הזיכרון של הכרטיס על {pct}% ({used}/{total}MB) — free_gpu משחרר אותו"


def check_ollama(_opts, _memo):
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=6) as r:
            models = len(json.load(r).get("models", []))
        return True, f"אולמה עונה, {models} מודלים"
    except (urllib.error.URLError, OSError, ValueError):
        return False, "אולמה לא עונה — בלעדיו אני לא יכול לענות על כלום"


def check_minecraft(opts, memo):
    """Only interesting while the bot is meant to be playing by itself."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:8124/status", timeout=5) as r:
            st = json.load(r)
    except (urllib.error.URLError, OSError, ValueError):
        memo.pop("deaths", None)
        return True, "הגשר לא רץ"
    if not st.get("connected"):
        return True, "הבוט לא מחובר"

    deaths = int(st.get("deaths") or 0)
    before = memo.get("deaths")
    memo["deaths"] = deaths
    if before is None or deaths < before:
        return True, f"{deaths} מיתות עד כה"
    gained = deaths - before
    limit = int(opts.get("deaths_per_check_above", 2))
    if gained > limit:
        return False, (f"הבוט מת {gained} פעמים מאז הבדיקה הקודמת "
                       f"(y={round(st.get('position', {}).get('y', 0))}, "
                       f"{st.get('goal') or 'בלי מטרה'})")
    return True, f"{deaths} מיתות, {gained} מאז הבדיקה הקודמת"


CHECKS = {
    "disk": check_disk,
    "gpu": check_gpu,
    "ollama": check_ollama,
    "minecraft": check_minecraft,
}
