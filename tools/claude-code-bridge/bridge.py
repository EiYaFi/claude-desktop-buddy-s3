#!/usr/bin/env python3
"""
claude-desktop-buddy bridge for Claude Code.

Long-running daemon that:
  1. Maintains a BLE connection to the buddy device (Nordic UART Service).
  2. Listens on a Unix socket for hook events from Claude Code.
  3. Translates hook events into heartbeat snapshots the device already
     understands, and routes permission decisions back to the hook that
     asked for them.

Run it once in the background; point your Claude Code hooks at hook.py.
"""

import argparse
import asyncio
import datetime as dt
import json
import os
import signal
import sys
import time
import uuid
from collections import deque
from pathlib import Path

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    print("error: `bleak` not installed. run: pip install bleak", file=sys.stderr)
    sys.exit(1)


NUS_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX      = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"   # desktop -> device
NUS_TX      = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"   # device -> desktop

DEFAULT_SOCK = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "claude-buddy.sock"
DEFAULT_NAME_PREFIX = "Claude"

HEARTBEAT_SEC = 10            # keepalive interval
ENTRIES_CAP   = 10            # recent transcript lines remembered
PROMPT_TIMEOUT_DEFAULT = 60   # seconds to wait for a device decision


def now_hhmm():
    return dt.datetime.now().strftime("%H:%M")


