#!/usr/bin/env python3
"""Keep a seat's app server alive exactly as long as its remote TUI."""
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import config, notify
from agentkit.harness.codex import main


def seat_home(receipt):
    with Path(receipt).open() as fh:
        data = json.load(fh)
    home = config.STATE / ("codex-remote-" + data["remote"])
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    source = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).resolve()
    source.mkdir(parents=True, exist_ok=True)
    (source / "sessions").mkdir(exist_ok=True)
    (source / "session_index.jsonl").touch(exist_ok=True)
    # Enrollment is tied to installation_id AND the state database. Sharing either
    # lets a second seat take the first seat's remote connection. Everything else,
    # including the login, configured extensions and conversations, stays shared.
    names = {p.name for p in source.iterdir()} if source.exists() else set()
    names.update(("auth.json", "config.toml", "sessions", "session_index.jsonl"))
    for name in names:
        if name in ("installation_id", "app-server-control", "tmp") or ".sqlite" in name:
            continue
        target = home / name
        if target.is_symlink():
            if target.readlink() == source / name:
                continue
            target.unlink()
        if not target.exists():
            target.symlink_to(source / name, target_is_directory=(source / name).is_dir())
    return home


def stop(proc):
    if proc is None:
        return
    # npm's codex is a parent shim; terminating that PID alone leaks its server.
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()


class Client:
    """The Unix transport is WebSocket, including its HTTP upgrade and masking."""
    def __init__(self, path):
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.settimeout(15)
        self.buffer = b""
        self.serial = 0
        try:
            self.socket.connect(path)
            key = base64.b64encode(os.urandom(16)).decode()
            self.socket.sendall((f"GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
                                 f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                                 "Sec-WebSocket-Version: 13\r\n\r\n").encode())
            while b"\r\n\r\n" not in self.buffer:
                self.more()
                if len(self.buffer) > 65536:
                    raise config.Error("Invalid Codex socket handshake")
            head, self.buffer = self.buffer.split(b"\r\n\r\n", 1)
            accept = base64.b64encode(hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest())
            if not head.startswith(b"HTTP/1.1 101 ") or accept not in head:
                raise config.Error("Codex socket did not accept WebSocket upgrade")
            self.call("initialize", {"clientInfo": {"name": "agentkit", "version": "1"},
                                     "capabilities": {"experimentalApi": True}})
            self.send({"method": "initialized"})
        except BaseException:
            self.close()
            raise

    def more(self):
        chunk = self.socket.recv(65536)
        if not chunk:
            raise config.Error("Codex app server closed its socket")
        self.buffer += chunk

    def read(self, size):
        while len(self.buffer) < size:
            self.more()
        data, self.buffer = self.buffer[:size], self.buffer[size:]
        return data

    def send(self, value, opcode=1):
        data = json.dumps(value).encode() if opcode == 1 else value
        size, mask = len(data), os.urandom(4)
        header = bytes([128 | opcode, 128 | size]) if size < 126 else (
            bytes([128 | opcode, 254]) + struct.pack("!H", size))
        self.socket.sendall(header + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(data)))

    def receive(self):
        fragments = bytearray()
        while True:
            first, second = self.read(2)
            size = second & 127
            if size == 126:
                size = struct.unpack("!H", self.read(2))[0]
            elif size == 127:
                size = struct.unpack("!Q", self.read(8))[0]
            if second & 128 or size + len(fragments) > 16 * 1024 * 1024:
                raise config.Error("Invalid Codex WebSocket frame")
            data = self.read(size)
            opcode = first & 15
            if opcode == 8:
                raise config.Error("Codex app server closed its connection")
            if opcode == 9:
                self.send(data, 10)
            elif opcode in (0, 1):
                fragments.extend(data)
                if first & 128:
                    return json.loads(fragments)

    def call(self, method, params=None):
        self.serial += 1
        self.send({"id": self.serial, "method": method, "params": params})
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            self.socket.settimeout(max(.01, deadline - time.monotonic()))
            message = self.receive()
            if message.get("id") == self.serial:
                if "error" in message:
                    raise config.Error(message["error"]["message"])
                return message["result"]
        raise config.Error(f"Codex app server did not answer {method}")

    def close(self):
        self.socket.close()


