"""Files requested on the VM, delivered over a connection initiated by the Mac."""

import fcntl
import json
import logging
import math
import os
from pathlib import Path
import plistlib
import re
import secrets
import select
import shlex
import shutil
import subprocess
import sys
import threading
import time

from . import command_help, config

POLL = 0.1
READ_TIMEOUT = 10
READ_ERROR = ("macOS lets only the app the file was dropped on read it: open a new terminal tab "
              "on the Mac (or run ak macbridge --reader there) and fetch again")
HEARTBEAT = b"heartbeat\n"
HEARTBEAT_INTERVAL = 5
HEARTBEAT_TIMEOUT = 15
LABEL = "com.agentkit.macbridge"
REQUEST_ID = re.compile(r"[a-f0-9]{16}\Z")


def directories():
    root = Path.home() / ".agentkit/macbridge"
    for path in (root, root / "requests", root / "inbox", root / "reads", root / "staged"):
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def normalize(value):
    if not value or any(c in value for c in "\0\r\n\t"):
        raise config.Error("a file path must be non-empty and contain no tabs or newlines")
    # Preserve literal filenames when already readable here, including quotes/backslashes.
    if Path(value).expanduser().exists():
        return str(Path(value).expanduser())
    value = value.strip()
    if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
        try:
            parts = shlex.split(value)
        except ValueError:
            parts = []
        value = parts[0] if len(parts) == 1 else value[1:-1]
    # Finder/Terminal escape shell punctuation; ordinary spaces and apostrophes stay put.
    value = re.sub(r"\\([\s\\'\"()\[\]{}<>|;&!$`*?#~])", r"\1", value)
    if not value or any(c in value for c in "\0\r\n\t"):
        raise config.Error("a file path must be non-empty and contain no tabs or newlines")
    return str(Path(value).expanduser())


def basename(path):
    return re.sub(r"[^A-Za-z0-9._-]", "_", Path(path).name) or "file"


def extension(path):
    return Path(basename(path)).suffix


def fetch_one(value, timeout):
    path = normalize(value)
    if Path(path).exists():
        return str(Path(path).absolute())
    root = directories()
    ident = secrets.token_hex(8)
    request = root / "requests" / ident
    temp = request.with_name(f".{ident}.tmp")
    dest = root / "inbox" / (ident + extension(path))
    missing = root / "inbox" / f"{ident}.missing"
    ready = root / "inbox" / f".{ident}.ready"
    error = root / "inbox" / f".{ident}.error"
    try:
        temp.write_text(json.dumps({"path": path, "basename": basename(path)}) + "\n")
        temp.replace(request)
        deadline = time.monotonic() + timeout
        while True:
            if error.exists():
                text = error.read_text().strip() or "the Mac could not send that file"
                raise config.Error(f"{path}: {text}")
            # .missing is also a legal file extension. The Mac publishes a receipt first
            # for that case, so even an empty file can be distinguished from a failure.
            if dest.is_file() and (dest != missing or ready.exists()):
                return str(dest)
            if missing.exists():
                raise config.Error(f"the Mac no longer has that file: {path}")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise config.Error(f"{path}: no answer from the Mac bridge in {timeout:g}s; "
                                   "the Mac may be asleep or offline, or ak macbridge is not "
                                   "running there (open ak on the Mac)")
            time.sleep(min(POLL, remaining))
    finally:
        temp.unlink(missing_ok=True)
        request.unlink(missing_ok=True)
        ready.unlink(missing_ok=True)
        error.unlink(missing_ok=True)
        if missing != dest:
            missing.unlink(missing_ok=True)


