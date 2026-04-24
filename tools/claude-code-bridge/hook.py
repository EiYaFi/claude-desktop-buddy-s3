#!/usr/bin/env python3
"""
Claude Code hook client for claude-desktop-buddy.

Claude Code invokes this once per hook event; it reads the hook JSON from
stdin, talks to the long-running bridge.py daemon over a Unix socket, and
writes the appropriate response to stdout.

Wire it into ~/.claude/settings.json — see settings.example.json in this
folder for the exact shape. The same binary handles every event type; it
dispatches on the CC_EVENT environment variable (which Claude Code sets,
but you can also pass --event for testing).

Design goals:
  - Never block Claude Code if the bridge is down or the device is gone.
    On any bridge error we fall through with no decision, letting Claude's
    normal prompt flow take over.
  - For PreToolUse, block on the device's approve/deny button and translate
    that into Claude Code's permission-decision JSON.
  - For everything else, fire-and-forget a state update.
"""

import argparse
import json
import os
import socket
import sys
from pathlib import Path

DEFAULT_SOCK = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "claude-buddy.sock"
PROMPT_TIMEOUT = 60            # seconds to wait on device response


def talk(sock_path: Path, req: dict, timeout: float = 90.0) -> dict:
    """Send one JSON request, read one JSON reply."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect(str(sock_path))
    s.sendall((json.dumps(req) + "\n").encode())
    buf = b""
    while b"\n" not in buf:
        chunk = s.recv(4096)
        if not chunk:
            break
        buf += chunk
    s.close()
    line = buf.split(b"\n", 1)[0]
    return json.loads(line.decode()) if line else {"ok": False}


def summarize_tool(tool_name: str, tool_input: dict) -> str:
    """One-line hint shown on the device's small screen."""
    if not tool_input:
        return tool_name
    if tool_name == "Bash":
        return (tool_input.get("command") or "").split("\n", 1)[0]
    if tool_name in ("Edit", "Write", "Read", "NotebookEdit"):
        return tool_input.get("file_path") or tool_input.get("notebook_path") or tool_name
    if tool_name in ("Glob", "Grep"):
        parts = []
        for k in ("pattern", "path", "glob"):
            v = tool_input.get(k)
            if v: parts.append(str(v))
        return " ".join(parts) or tool_name
    if tool_name == "WebFetch":
        return tool_input.get("url") or tool_name
    if tool_name in ("Task", "Agent"):
        return tool_input.get("description") or tool_input.get("subagent_type") or tool_name
    # generic: first string value
    for v in tool_input.values():
        if isinstance(v, str) and v:
            return v
    return tool_name


def handle_pretooluse(hook_input: dict, sock_path: Path) -> int:
    """
    Ask the device to approve/deny. Emit the PreToolUse JSON response
    Claude Code expects.
    """
    tool_name = hook_input.get("tool_name", "?")
    tool_input = hook_input.get("tool_input", {}) or {}
    session_id = hook_input.get("session_id") or "default"

    hint = summarize_tool(tool_name, tool_input)

    try:
        resp = talk(sock_path, {
            "kind": "prompt",
            "id": hook_input.get("hook_event_name", "") + ":" + (hook_input.get("message_id") or ""),
            "tool": tool_name,
            "hint": hint,
            "session_id": session_id,
            "timeout": PROMPT_TIMEOUT,
        })
    except Exception:
        # bridge down → fall through to Claude's default prompt
        return 0

    decision = (resp or {}).get("decision")
    short_hint = (hint or tool_name)[:80]
    if decision == "once":
        out = {
            "systemMessage": f"✓ S3 approved: {tool_name} — {short_hint}",
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": "approved on device",
            },
        }
    elif decision == "deny":
        out = {
            "systemMessage": f"✗ S3 denied: {tool_name} — {short_hint}",
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "denied on device",
            },
        }
    else:
        # timeout / unknown → let Claude prompt the user normally
        return 0

    print(json.dumps(out))
    return 0


def handle_generic(event: str, hook_input: dict, sock_path: Path) -> int:
    """Fire-and-forget state update for non-gating events."""
    tool_name = hook_input.get("tool_name") or ""
    tool_input = hook_input.get("tool_input") or {}
    text = None

    if event == "UserPromptSubmit":
        text = hook_input.get("prompt") or ""
    elif event == "Stop":
        text = "turn done"
    elif event == "Notification":
        text = hook_input.get("message") or "notification"
    elif event == "PostToolUse":
        text = summarize_tool(tool_name, tool_input) if tool_name else None
    elif event == "PreToolUse":
        text = summarize_tool(tool_name, tool_input) if tool_name else None

    try:
        talk(sock_path, {
            "kind": "event",
            "event": event,
            "session_id": hook_input.get("session_id") or "default",
            "text": text or "",
        }, timeout=2.0)
    except Exception:
        pass
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--socket", default=str(DEFAULT_SOCK))
    # CC_EVENT is what Claude Code exposes via env; --event lets us test manually
    p.add_argument("--event", default=os.environ.get("CC_EVENT") or os.environ.get("HOOK_EVENT_NAME"))
    p.add_argument("--gate", action="store_true", help="treat PreToolUse as a gating prompt (block on device)")
    args = p.parse_args()

    sock_path = Path(args.socket)

    try:
        hook_input = json.load(sys.stdin)
    except Exception:
        hook_input = {}

    event = args.event or hook_input.get("hook_event_name") or ""

    if event == "PreToolUse" and args.gate:
        return handle_pretooluse(hook_input, sock_path)

    return handle_generic(event, hook_input, sock_path)


if __name__ == "__main__":
    sys.exit(main())
