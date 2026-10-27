#!/usr/bin/env python3
"""Keep a seat's app server alive exactly as long as its remote TUI."""
from contextlib import closing
import fcntl
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import config
from agentkit.harness.codex import (SEAT_STATE, STOP_RULE, Client, drop_closed_seat,
                                    first_prompt, in_flight, main, pairing_home, remote_home,
                                    seat_conversations)


CONVERSATIONS = ("sessions", "archived_sessions")


def seat_home(receipt):
    with Path(receipt).open() as fh:
        data = json.load(fh)
    home = remote_home(data["remote"])
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    source = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).resolve()
    source.mkdir(parents=True, exist_ok=True)
    (source / "session_index.jsonl").touch(exist_ok=True)
    # Enrollment is tied to installation_id AND the state database. Sharing either
    # lets a second seat take the first seat's remote connection. A new database
    # imports every conversation under its home's sessions and archived_sessions
    # before the server listens (3,500 kept a seat blank for a minute), so those are
    # the seat's own, in a directory that outlives its home and is the same whichever
    # login it runs on (`seat_conversations`). A home keeps the links it has, made
    # before or on another login. The login, config, extensions and thread names stay
    # shared.
    own = seat_conversations(data["remote"])
    for name in CONVERSATIONS:
        if not (home / name).is_symlink() and not (home / name).exists():
            (own / name).mkdir(mode=0o700, parents=True, exist_ok=True)
            (home / name).symlink_to(own / name, target_is_directory=True)
    names = {p.name for p in source.iterdir()} if source.exists() else set()
    names.update(("auth.json", "config.toml", "session_index.jsonl"))
    for name in names:
        if (name in ("installation_id", "app-server-control", "tmp", own.parent.name,
                     *CONVERSATIONS)
                or ".sqlite" in name):
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


def remote_request(auth, environment, method, body=None):
    tokens = json.loads(Path(auth).read_text())["tokens"]
    url = ("https://chatgpt.com/backend-api/wham/remote/control/environments/"
           + urllib.parse.quote(environment, safe=""))
    request = urllib.request.Request(url, method=method,
        headers={"Authorization": "Bearer " + tokens["access_token"],
                 "ChatGPT-Account-Id": tokens["account_id"], "Content-Type": "application/json"},
        data=json.dumps(body).encode() if body is not None else None)
    # The backend briefly still sees an online connection after its process exits.
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                response.read()
            return
        except urllib.error.HTTPError as exc:
            if method == "DELETE" and exc.code == 404:
                return
            if method != "DELETE" or exc.code != 409 or attempt == 5:
                raise config.Error(f"Codex remote {method}: HTTP {exc.code}") from exc
            time.sleep(1)


def enrollments(home):
    path = home / "agentkit-enrollments.json"
    records = json.loads(path.read_text()) if path.exists() else {}
    # A pane can close before the first connected status was read. Codex's own
    # cache still names that enrollment; preserve it before changing accounts.
    auth = home / "auth.json"
    if auth.exists():
        account = (json.loads(auth.read_text()).get("tokens") or {}).get("account_id")
        for database in home.glob("state_*.sqlite"):
            with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
                if not db.execute("SELECT 1 FROM sqlite_master WHERE name = ?",
                                  ("remote_control_enrollments",)).fetchone():
                    continue
                for (environment,) in db.execute(
                        "SELECT environment_id FROM remote_control_enrollments WHERE account_id = ?",
                        (account,)):
                    records.setdefault(environment, {"auth": str(auth.resolve())})
    return records


def enroll(home, status, named):
    environment = status.get("environmentId")
    if not environment:
        return
    path = home / "agentkit-enrollments.json"
    records = enrollments(home)
    entry = records.setdefault(environment, {"auth": str((home / "auth.json").resolve())})
    # Save the deletion receipt before an HTTP request can fail. Each account's
    # login remains addressable after the next launch retargets auth.json.
    path.write_text(json.dumps(records))
    name = config.resolve_session(os.environ[config.SESSION_ENV])
    if named != (environment, name):
        remote_request(entry["auth"], environment, "PATCH", {"name": name})
    return environment, name


def pairing_key(environment):
    return hashlib.sha256(("codex-pair:" + environment).encode()).hexdigest()