def serve():
    root = directories()
    # One connection owns the queue for its entire lifetime. A reconnect retries
    # until the old connection closes or its heartbeat expires, even if sshd lives on.
    with (root / "serve.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("ak fetch --serve: another connection holds serve.lock; exiting", file=sys.stderr)
            return 0
        deadline = time.monotonic() + HEARTBEAT_TIMEOUT
        heartbeat = b""
        connected = False
        request = None
        output = b""
        fd = sys.stdout.fileno()
        blocking = os.get_blocking(fd)
        os.set_blocking(fd, False)
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return 0
                readable, writable, _ = select.select(
                    [sys.stdin], [fd] if output else [], [], min(POLL, remaining))
                if readable:
                    chunk = os.read(sys.stdin.fileno(), 4096)
                    if not chunk:
                        return 0
                    *lines, heartbeat = (heartbeat + chunk).split(b"\n")
                    if HEARTBEAT[:-1] in lines:
                        deadline = time.monotonic() + HEARTBEAT_TIMEOUT
                        connected = True
                    # Bound memory for an invalid line without accepting its suffix.
                    if len(heartbeat) >= len(HEARTBEAT):
                        heartbeat = b"\0"
                if time.monotonic() >= deadline:
                    return 0
                if writable:
                    try:
                        output = output[os.write(fd, output):]
                    except BlockingIOError:
                        continue
                    if not output:
                        # Leave failures (including partial writes) queued for the next
                        # connection. Only a complete line hands the request off.
                        request.unlink(missing_ok=True)
                        request = None
                if connected and request is None:
                    for candidate in sorted((root / "requests").iterdir()):
                        if not REQUEST_ID.fullmatch(candidate.name):
                            continue
                        try:
                            data = json.loads(candidate.read_text())
                            path = data["path"]
                            if not isinstance(path, str) or any(c in path for c in "\0\r\n\t"):
                                raise ValueError("invalid request path")
                            output = f"{candidate.name}\t{path}\n".encode("utf-8")
                        except FileNotFoundError:  # a fetch timed out during this scan
                            continue
                        except (ValueError, KeyError, TypeError) as exc:
                            candidate.unlink(missing_ok=True)
                            print(f"ak fetch --serve: invalid request {candidate.name}: {exc}",
                                  file=sys.stderr)
                            continue
                        request = candidate
                        break
        except BrokenPipeError:
            return 0
        finally:
            os.set_blocking(fd, blocking)


def fetch_main(argv):
    if command_help.show("fetch", argv):
        return 0
    try:
        if argv == ["--serve"]:
            return serve()
        if argv[:1] == ["--"]:
            argv = argv[1:]
        if not argv or "--serve" in argv:
            raise config.Error("usage: ak fetch PATH [PATH ...] | ak fetch --serve")
        try:
            timeout = float(os.environ.get("AK_FETCH_TIMEOUT", "25"))
            if not math.isfinite(timeout) or timeout < 0:
                raise ValueError()
        except ValueError:
            raise config.Error("AK_FETCH_TIMEOUT must be a finite, non-negative number")
        rc = 0
        for value in argv:
            try:
                print(fetch_one(value, timeout), flush=True)
            except (config.Error, OSError) as exc:
                print(f"ak fetch: {exc}", file=sys.stderr)
                rc = 1
        return rc
    except BrokenPipeError:
        return 0
    except OSError as exc:
        raise config.Error(str(exc))


def acquire_lock(name="macbridge.lock"):
    lock = (directories() / name).open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return None
    return lock


def terminal_app_pid():
    pid = os.getpid()
    while pid > 1:
        parent = int(subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)],
                                    capture_output=True, text=True, check=True).stdout.strip())
        if parent == 1:
            return pid
        pid = parent
    raise config.Error("could not find the terminal app")


def reader_loop(root, apppid, log):
    logger = logging.getLogger("agentkit.macbridge")
    handler = logging.StreamHandler(log)
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        while True:
            try:
                os.kill(apppid, 0)
            except ProcessLookupError:
                return
            for request in sorted((root / "reads").iterdir()):
                if not REQUEST_ID.fullmatch(request.name):
                    continue
                part = root / "staged" / f".{request.name}.{apppid}.part"
                dest = root / "staged" / request.name
                try:
                    path = json.loads(request.read_text())["path"]
                    if not isinstance(path, str) or not path or any(c in path for c in "\0\r\n\t"):
                        raise ValueError("invalid request path")
                    with open(path, "rb") as source, part.open("wb") as target:
                        shutil.copyfileobj(source, target)
                    # Another reader may have won, or the bridge may have timed out.
                    if request.exists():
                        if not dest.exists():
                            part.replace(dest)
                        request.unlink(missing_ok=True)
                except (PermissionError, FileNotFoundError):
                    pass  # Another app's reader may hold the grant.
                except (ValueError, KeyError, TypeError) as exc:
                    logger.warning("invalid read request %s: %s", request.name, exc)
                    request.unlink(missing_ok=True)
                except OSError as exc:
                    logger.warning("read %s failed: %s", request.name, exc)
                finally:
                    part.unlink(missing_ok=True)
            time.sleep(POLL)
    finally:
        (root / f"reader-{apppid}.lock").unlink(missing_ok=True)
        logger.removeHandler(handler)


def start_reader():
    # Discover before detaching: after the launching shell exits, launchd adopts us.
    apppid = terminal_app_pid()
    name = f"reader-{apppid}.lock"
    lock = acquire_lock(name)
    if lock is None:
        return
    with lock:
        try:
            with (directories() / "macbridge.log").open("a") as log:
                subprocess.Popen([sys.executable, str(config.REPO / "bin/ak"), "macbridge",
                                  "--reader", "--app-pid", str(apppid),
                                  "--lock-fd", str(lock.fileno())], pass_fds=(lock.fileno(),),
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                 start_new_session=True)
        except OSError:
            (directories() / name).unlink(missing_ok=True)
            raise


