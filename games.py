"""
What is actually installed, asked rather than assumed.

The tempting version of this feature is a dictionary: seven games, seven paths,
written once. It works on the day it is written and is wrong a week later — a
game gets installed, another gets removed, and the assistant goes on confidently
naming things that are not there. That is the same failure as a model reporting
an action it never took, only slower to notice.

So nothing here is a list of games. It is a list of *places games register
themselves*, and the games are read out of those places every time the answer
could have changed:

  Steam    writes an appmanifest_<id>.acf per installed game, in every library
           folder listed in libraryfolders.vdf. The id is enough to launch it —
           steam://rungameid/<id> — which also means Steam handles updates,
           cloud saves and its own overlay rather than us.
  launchers are found by their install path, and launch by their own protocol
           or executable.

The result is cached for a minute, because a scan touches the disk and a person
asking twice in a row has not installed anything in between.
"""
import os
import re
import subprocess
import time

_cache = {"at": 0.0, "games": []}
CACHE_SECONDS = 60


# Launchers worth knowing about, and how to start them. The path is what proves
# it is installed; the target is what actually runs.
LAUNCHERS = [
    ("Minecraft", ["Microsoft.4297127D64EC6_8wekyb3d8bbwe"], "minecraft:",
     ["מיינקראפט", "מיינקרפט", "מיינקראפט לאנצ'ר"]),
    ("Roblox", [r"%LOCALAPPDATA%\Roblox"], "roblox:",
     ["רובלוקס"]),
    ("VALORANT", [r"C:\Riot Games\VALORANT", r"C:\Riot Games"],
     r"C:\Riot Games\Riot Client\RiotClientServices.exe",
     ["ולורנט", "וולורנט"]),
    ("Epic Games", [r"C:\Program Files (x86)\Epic Games\Launcher"],
     r"C:\Program Files (x86)\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe",
     ["אפיק", "אפיק גיימס"]),
    ("Discord", [r"%LOCALAPPDATA%\Discord"], r"%LOCALAPPDATA%\Discord\Update.exe",
     ["דיסקורד"]),
    ("Steam", [r"C:\Program Files (x86)\Steam"], "steam://open/games",
     ["סטים", "סטיים"]),
]

# Things Steam installs that are not games and nobody ever means.
NOT_A_GAME = re.compile(
    r"redistributable|steamworks|runtime|proton|linux|dedicated server|sdk",
    re.I)


def _expand(p):
    return os.path.expandvars(p)


def _steam_root():
    for key in (r"HKLM:\SOFTWARE\WOW6432Node\Valve\Steam", r"HKCU:\SOFTWARE\Valve\Steam"):
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"(Get-ItemProperty '{key}' -ErrorAction SilentlyContinue).InstallPath"],
                capture_output=True, text=True, timeout=15).stdout.strip()
            if out and os.path.isdir(out):
                return out
        except (OSError, subprocess.SubprocessError):
            pass
    fallback = r"C:\Program Files (x86)\Steam"
    return fallback if os.path.isdir(fallback) else None


def _steam_libraries(root):
    """Every folder Steam keeps games in, not just the one it is installed to."""
    libs = [root]
    vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
    try:
        with open(vdf, encoding="utf-8", errors="replace") as f:
            for path in re.findall(r'"path"\s*"([^"]+)"', f.read()):
                libs.append(path.replace("\\\\", "\\"))
    except OSError:
        pass
    return list(dict.fromkeys(libs))


def _steam_games():
    root = _steam_root()
    if not root:
        return []
    found = {}
    for lib in _steam_libraries(root):
        apps = os.path.join(lib, "steamapps")
        if not os.path.isdir(apps):
            continue
        try:
            names = os.listdir(apps)
        except OSError:
            continue
        for entry in names:
            if not (entry.startswith("appmanifest_") and entry.endswith(".acf")):
                continue
            try:
                with open(os.path.join(apps, entry), encoding="utf-8", errors="replace") as f:
                    body = f.read()
            except OSError:
                continue
            appid = re.search(r'"appid"\s*"(\d+)"', body)
            name = re.search(r'"name"\s*"([^"]+)"', body)
            if not (appid and name) or NOT_A_GAME.search(name.group(1)):
                continue
            found[appid.group(1)] = {
                "name": name.group(1),
                "where": "Steam",
                "launch": f"steam://rungameid/{appid.group(1)}",
                "aliases": [],
            }
    return sorted(found.values(), key=lambda g: g["name"].lower())