def truncate(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


class DeviceState:
    """Mirrors the heartbeat schema from REFERENCE.md."""

    def __init__(self, owner: str):
        self.owner = owner
        self.sessions: dict[str, dict] = {}     # session_id -> {running, last_tool, ...}
        self.entries: deque[str] = deque(maxlen=ENTRIES_CAP)
        self.tokens_session = 0
        self.tokens_today = 0
        self.tokens_day = dt.date.today()
        self.prompt: dict | None = None         # {id, tool, hint} when blocked
        self.msg_override: str | None = None

    def add_entry(self, text: str):
        self.entries.appendleft(f"{now_hhmm()} {truncate(text, 40)}")

    def tick_tokens(self, n: int):
        today = dt.date.today()
        if today != self.tokens_day:
            self.tokens_day = today
            self.tokens_today = 0
        self.tokens_session += n
        self.tokens_today += n

    def snapshot(self) -> dict:
        total = len(self.sessions)
        running = sum(1 for s in self.sessions.values() if s.get("running"))
        waiting = 1 if self.prompt else 0
        if self.msg_override:
            msg = self.msg_override
        elif waiting:
            msg = f"approve: {self.prompt.get('tool', '?')}"
        elif running:
            msg = "working…"
        else:
            msg = "idle"
        out = {
            "total": total,
            "running": running,
            "waiting": waiting,
            "msg": truncate(msg, 40),
            "entries": list(self.entries),
            "tokens": self.tokens_session,
            "tokens_today": self.tokens_today,
        }
        if self.prompt:
            out["prompt"] = self.prompt
        return out


class Bridge:
    def __init__(self, name_prefix: str, sock_path: Path, owner: str, verbose: bool):
        self.name_prefix = name_prefix
        self.sock_path = sock_path
        self.owner = owner
        self.verbose = verbose

        self.state = DeviceState(owner)
        self.client: BleakClient | None = None
        self.ble_lock = asyncio.Lock()
        self.ble_buffer = b""

        self.pending_prompts: dict[str, asyncio.Future] = {}  # prompt id -> future
        self.dirty = asyncio.Event()                           # set when state changed
        self.stats = {"appr": 0, "deny": 0}

    def log(self, *a):
        if self.verbose:
            print("[bridge]", *a, file=sys.stderr, flush=True)

    # -- BLE -------------------------------------------------------------

    async def ble_connect_loop(self):
        while True:
            try:
                self.log(f"scanning for '{self.name_prefix}...'")
                device = await BleakScanner.find_device_by_filter(
                    lambda d, _ad: (d.name or "").startswith(self.name_prefix),
                    timeout=15.0,
                )
                if not device:
                    self.log("no device found, retrying in 5s")
                    await asyncio.sleep(5)
                    continue

                self.log(f"connecting to {device.name} [{device.address}]")
                async with BleakClient(device) as client:
                    self.client = client
                    await client.start_notify(NUS_TX, self._on_tx)
                    # one-shot-on-connect: time sync + owner name
                    tz_off = -time.timezone + (3600 if time.localtime().tm_isdst else 0)
                    await self._write({"time": [int(time.time()), tz_off]})
                    await self._write({"cmd": "owner", "name": self.owner})
                    await self._push_heartbeat()
                    self.log("connected, heartbeat pushed")

                    # run two concurrent tasks: heartbeat keepalive + dirty-push
                    await asyncio.gather(
                        self._heartbeat_loop(client),
                        self._dirty_loop(client),
                    )
            except Exception as e:
                self.log(f"ble loop error: {e}; reconnecting in 3s")
                self.client = None
                await asyncio.sleep(3)

    async def _heartbeat_loop(self, client):
        while client.is_connected:
            await asyncio.sleep(HEARTBEAT_SEC)
            if client.is_connected:
                await self._push_heartbeat()

    async def _dirty_loop(self, client):
        while client.is_connected:
            await self.dirty.wait()
            self.dirty.clear()
            if client.is_connected:
                await self._push_heartbeat()

    async def _push_heartbeat(self):
        await self._write(self.state.snapshot())

    async def _write(self, obj: dict):
        if not self.client or not self.client.is_connected:
            return
        line = (json.dumps(obj) + "\n").encode()
        async with self.ble_lock:
            # chunk at MTU; bleak handles WriteWithoutResponse but we use write-with-response for reliability
            chunk = 180
            for i in range(0, len(line), chunk):
                await self.client.write_gatt_char(NUS_RX, line[i : i + chunk], response=False)

    def _on_tx(self, _handle, data: bytearray):
        self.ble_buffer += bytes(data)
        while b"\n" in self.ble_buffer:
            line, self.ble_buffer = self.ble_buffer.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line.decode("utf-8", errors="replace"))
            except Exception:
                self.log(f"non-json from device: {line!r}")
                continue
            asyncio.create_task(self._handle_device_msg(obj))

    async def _handle_device_msg(self, obj: dict):
        self.log(f"<- {obj}")
        if obj.get("cmd") == "permission":
            pid = obj.get("id")
            decision = obj.get("decision")
            fut = self.pending_prompts.pop(pid, None)
            if fut and not fut.done():
                fut.set_result(decision)
            if decision == "once":
                self.stats["appr"] += 1
            elif decision == "deny":
                self.stats["deny"] += 1
            if self.state.prompt and self.state.prompt.get("id") == pid:
                self.state.prompt = None
                self.dirty.set()
        elif obj.get("cmd") == "status":
            await self._write({
                "ack": "status", "ok": True,
                "data": {
                    "name": "Claude-Code",
                    "sec": True,
                    "sys": {"up": int(time.monotonic()), "heap": 0},
                    "stats": {**self.stats, "vel": 0, "nap": 0, "lvl": 0},
                },
            })
        elif obj.get("cmd"):
            # generic ack for anything we don't specifically handle
            await self._write({"ack": obj["cmd"], "ok": True, "n": 0})

    # -- IPC -------------------------------------------------------------

    async def ipc_server(self):
        if self.sock_path.exists():
            self.sock_path.unlink()
        server = await asyncio.start_unix_server(self._ipc_client, path=str(self.sock_path))
        os.chmod(self.sock_path, 0o600)
        self.log(f"listening on {self.sock_path}")
        async with server:
            await server.serve_forever()

    async def _ipc_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            raw = await reader.readline()
            if not raw:
                return
            req = json.loads(raw.decode())
        except Exception as e:
            writer.write((json.dumps({"ok": False, "error": f"bad request: {e}"}) + "\n").encode())
            await writer.drain()
            writer.close()
            return

        try:
            resp = await self._dispatch(req)
        except Exception as e:
            resp = {"ok": False, "error": str(e)}

        writer.write((json.dumps(resp) + "\n").encode())
        await writer.drain()
        writer.close()

    async def _dispatch(self, req: dict) -> dict:
        kind = req.get("kind")
        if kind == "event":
            return await self._on_event(req)
        if kind == "prompt":
            return await self._on_prompt(req)
        if kind == "status":
            return {"ok": True, "connected": bool(self.client and self.client.is_connected)}
        return {"ok": False, "error": f"unknown kind: {kind}"}

    async def _on_event(self, req: dict) -> dict:
        """Generic state-update event from a Claude Code hook."""
        event = req.get("event", "")
        session = req.get("session_id", "default")
        text = req.get("text", "")

        if event == "SessionStart":
            self.state.sessions.setdefault(session, {"running": False})
        elif event == "SessionEnd":
            self.state.sessions.pop(session, None)
        elif event == "UserPromptSubmit":
            self.state.sessions.setdefault(session, {})["running"] = True
            if text:
                self.state.add_entry(f"> {text}")
        elif event == "Stop":
            s = self.state.sessions.setdefault(session, {})
            s["running"] = False
            if text:
                self.state.add_entry(text)
        elif event == "Notification":
            if text:
                self.state.add_entry(f"! {text}")
        elif event == "PostToolUse":
            # optional: track tool completions in the entries ring
            if text:
                self.state.add_entry(f"✓ {text}")
        elif event == "PreToolUse":
            # non-blocking observation only; real gating goes through "prompt"
            if text:
                self.state.add_entry(f"… {text}")
        else:
            return {"ok": False, "error": f"unknown event: {event}"}

        self.dirty.set()
        return {"ok": True}

    async def _on_prompt(self, req: dict) -> dict:
        """
        Block until the device answers. Returns {ok, decision} where decision
        is "once" | "deny" | "timeout".
        """
        pid = req.get("id") or uuid.uuid4().hex[:12]
        tool = req.get("tool", "?")
        hint = truncate(req.get("hint", ""), 80)
        timeout = float(req.get("timeout", PROMPT_TIMEOUT_DEFAULT))

        self.state.prompt = {"id": pid, "tool": tool, "hint": hint}
        session = req.get("session_id", "default")
        self.state.sessions.setdefault(session, {})["running"] = True
        self.dirty.set()

        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self.pending_prompts[pid] = fut

        try:
            decision = await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            decision = "timeout"
        finally:
            self.pending_prompts.pop(pid, None)
            if self.state.prompt and self.state.prompt.get("id") == pid:
                self.state.prompt = None
                self.dirty.set()

        return {"ok": True, "decision": decision}


async def main_async(args):
    bridge = Bridge(
        name_prefix=args.name_prefix,
        sock_path=Path(args.socket),
        owner=args.owner,
        verbose=args.verbose,
    )
    stop = asyncio.Event()

    def _sig(*_):
        stop.set()

    for s in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(s, _sig)

    tasks = [
        asyncio.create_task(bridge.ble_connect_loop()),
        asyncio.create_task(bridge.ipc_server()),
    ]

    await stop.wait()
    for t in tasks:
        t.cancel()
    for t in tasks:
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass

    try:
        bridge.sock_path.unlink()
    except FileNotFoundError:
        pass


def main():
    p = argparse.ArgumentParser(description="BLE bridge between Claude Code hooks and a claude-desktop-buddy device")
    p.add_argument("--name-prefix", default=DEFAULT_NAME_PREFIX, help=f"BLE device name prefix (default: {DEFAULT_NAME_PREFIX})")
    p.add_argument("--socket", default=str(DEFAULT_SOCK), help=f"Unix socket path (default: {DEFAULT_SOCK})")
    p.add_argument("--owner", default=os.environ.get("USER", "User").capitalize(), help="Owner name shown on device")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