def request_read(root, ident, source):
    live = False
    for path in root.glob("reader-*.lock"):
        with path.open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                live = True
            else:
                path.unlink(missing_ok=True)
    request = root / "reads" / ident
    temp = request.with_name(f".{ident}.tmp")
    try:
        if not live:
            return False
        temp.write_text(json.dumps({"path": str(source)}) + "\n")
        temp.replace(request)
        deadline = time.monotonic() + READ_TIMEOUT
        while True:
            if (root / "staged" / ident).is_file():
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(POLL, remaining))
    finally:
        temp.unlink(missing_ok=True)
        request.unlink(missing_ok=True)


def server():
    """The server's ssh alias, as `install.sh --client [ALIAS]` recorded it."""
    alias = config.server_alias()
    if not alias:
        raise config.Error("no server is recorded; run `install.sh --client ALIAS` on this Mac")
    return alias


def publish_error(ident, text, options, log):
    inbox = '"$HOME"/.agentkit/macbridge/inbox/'
    text = " ".join(str(text).splitlines())
    command = (f"printf '%s\\n' {shlex.quote(text)} > {inbox}.{ident}.error.part && "
               f"mv -f {inbox}.{ident}.error.part {inbox}.{ident}.error")
    try:
        subprocess.run(["ssh", *options, "-T", server(), command],
                       stdin=subprocess.DEVNULL, stdout=log, stderr=log, check=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        logging.getLogger("agentkit.macbridge").warning("error marker %s failed: %s", ident, exc)


def ssh_options(root):
    return ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=2",
            "-o", "ControlMaster=auto", "-o", "ControlPersist=60",
            "-o", f"ControlPath={root}/ssh-%C"]


def transfer(ident, path, options, log):
    """Keep partial scp uploads invisible to fetch; all remote shell names are ours."""
    if not REQUEST_ID.fullmatch(ident) or not path or any(c in path for c in "\0\r\n\t"):
        raise ValueError("invalid request line")
    source = Path(path).expanduser().absolute()
    inbox = '"$HOME"/.agentkit/macbridge/inbox/'
    staged = None
    try:
        if not source.is_file():
            command = f": > {inbox}{ident}.missing"
        else:
            try:
                with open(source, "rb"):
                    pass
            except PermissionError:
                root = directories()
                staged = root / "staged" / ident
                if not request_read(root, ident, source):
                    logging.getLogger("agentkit.macbridge").warning("transfer %s: %s", ident, READ_ERROR)
                    publish_error(ident, READ_ERROR, options, log)
                    return False
                source = staged
            subprocess.run(["scp", "-q", *options, "--", str(source),
                            f"{server()}:.agentkit/macbridge/inbox/.{ident}.part"],
                           stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                           check=True, timeout=120)
            ext = extension(path)
            command = (f": > {inbox}.{ident}.ready && " if ext == ".missing" else "")
            command += f"mv -f {inbox}.{ident}.part {inbox}{ident}{ext}"
        subprocess.run(["ssh", *options, "-T", server(), command],
                       stdin=subprocess.DEVNULL, stdout=log, stderr=log, check=True, timeout=30)
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


def send_heartbeats(stream, stopped):
    # A beat fits in PIPE_BUF, so a nonblocking pipe write is all-or-nothing.
    # Keep ticking during scp and its retries; a stalled SSH reader cannot trap cleanup.
    while not stopped.is_set():
        try:
            os.write(stream.stdin.fileno(), HEARTBEAT)
        except BlockingIOError:
            pass
        except OSError:
            if stream.poll() is None:
                stream.terminate()
            return
        stopped.wait(HEARTBEAT_INTERVAL)