def _launchers():
    out = []
    for name, paths, target, aliases in LAUNCHERS:
        for p in paths:
            candidate = _expand(p)
            # The Minecraft launcher lives inside a Packages folder whose full
            # name is long and version-stamped, so match on the fragment.
            if os.sep not in candidate:
                base = os.path.expandvars(r"%LOCALAPPDATA%\Packages")
                hit = os.path.isdir(base) and any(candidate in d for d in os.listdir(base))
            else:
                hit = os.path.exists(candidate)
            if hit:
                out.append({"name": name, "where": "launcher",
                            "launch": _expand(target), "aliases": aliases})
                break
    return out


def all_games(force=False):
    now = time.time()
    if not force and now - _cache["at"] < CACHE_SECONDS and _cache["games"]:
        return _cache["games"]
    games = _launchers() + _steam_games()
    _cache.update(at=now, games=games)
    return games


# Hebrew has no vowels written down and no one spelling for a foreign name, so
# a person asking for Subnautica will type סאבנוטיקה, סבנאוטיקה or סאבנאוטיקה and
# mean the same thing. Transliterating to consonants and comparing loosely is
# what makes those all land on the same game — an alias table would need a line
# per game per spelling, which is a table nobody maintains.
_HEB = {
    "א": "a", "ב": "b", "ג": "g", "ד": "d", "ה": "h", "ו": "u", "ז": "z",
    "ח": "h", "ט": "t", "י": "i", "כ": "k", "ך": "k", "ל": "l", "מ": "m",
    "ם": "m", "נ": "n", "ן": "n", "ס": "s", "ע": "a", "פ": "p", "ף": "p",
    "צ": "ts", "ץ": "ts", "ק": "k", "ר": "r", "ש": "sh", "ת": "t",
}
# Vowels carry almost no information across a transliteration, and dropping them
# is what lets "sabnutika" meet "subnautica" in the middle.
_VOWELS = str.maketrans("", "", "aeiou")


def _translit(text):
    out = []
    for ch in str(text):
        out.append(_HEB.get(ch, ch.lower()))
    return "".join(c for c in "".join(out) if c.isalnum())


def _skeleton(text):
    """Consonants only — what two spellings of the same name have in common."""
    return _translit(text).translate(_VOWELS)


def _norm(s):
    """Compare on letters and digits only, so 'Stumble Guys' matches 'stumbleguys'."""
    return "".join(c for c in str(s).lower() if c.isalnum())


def find(query):
    """The game someone meant, or the reason it is ambiguous.

    Returns (game, alternatives). Exactly one of them is meaningful: a game and
    an empty list, or None and whatever it could not choose between.
    """
    q = _norm(query)
    if not q:
        return None, []
    games = all_games()

    exact = [g for g in games if _norm(g["name"]) == q or any(_norm(a) == q for a in g["aliases"])]
    if len(exact) == 1:
        return exact[0], []

    starts = [g for g in games if _norm(g["name"]).startswith(q)
              or any(_norm(a).startswith(q) for a in g["aliases"])]
    if len(starts) == 1:
        return starts[0], []

    part = [g for g in games if q in _norm(g["name"])
            or any(q in _norm(a) for a in g["aliases"])]
    if len(part) == 1:
        return part[0], []

    # Nothing matched on the letters as typed. Try again on consonants, which is
    # where a Hebrew spelling of an English title and the title itself meet.
    if not (exact or starts or part):
        import difflib
        skel = _skeleton(query)
        if len(skel) >= 3:
            names = {g["name"]: g for g in games}
            scored = []
            for name, g in names.items():
                r = difflib.SequenceMatcher(None, skel, _skeleton(name)).ratio()
                for a in g["aliases"]:
                    r = max(r, difflib.SequenceMatcher(None, skel, _skeleton(a)).ratio())
                scored.append((r, name))
            scored.sort(reverse=True)
            # Only when one candidate is clearly ahead. Two near-identical
            # scores means a guess, and a guess that launches something is worse
            # than a question.
            if scored and scored[0][0] >= 0.72 and (
                    len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.12):
                return names[scored[0][1]], []
            close = [n for r, n in scored if r >= 0.72]
            if close:
                return None, close

    return None, [g["name"] for g in (exact or starts or part)]


def launch(game):
    target = game["launch"]
    # A protocol (steam://, minecraft:) and a path both go through the shell,
    # which is what knows how to handle each.
    subprocess.Popen(["cmd", "/c", "start", "", target], shell=False)
    return game