def close_pairing(environment, status):
    # an old pairing card stops retrying; one already out stays as it went
    from agentkit import notify
    with notify.outbox_lock():
        event = notify._read_event(pairing_key(environment))
        if event and not event.get("closed"):
            event.update(closed=status, status="disabled", next_attempt=None)
            notify._write_event(event)


def remove_home(home):
    # A failed DELETE raises before the rmtree: the home stays with its receipt
    # and .forgotten marker, and the next forget retries it.
    for environment, entry in enrollments(home).items():
        remote_request(entry["auth"], environment, "DELETE")
        close_pairing(environment, "Closed")
    shutil.rmtree(home, ignore_errors=True)
    drop_closed_seat(home)
    home.with_suffix(".forgotten").unlink(missing_ok=True)
    home.with_suffix(".lock").unlink(missing_ok=True)


def forget(home):
    home = Path(home)
    home.with_suffix(".forgotten").touch(mode=0o600)
    with home.with_suffix(".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0  # the live guard removes it after stopping the server
        remove_home(home)
    return 0


def serve(cmd, receipt, parent):
    data = json.loads(Path(receipt).read_text())
    home = remote_home(data["remote"])
    forgotten = home.with_suffix(".forgotten")

    def ended(signum, frame):
        raise SystemExit(128 + signum)

    def alive():
        return not forgotten.exists() and not select.select([parent], [], [], 0)[0]

    for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, ended)
    # prepare replaces the receipt BEFORE tmux kills the old pane. The receipt
    # is not a deletion signal. Serialize both launches, including their cleanup.
    # The lock sits beside the home, which the first launch has yet to make.
    home.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with home.with_suffix(".lock").open("a") as lock:
        while alive():
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(.05)
        else:
            return 0
        if not Path(receipt).exists():
            return 0
        home = seat_home(receipt)
        return connected(cmd, home, alive)


def connected(cmd, home, alive):
    env = {**os.environ, "CODEX_HOME": str(home)}
    env.pop("CODEX_SQLITE_HOME", None)
    cmd, prompt = first_prompt(cmd)
    cmd += ["-c", "sqlite_home=" + json.dumps(str(home))]
    runtime = tempfile.TemporaryDirectory(prefix=".cx-")
    path = Path(runtime.name) / "s"
    server = [cmd[0], "app-server", "--remote-control", "--listen", "unix://" + str(path)]
    for i, word in enumerate(cmd[:-1]):
        if word in ("-c", "--config"):
            server += ["-c", cmd[i + 1]]
        elif word in ("-m", "--model"):
            server += ["-c", "model=" + json.dumps(cmd[i + 1])]
    server += ["-c", 'approval_policy="never"', "-c", 'sandbox_mode="danger-full-access"']
    # Only Codex itself needs the private home. Shells and their ak workers keep
    # the caller's home variables, including an explicitly selected login.
    source = os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))
    server += ["-c", "shell_environment_policy.set.CODEX_HOME=" + json.dumps(source)]
    if "CODEX_SQLITE_HOME" in os.environ:
        server += ["-c", "shell_environment_policy.set.CODEX_SQLITE_HOME="
                   + json.dumps(os.environ["CODEX_SQLITE_HOME"])]
    proc = tui = None
    try:
        # The home's lock excludes the old server. Its interrupted backfill's
        # running lease would otherwise outlast Codex's own startup wait.
        for database in home.glob("state_*.sqlite"):
            with closing(sqlite3.connect(database)) as db, db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name = ?",
                              ("backfill_state",)).fetchone():
                    db.execute("UPDATE backfill_state SET status = 'pending' WHERE status = 'running'")
        with (home / "server.log").open("w") as log:
            proc = subprocess.Popen(server, env=env, stdin=subprocess.DEVNULL,
                                    stdout=log, stderr=log, start_new_session=True)
            while not path.exists():
                if not alive():
                    return 0
                if proc.poll() is not None:
                    raise config.Error(f"Codex seat server did not start; see {home / 'server.log'}")
                time.sleep(.05)
            # Written before the TUI starts a turn, whose Stop asks the server (`in_flight`).
            with (home / "connection.json").open("w") as fh:
                json.dump({"socket": str(path)}, fh)
            # --remote is global and must precede the resume subcommand. The server above
            # holds the seat's permissions; since 0.160 a remote resume whose TUI asks for
            # its own is refused.
            tui = subprocess.Popen([cmd[0], "--remote", "unix://" + str(path),
                                    *(word for word in cmd[1:] if word != "--yolo"), *prompt],
                                   env=env)
            check_at = 0
            named = None
            while tui.poll() is None and alive():
                if proc.poll() is not None:
                    raise config.Error("Codex seat server stopped")
                if time.monotonic() >= check_at:
                    client = None
                    try:
                        client = Client(str(path))
                        status = client.call("remoteControl/status/read")
                        named = enroll(home, status, named)
                        if status["status"] == "connected":
                            # Older seats posted optional setup as a question. Retire that
                            # card without starting pairing; --pair is the owner's request.
                            close_pairing(status["environmentId"], "Pairing optional")
                            check_at = time.monotonic() + 30
                    except (OSError, ValueError, config.Error) as exc:
                        print(f"Codex remote control: {exc}", file=log, flush=True)
                    finally:
                        if client:
                            client.close()
                    check_at = max(check_at, time.monotonic() + 1)
                time.sleep(.25)
            return tui.returncode or 0
    finally:
        for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, signal.SIG_IGN)
        if tui and tui.poll() is None:
            tui.terminate()
            try:
                tui.wait(timeout=5)
            except subprocess.TimeoutExpired:
                tui.kill()
                tui.wait()
        stop(proc)
        runtime.cleanup()
        (home / "connection.json").unlink(missing_ok=True)
        (home / "agentkit-enrollments.json").write_text(json.dumps(enrollments(home)))
        if home.with_suffix(".forgotten").exists():
            try:
                remove_home(home)
            except (OSError, ValueError, config.Error) as exc:
                print(f"Codex remote cleanup deferred: {exc}", file=sys.stderr)


