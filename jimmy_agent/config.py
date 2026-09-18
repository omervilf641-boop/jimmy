"""
Jimmy's settings - mainly, where his API key lives.

Exporting ANTHROPIC_API_KEY in a shell profile works but is a papercut: it has
to be redone per shell, per machine, and it is easy to get wrong. Jimmy can
instead keep the key in ~/.jimmy/config.json with owner-only permissions.

Resolution order, first hit wins:
  1. ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN in the environment
  2. ~/.jimmy/config.json
  3. an `ant auth login` profile, which the SDK reads by itself
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

CONFIG_NAME = "config.json"
KEY_FIELD = "anthropic_api_key"


def jimmy_home() -> Path:
    """The folder Jimmy keeps everything in."""
    return Path(os.environ.get("JIMMY_HOME") or (Path.home() / ".jimmy"))


def config_path() -> Path:
    return jimmy_home() / CONFIG_NAME


def load() -> Dict[str, Any]:
    """Read the config, returning {} if there isn't one or it's unreadable."""
    path = config_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def save(settings: Dict[str, Any]) -> Path:
    """Write the config atomically, readable only by its owner."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), delete=False, suffix=".tmp"
    )
    try:
        with handle:
            json.dump(settings, handle, indent=2)
        os.chmod(handle.name, stat.S_IRUSR | stat.S_IWUSR)  # 0600 - it holds a secret
        os.replace(handle.name, path)
    except OSError:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise
    return path


def stored_api_key() -> Optional[str]:
    """The key from the config file, if one was saved."""
    key = load().get(KEY_FIELD)
    return key.strip() if isinstance(key, str) and key.strip() else None


def api_key() -> Optional[str]:
    """The key Jimmy should use, environment first."""
    for variable in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        value = os.environ.get(variable)
        if value and value.strip():
            return value.strip()
    return stored_api_key()


def set_api_key(key: str) -> Path:
    """Save a key. An empty value removes the stored one."""
    settings = load()
    key = key.strip()
    if key:
        settings[KEY_FIELD] = key
    else:
        settings.pop(KEY_FIELD, None)
    return save(settings)


def key_source() -> str:
    """Where the active key came from, for status lines."""
    for variable in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        if os.environ.get(variable, "").strip():
            return f"the {variable} environment variable"
    if stored_api_key():
        return str(config_path())
    return "nowhere yet"


def masked_key() -> str:
    """A safe-to-display version of the active key."""
    key = api_key()
    if not key:
        return ""
    return f"{key[:11]}...{key[-4:]}" if len(key) > 18 else "set"
