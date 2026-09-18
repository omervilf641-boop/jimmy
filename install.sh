#!/usr/bin/env bash
# Install Jimmy into his own virtualenv and put `jimmy` on your PATH.
#
#   ./install.sh              install with voice support
#   ./install.sh --no-voice   skip the text-to-speech dependency
#
# Nothing is installed system-wide. Everything lives under ~/.jimmy:
#   ~/.jimmy/venv         the install  - delete this to uninstall
#   ~/.jimmy/memory.json  what he remembers about you - kept separate on purpose
#
# Uninstall:  rm -rf ~/.jimmy/venv ~/.local/bin/jimmy
# Forget me:  rm ~/.jimmy/memory.json

set -euo pipefail

JIMMY_HOME="${JIMMY_HOME:-$HOME/.jimmy}"
# The venv is a subfolder so that uninstalling never takes his memory with it.
VENV="$JIMMY_HOME/venv"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXTRAS="[voice]"

[ "${1:-}" = "--no-voice" ] && EXTRAS=""

say() { printf '  %s\n' "$1"; }

echo
echo "🤖 Installing Jimmy"
echo

# --- Python ---------------------------------------------------------------
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "❌ Jimmy needs Python 3.10 or newer (the Claude SDK does)."
    echo "   Install it from https://python.org and run this again."
    exit 1
fi
say "Python: $($PYTHON -V) at $(command -v "$PYTHON")"

# --- virtualenv -----------------------------------------------------------
if [ ! -d "$VENV" ]; then
    "$PYTHON" -m venv "$VENV" || {
        echo "❌ Could not create a virtualenv."
        echo "   On Debian/Ubuntu: sudo apt install python3-venv"
        exit 1
    }
    say "Created a virtualenv at $VENV"
else
    say "Reusing the virtualenv at $VENV"
fi

say "Installing Jimmy and his dependencies..."
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet "$SOURCE_DIR$EXTRAS"

# --- put `jimmy` on PATH --------------------------------------------------
mkdir -p "$BIN_DIR"
ln -sf "$VENV/bin/jimmy" "$BIN_DIR/jimmy"
say "Linked $BIN_DIR/jimmy"

echo
echo "✅ Jimmy is installed."
echo

# --- what still needs doing ----------------------------------------------
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
        echo "⚠️  $BIN_DIR is not on your PATH. Add this to your shell profile:"
        echo "      export PATH=\"\$PATH:$BIN_DIR\""
        echo
        ;;
esac

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "🔑 For his full brain, set an API key (he runs offline without one):"
    echo "      export ANTHROPIC_API_KEY=\"sk-ant-...\""
    echo "   Get one at https://console.anthropic.com/settings/keys"
    echo
fi

if [ -n "$EXTRAS" ]; then
    PLAYER_FOUND=""
    for player in ffplay mpv mpg123 afplay; do
        command -v "$player" >/dev/null 2>&1 && { PLAYER_FOUND="$player"; break; }
    done
    if [ -z "$PLAYER_FOUND" ]; then
        echo "🔊 For voice, install an audio player:"
        case "$(uname -s)" in
            Darwin) echo "      brew install ffmpeg   (macOS also has afplay built in)" ;;
            *)      echo "      sudo apt install ffmpeg      # or: mpv / mpg123" ;;
        esac
        echo
    else
        say "Audio player found: $PLAYER_FOUND"
        echo
    fi
fi

say "He will remember you in $JIMMY_HOME/memory.json"
echo
echo "Start him with:  jimmy"
echo "With his voice:  jimmy --voice"
echo