def bridge_loop(root, log):
    logger = logging.getLogger("agentkit.macbridge")
    handler = logging.StreamHandler(log)
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    options = ssh_options(root)
    delay = 1
    try:
        while True:
            stream = None
            stopped = threading.Event()
            heartbeat = None
            try:
                logger.info("connecting to %s", server())
                # Heartbeats prove the Mac is alive even when sshd holds stale pipes open;
                # scp still uses separate multiplexed SSH channels.
                stream = subprocess.Popen(["ssh", *options, "-T", server(), "ak fetch --serve"],
                                          stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                          stderr=log, text=True, encoding="utf-8")
                os.set_blocking(stream.stdin.fileno(), False)
                heartbeat = threading.Thread(target=send_heartbeats, args=(stream, stopped),
                                             daemon=True)
                heartbeat.start()
                for line in stream.stdout:
                    if not line.endswith("\n"):
                        logger.warning("ignoring incomplete request")
                        continue
                    try:
                        ident, path = line.rstrip("\n").split("\t", 1)
                        retry = 1
                        for attempt in range(3):
                            try:
                                if transfer(ident, path, options, log) is not False:
                                    logger.info("delivered %s %s", ident, path)
                                delay = 1
                                break
                            except (OSError, subprocess.SubprocessError) as exc:
                                if attempt == 2:
                                    logger.warning("transfer %s abandoned: %s", ident, exc)
                                    publish_error(ident, str(exc), options, log)
                                    break
                                logger.warning("transfer %s failed: %s; retry in %ss",
                                               ident, exc, retry)
                                time.sleep(retry)
                                retry = min(retry * 2, 30)
                    except ValueError as exc:
                        logger.warning("ignoring request: %s", exc)
                logger.warning("SSH stream closed")
            except (OSError, UnicodeError, config.Error) as exc:
                # A missing server record reads here too: the daemon logs it and backs
                # off with the other reconnects instead of exiting under KeepAlive.
                logger.warning("SSH stream failed: %s", exc)
            finally:
                stopped.set()
                if heartbeat is not None:
                    heartbeat.join()
                if stream is not None:
                    stream.stdin.close()
                    stream.stdout.close()
                    if stream.poll() is None:
                        stream.terminate()
                    try:
                        stream.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        stream.kill()
                        stream.wait()
            logger.info("reconnect in %ss", delay)
            time.sleep(delay)
            delay = min(delay * 2, 30)
    finally:
        logger.removeHandler(handler)


def start_background():
    if sys.platform != "darwin":
        return
    try:
        start_reader()
    except (OSError, ValueError, config.Error, subprocess.SubprocessError) as exc:
        print(f"ak macbridge: could not start reader: {exc}", file=sys.stderr)
    try:
        lock = acquire_lock()
        if lock is None:
            return
        # Pass ownership across exec so concurrent menus cannot race the child startup.
        with lock, (directories() / "macbridge.log").open("a") as log:
            subprocess.Popen([sys.executable, str(config.REPO / "bin/ak"), "macbridge",
                              "--lock-fd", str(lock.fileno())], pass_fds=(lock.fileno(),),
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                             start_new_session=True)
    except OSError as exc:
        print(f"ak macbridge: could not start: {exc}", file=sys.stderr)


def install_launch_agent(load=True):
    root = directories()
    path = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [sys.executable, str(Path.home() / ".local/bin/ak"), "macbridge"],
        "EnvironmentVariables": {"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 10,
        "StandardOutPath": str(root / "macbridge.log"),
        "StandardErrorPath": str(root / "macbridge.log"),
    })
    changed = not path.exists() or path.read_bytes() != data
    if changed:
        path.write_bytes(data)
    if load:
        domain = f"gui/{os.getuid()}"
        active = subprocess.run(["launchctl", "print", f"{domain}/{LABEL}"],
                                capture_output=True).returncode == 0
        if active and changed:
            subprocess.run(["launchctl", "bootout", domain, str(path)], check=True)
        if not active or changed:
            subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=True)
        else:
            subprocess.run(["launchctl", "kickstart", "-k", f"{domain}/{LABEL}"], check=True)
    print(f"macbridge: {path}" + (" loaded" if load else " (sandbox: launchctl skipped)"))


def main(argv):
    if command_help.show("macbridge", argv):
        return 0
    if sys.platform != "darwin":
        raise config.Error("ak macbridge runs on macOS; use ak fetch on this host")
    try:
        if argv == ["--reader"]:
            start_reader()
            return 0
        apppid = None
        if len(argv) == 5 and argv[:2] == ["--reader", "--app-pid"] and argv[3] == "--lock-fd":
            apppid = int(argv[2])
            if apppid <= 1:
                raise config.Error("usage: ak macbridge [--reader]")
            argv = argv[3:]
        if len(argv) == 2 and argv[0] == "--lock-fd":
            lock = os.fdopen(int(argv[1]), "a")
            os.set_inheritable(lock.fileno(), False)
        elif not argv:
            lock = acquire_lock()
        else:
            raise config.Error("usage: ak macbridge [--reader]")
        if lock is None:
            return 0
        with lock, (directories() / "macbridge.log").open("a", buffering=1) as log:
            if apppid is not None:
                reader_loop(directories(), apppid, log)
            else:
                bridge_loop(directories(), log)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise config.Error(str(exc))
    return 0
