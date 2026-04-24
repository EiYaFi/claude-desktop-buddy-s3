# Claude Code Bridge for claude-desktop-buddy

Let your M5Stick buddy (or any device speaking the [BLE protocol from
REFERENCE.md](../../REFERENCE.md)) talk to **Claude Code** instead of the
Claude desktop app.

## How it works

```
                +----------------+
  Claude Code → |  hook.py       |  (runs per event, short-lived)
                +-------+--------+
                        |  unix socket  /tmp/claude-buddy.sock
                        v
                +----------------+
                |  bridge.py     |  (long-running daemon)
                +-------+--------+
                        |  BLE NUS (Nordic UART Service)
                        v
                +----------------+
                |  M5StickS3     |  (unchanged firmware)
                +----------------+
```

- `bridge.py` runs in the background, connects to the device, and holds
  the BLE session. It mirrors the heartbeat schema the firmware already
  understands, so **no firmware changes are needed** — the device can't
  tell whether the other end is Claude Desktop or Claude Code.
- `hook.py` is invoked once per Claude Code hook event. It forwards the
  event to `bridge.py` over a Unix socket. For `PreToolUse` with `--gate`,
  it blocks until the device returns approve/deny and emits the matching
  Claude Code `permissionDecision` JSON.

If the bridge is down or the device is gone, hooks fall through silently —
Claude Code's normal permission flow still works. This is a strictly
additive layer.

## What you get on the device

| Claude Code event      | Effect on device |
| ---------------------- | ---------------- |
| `SessionStart`         | Session counter ticks up; buddy wakes |
| `UserPromptSubmit`     | `running` flag set; recent entries show `> <prompt>` |
| `PreToolUse` + `--gate`| **Blocks** for device approve/deny; buddy shows tool + hint |
| `PreToolUse` (no gate) | Passive: entries show `… <tool summary>` |
| `PostToolUse`          | Entries show `✓ <tool summary>` |
| `Notification`         | Entries show `! <message>` |
| `Stop`                 | Session marked idle |
| `SessionEnd`           | Session counter ticks down |

## Quick start (recommended)

```bash
cd tools/claude-code-bridge
./setup.sh
```

This creates a Python venv at `~/.claude-buddy-venv`, installs `bleak`,
writes a launchd agent, and merges the hook config into
`~/.claude/settings.json`. Re-running is safe — it's idempotent.

You still need to (once per machine): grant Bluetooth permission to your
terminal in **System Settings → Privacy & Security → Bluetooth**, flash
the device (`pio run -e m5stick-s3 -t upload -t uploadfs` from the repo
root), and pair once via Claude Desktop before quitting it. The script
prints a reminder of these steps at the end.

## Setup (manual)

### 1. Install dependencies

Python 3.10+ and `bleak`:

```bash
cd tools/claude-code-bridge
python3 -m pip install -r requirements.txt
```

On macOS, the first run will trigger a Bluetooth permission prompt for your
terminal — grant it.

### 2. Pair the device once

If you haven't already paired with the Claude desktop app, you can still
use it here — the firmware uses **LE Secure Connections** with bonding.
Easiest flow:

1. Pair through the Claude desktop app first (Developer → Open Hardware
   Buddy → Connect) so macOS stores the bond.
2. Quit the Claude desktop app (so it releases the BLE connection).
3. Start `bridge.py`; it reuses the OS-stored bond.

Or, pair directly: the first time `bridge.py` connects, the device shows a
6-digit passkey that macOS will prompt you to enter.

### 3. Start the bridge

```bash
./bridge.py -v
```

Flags:

| Flag | Default | Meaning |
| --- | --- | --- |
| `--name-prefix` | `Claude` | BLE scan filter prefix |
| `--socket` | `$XDG_RUNTIME_DIR/claude-buddy.sock` or `/tmp/claude-buddy.sock` | IPC path |
| `--owner` | `$USER` | Name shown under the pet |
| `-v` / `--verbose` | off | Log BLE + IPC activity |

The bridge auto-reconnects on BLE drops, so you can leave it running.

### 4. Wire up Claude Code hooks

Copy `settings.example.json` and merge the `hooks` block into
`~/.claude/settings.json` (or your project's `.claude/settings.json`).
**Replace every `/ABSOLUTE/PATH/TO/...`** with your checkout path.

Quick test after editing settings:

```bash
# in any directory, start Claude Code
claude
# > run `ls` in a shell
```

The M5Stick screen should:

1. Show `> run ls in a shell` in the scrolling entries on `UserPromptSubmit`.
2. Light up an `approve: Bash` prompt with the command hint when Claude
   wants to run `ls`.
3. Approve or deny from the device buttons — Claude Code respects it.

### 5. (Optional) Run as a launchd service on macOS

A minimal plist, written once to
`~/Library/LaunchAgents/com.claude.buddy-bridge.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.claude.buddy-bridge</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/env</string>
    <string>python3</string>
    <string>/ABSOLUTE/PATH/TO/tools/claude-code-bridge/bridge.py</string>
    <string>-v</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/claude-buddy.out.log</string>
  <key>StandardErrorPath</key><string>/tmp/claude-buddy.err.log</string>
</dict>
</plist>
```

Load:

```bash
launchctl load ~/Library/LaunchAgents/com.claude.buddy-bridge.plist
```

## Which events to gate with `--gate`?

The example settings only gate **`Bash|Edit|Write|NotebookEdit`** — the
tools most likely to need a human in the loop. Gate too aggressively and
every `Read` / `Glob` / `Grep` will wait on a button press; that's
probably not what you want.

To gate everything, drop the `matcher` field.

## Troubleshooting

**Python crashes on startup with exit code 134 (SIGABRT)**: Python 3.14 has
known incompatibilities with `bleak`'s CoreBluetooth bindings on macOS. Use
Python 3.12 or 3.13:

```bash
python3.13 -m venv ~/.buddy-venv
~/.buddy-venv/bin/pip install -r requirements.txt
~/.buddy-venv/bin/python bridge.py -v
```

**Python crashes silently without a permission dialog**: macOS TCC is
blocking Bluetooth access before the process can prompt. Open **System
Settings → Privacy & Security → Bluetooth**, click `+`, add your terminal
app (Terminal / iTerm), and toggle it on.

**`bleak` can't find device**: make sure the Claude desktop app isn't
holding the connection. Only one BLE central can own the device at a time.
Quit the desktop app before starting the bridge.

**Permission decisions time out on device**: bump `PROMPT_TIMEOUT` at the
top of `hook.py`, or increase the hook `timeout` in `settings.json`.

**Buddy shows `no claude connected`**: the bridge either isn't running or
hasn't reached the device yet. Try `./bridge.py -v` in the foreground to
see what's happening.

**macOS Bluetooth permission**: on first run, macOS prompts your terminal
app. If you missed the prompt, reset it with:
```bash
tccutil reset Bluetooth
```
and re-run the bridge.

## Known limitations

- **No transcript snippets**: the Claude desktop app streams recent
  assistant messages to the device; Claude Code hooks don't expose that
  firehose, so the `entries` list is built from hook-visible summaries
  (prompts, tool calls, notifications). Feels less chatty than the desktop
  experience.
- **Token counts are approximate**: Claude Code doesn't surface token
  counts in hooks. `tokens` and `tokens_today` stay at 0 unless you wire
  up a separate counter.
- **One device at a time**: the bridge connects to the first device whose
  name starts with the `--name-prefix`. If you have multiple, either use a
  more specific prefix (e.g. `Claude-ABCD`) or run multiple bridges on
  different sockets.
