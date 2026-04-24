#!/usr/bin/env bash
# Sets up claude-desktop-buddy bridge on macOS.
# Idempotent: safe to re-run.
#
# What this does:
#   1. Creates a Python venv at ~/.claude-buddy-venv (Python 3.12 or 3.13)
#   2. Installs bleak + deps
#   3. Writes a launchd plist pointing at this checkout's bridge.py
#   4. Merges Claude Code hooks into ~/.claude/settings.json
#
# What this does NOT do (manual steps):
#   - Flash firmware to the M5StickS3
#   - Grant macOS Bluetooth permission to your terminal
#   - Pair the device over BLE

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BRIDGE_PY="$SCRIPT_DIR/bridge.py"
HOOK_PY="$SCRIPT_DIR/hook.py"
VENV="$HOME/.claude-buddy-venv"
PLIST="$HOME/Library/LaunchAgents/com.claude.buddy-bridge.plist"
SETTINGS="$HOME/.claude/settings.json"
SOCKET="/tmp/claude-buddy.sock"

# --- 1. Pick a supported Python ---
PYTHON=""
for candidate in python3.13 python3.12; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PYTHON="$candidate"
    break
  fi
done

if [ -z "$PYTHON" ]; then
  echo "Error: need Python 3.12 or 3.13 (bleak breaks on 3.14 on macOS)." >&2
  echo "Install with: brew install python@3.13" >&2
  exit 1
fi

echo "[setup] using $PYTHON ($(command -v "$PYTHON"))"

# --- 2. venv + deps ---
if [ ! -x "$VENV/bin/python" ]; then
  echo "[setup] creating venv at $VENV"
  "$PYTHON" -m venv "$VENV"
fi

echo "[setup] installing dependencies"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$SCRIPT_DIR/requirements.txt"

# --- 3. launchd plist ---
mkdir -p "$(dirname "$PLIST")"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.claude.buddy-bridge</string>
  <key>ProgramArguments</key>
  <array>
    <string>$VENV/bin/python</string>
    <string>$BRIDGE_PY</string>
    <string>--socket</string>
    <string>$SOCKET</string>
    <string>-v</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>10</integer>
  <key>StandardOutPath</key>
  <string>/tmp/claude-buddy.out.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/claude-buddy.err.log</string>
</dict>
</plist>
EOF
echo "[setup] wrote $PLIST"

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "[setup] launchd agent loaded"

# --- 4. merge hooks into ~/.claude/settings.json ---
HOOK_GATE="$VENV/bin/python $HOOK_PY --gate --socket $SOCKET"
HOOK_PASS="$VENV/bin/python $HOOK_PY --socket $SOCKET"

mkdir -p "$(dirname "$SETTINGS")"
[ -f "$SETTINGS" ] || echo "{}" > "$SETTINGS"

HOOK_GATE="$HOOK_GATE" HOOK_PASS="$HOOK_PASS" SETTINGS_PATH="$SETTINGS" \
  "$VENV/bin/python" <<'PYEOF'
import json, os
path = os.environ["SETTINGS_PATH"]
gate = os.environ["HOOK_GATE"]
passcmd = os.environ["HOOK_PASS"]

try:
    with open(path) as f:
        cfg = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    cfg = {}

hooks = cfg.setdefault("hooks", {})
hooks["PreToolUse"] = [{
    "matcher": "Bash|Edit|Write|NotebookEdit",
    "hooks": [{"type": "command", "command": gate, "timeout": 90}],
}]
for ev in ("UserPromptSubmit", "Notification", "Stop", "SessionStart", "SessionEnd"):
    hooks[ev] = [{"hooks": [{"type": "command", "command": passcmd}]}]

with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
PYEOF
echo "[setup] hooks merged into $SETTINGS"

# --- 5. done ---
cat <<EOF

============================================
Setup complete. Remaining manual steps:
============================================

1. Grant Bluetooth permission to your terminal:
   System Settings → Privacy & Security → Bluetooth → add Terminal/iTerm
   (If you miss the prompt, reset with: tccutil reset Bluetooth)

2. Flash the M5StickS3 firmware:
   cd $REPO_ROOT
   pio run -e m5stick-s3 -t upload -t uploadfs
   # long-press the side button until green LED blinks to enter download mode
   # short-press after flashing to boot

3. Pair the device once via Claude Desktop, then quit Desktop so the bridge
   can grab the BLE connection. Bridge auto-reconnects after that.

4. Open /hooks in Claude Code (or restart) so the current session picks up
   the new hooks. New sessions get them automatically.

Logs:  tail -f /tmp/claude-buddy.err.log
Unload: launchctl unload $PLIST
EOF