def launch(cmd, receipt):
    # A guard owns both children. Only this wrapper holds the pipe's write end;
    # even SIGKILL closes it, so cleanup does not depend on a wrapper's finally.
    reader, writer = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(writer)
        try:
            return serve(cmd, receipt, reader)
        finally:
            os.close(reader)
    os.close(reader)
    old_signals = {}
    def ended(signum, frame):
        raise SystemExit(128 + signum)
    try:
        for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
            old_signals[sig] = signal.signal(sig, ended)
        _, status = os.waitpid(pid, 0)
        return os.waitstatus_to_exitcode(status)
    finally:
        for sig in old_signals:
            signal.signal(sig, signal.SIG_IGN)
        os.close(writer)
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
        for sig, handler in old_signals.items():
            signal.signal(sig, handler)


def stop_hook():
    """This seat's Stop, handed on with the background work it holds (`in_flight`), read from
    the seat's own app server, which runs this hook.  Where the server cannot say, the Stop goes
    on as it came: unread work is no evidence of none."""
    payload = sys.stdin.read()
    try:
        event = json.loads(payload)
        with (Path(os.environ["CODEX_HOME"]) / "connection.json").open() as fh:
            client = Client(json.load(fh)["socket"])
        try:
            payload = json.dumps({**event, "background_tasks": in_flight(client,
                                                                          event["session_id"])})
        finally:
            client.close()
    except (OSError, ValueError, KeyError, TypeError, AttributeError, config.Error):
        pass
    for script in (SEAT_STATE, STOP_RULE):
        subprocess.run(["bash", str(config.REPO / script)], input=payload, text=True)
    return 0


def pair_again(home):
    home = pairing_home(home)
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
        if len(sys.argv) == 3 and sys.argv[1] == "--forget":
            sys.exit(forget(sys.argv[2]))
        if len(sys.argv) == 3 and sys.argv[1] == "--pair":
            sys.exit(pair_again(sys.argv[2]))
        if sys.argv[1:] == ["stop"]:
            sys.exit(stop_hook())
        sys.exit(main(sys.argv[1:], launch=launch))
    except (OSError, ValueError, config.Error) as exc:
        print(f"codex seat: {exc}", file=sys.stderr)
        sys.exit(1)