def pairing(client, home, status):
    """An enrollment asks once, across reconnects, restarts and seat renames."""
    environment = status["environmentId"]
    clients = client.call("remoteControl/client/list", {"environmentId": environment})
    if clients["data"]:
        return
    stamp = home / "agentkit-pairing.json"
    with stamp.open("a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.seek(0)
        previous = fh.read()
        if previous and json.loads(previous).get("environment") == environment:
            return
        pair = client.call("remoteControl/pairing/start", {"manualCode": True})
        name = config.resolve_session(os.environ[config.SESSION_ENV])
        retry = shlex.join(["python3", str(Path(__file__).resolve()), "--pair", str(home)])
        step = (f"In the ChatGPT app, open Remote and pair this computer with code "
                f"{pair['manualPairingCode']}, then open {name}. "
                f"If the code expires, run {retry} on the host for a new code.")
        # Pairing has an exact owner action, unlike the usual card pointing at the
        # pane. Keep its text on the card and use the existing durable outbox.
        key = hashlib.sha256(("codex-pair:" + environment).encode()).hexdigest()
        with notify.session_lock(name), notify.outbox_lock():
            event = notify._read_event(key)
            if event is None:
                payload = {"username": "agentkit", "embeds": [
                    {**notify.embed("needs", name, step), "description": step}]}
                if who := notify.mention():
                    payload["content"] = who
                event = {"id": key, "source": "card:" + key, "episode": key,
                         "session": name, "kind": "needs", "text": step, "pr": None,
                         "files": [], "payload": payload, "message": f"Needs you · {name}: {step}",
                         "created_at": time.time(), "sink": notify.sink() is not None,
                         "status": "pending", "attempts": 0, "next_attempt": 0}
                notify._write_event(event)
                previous = notify.last(name, include_seen=True) or {}
                notify.record(name, "needs", step, source=event["source"],
                              time=event["created_at"], event_id=key)
                notify._card_write(name, {"word": "needs you", "since": event["created_at"],
                                         "began": event["created_at"], "episode": key,
                                         "sent": True, "open_needs": previous.get("open_needs", [])})
            notify._attempt(event)
            notify._remember_card(event)
        fh.seek(0)
        json.dump({"environment": environment}, fh)
        fh.truncate()


def launch(cmd, receipt):
    home = seat_home(receipt)
    env = {**os.environ, "CODEX_HOME": str(home), "CODEX_SQLITE_HOME": str(home)}
    # A short private runtime directory also works when the seat's HOME is a
    # long worktree path. Codex resolves relative socket paths before binding.
    runtime = tempfile.TemporaryDirectory(prefix=".cx-")
    path = Path(runtime.name) / "s"
    socket = str(path)
    server = [cmd[0], "app-server", "--remote-control", "--listen", "unix://" + socket]
    for i, word in enumerate(cmd[:-1]):
        if word in ("-c", "--config"):
            server += ["-c", cmd[i + 1]]
        elif word in ("-m", "--model"):
            server += ["-c", "model=" + json.dumps(cmd[i + 1])]
    server += ["-c", 'approval_policy="never"', "-c", 'sandbox_mode="danger-full-access"']
    processes = []
    client = None
    old_signals = {}

    def ended(signum, frame):
        raise SystemExit(128 + signum)

    try:
        for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
            old_signals[sig] = signal.signal(sig, ended)
        with (home / "server.log").open("w") as log:
            proc = subprocess.Popen(server, env=env, stdin=subprocess.DEVNULL,
                                    stdout=log, stderr=log, start_new_session=True)
            processes.append(proc)
            deadline = time.monotonic() + 15
            while not path.exists():
                if proc.poll() is not None or time.monotonic() > deadline:
                    raise config.Error(f"Codex seat server did not start; see {home / 'server.log'}")
                time.sleep(.05)
            client = Client(socket)
            # --remote is global and must precede the resume subcommand.
            tui = subprocess.Popen([cmd[0], "--remote", "unix://" + socket, *cmd[1:]], env=env)
            # The TUI stays in the pane's foreground process group for terminal input.
            with (home / "connection.json").open("w") as fh:
                json.dump({"socket": str(path)}, fh)
            try:
                checked = False
                while tui.poll() is None:
                    if proc.poll() is not None:
                        raise config.Error("Codex seat server stopped")
                    if not checked:
                        try:
                            status = client.call("remoteControl/status/read")
                            if status["status"] == "connected":
                                pairing(client, home, status)
                                checked = True
                        except (OSError, ValueError, config.Error) as exc:
                            print(f"Codex remote control: {exc}", file=log, flush=True)
                    time.sleep(.25 if checked else 1)
                return tui.returncode
            finally:
                if tui.poll() is None:
                    tui.terminate()
                    try:
                        tui.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        tui.kill()
                        tui.wait()
    finally:
        # Cleanup cannot itself be interrupted by tmux closing the pane.
        for sig in old_signals:
            signal.signal(sig, signal.SIG_IGN)
        if client:
            client.close()
        for proc in reversed(processes):
            stop(proc)
        runtime.cleanup()
        (home / "connection.json").unlink(missing_ok=True)
        if not Path(receipt).exists():
            shutil.rmtree(home, ignore_errors=True)
        for sig, handler in old_signals.items():
            signal.signal(sig, handler)


def pair_again(home):
    home = Path(home)
    connection = json.loads((home / "connection.json").read_text())
    client = Client(connection["socket"])
    try:
        print("Pairing code:", client.call("remoteControl/pairing/start",
                                          {"manualCode": True})["manualPairingCode"])
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "--pair":
            sys.exit(pair_again(sys.argv[2]))
        sys.exit(main(sys.argv[1:], launch=launch))
    except (OSError, ValueError, config.Error) as exc:
        print(f"codex seat: {exc}", file=sys.stderr)
        sys.exit(1)
