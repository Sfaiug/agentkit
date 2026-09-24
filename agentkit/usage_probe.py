"""The Muse caller and adapter share one deadline, including descendant cleanup.

Supervision runs in a dedicated process: Linux's subreaper must not adopt children from
unrelated agentkit work. The supervised adapter and its harness share one process group.
"""

import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

DEFAULT_BUDGET = 45.0
DEADLINE_ENV = "AGENTKIT_MUSE_USAGE_DEADLINE"
WORK_DEADLINE_ENV = "AGENTKIT_MUSE_USAGE_WORK_DEADLINE"


def budget():
    try:
        value = float(os.environ.get("AGENTKIT_MUSE_USAGE_TIMEOUT", DEFAULT_BUDGET))
        if math.isfinite(value) and 0 < value <= DEFAULT_BUDGET:
            return value
    except ValueError:
        pass
    return DEFAULT_BUDGET


def command(argv):
    """Start the same supervisor for a caller's adapter or the standalone probe."""
    seconds = budget()
    deadline = time.monotonic() + seconds
    env = dict(os.environ, **{DEADLINE_ENV: str(deadline),
                              WORK_DEADLINE_ENV: str(deadline - min(2.0, seconds / 5))})
    return [sys.executable, str(Path(__file__).resolve()), *argv], env


def capture(argv):
    argv, env = command(argv)
    return subprocess.run(argv, env=env, capture_output=True, encoding="utf-8", errors="replace")


def unknown(message):
    return json.dumps({"provider": "meta", "meters": [], "error": "unknown: " + message})


def supervise(argv):
    deadline = float(os.environ[DEADLINE_ENV])
    work_deadline = float(os.environ[WORK_DEADLINE_ENV])
    # Orphaned grandchildren become ours to reap, even when the harness exited first.
    if sys.platform == "linux":
        import ctypes
        if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
            return unknown("could not supervise Muse usage descendants")
    proc = None
    output = unknown("Muse usage probe timed out")

    class Cancelled(Exception):
        pass

    def cancel(signum, frame):
        raise Cancelled()

    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, start_new_session=True,
                                encoding="utf-8", errors="replace")
        output, _ = proc.communicate(timeout=max(0, work_deadline - time.monotonic()))
        if proc.returncode or not output.strip():
            output = unknown("Muse usage adapter failed")
    except subprocess.TimeoutExpired:
        pass
    except Cancelled:
        output = unknown("Muse usage probe cancelled")
    except OSError:
        output = unknown("could not start Muse usage adapter")
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        if proc is not None:
            def send(sig):
                try:
                    os.killpg(proc.pid, sig)
                except ProcessLookupError:
                    pass

            send(signal.SIGTERM)
            # Give the harness a short chance to reap its own children, then kill even if
            # the group leader already exited: inherited pipes must never keep us waiting.
            grace = min(.2, max(0, deadline - time.monotonic()) / 2)
            try:
                proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                pass
            send(signal.SIGKILL)
            try:
                proc.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass
            proc.stdout.close()
            while time.monotonic() < deadline:
                if sys.platform == "linux":
                    # A launcher may detach a child into another session. Once its parent
                    # exits the subreaper adopts it; kill those children too, then reap them.
                    children = Path(f"/proc/{os.getpid()}/task/{os.getpid()}/children")
                    for child in children.read_text().split():
                        try:
                            os.kill(int(child), signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                try:
                    pid, _ = os.waitpid(-1 if sys.platform == "linux" else -proc.pid, os.WNOHANG)
                except ChildProcessError:
                    break
                if pid == 0:
                    time.sleep(min(.01, max(0, deadline - time.monotonic())))
    return output


if __name__ == "__main__":
    print(supervise(sys.argv[1:]))
