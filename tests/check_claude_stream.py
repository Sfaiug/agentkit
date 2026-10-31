"""Smoke's live Claude assertion, check 3a: its turn streams before it ends.

    python3 tests/check_claude_stream.py <out-dir> <workspace>

Model calls are launched only by tests/smoke.sh.
"""

import json
import os
from pathlib import Path
import subprocess
import signal
import sys
import time
from unittest.mock import patch


def read_events(path):
    """Complete JSON events from a file still being written; a partial tail waits."""
    try:
        text = path.read_text()
    except FileNotFoundError:
        return []
    whole, _, _partial = text.rpartition("\n")
    events = []
    for line in whole.splitlines():
        try:
            found = json.loads(line)
        except ValueError:
            continue
        if isinstance(found, (dict, list)):
            events.append(found)
    return events


def check(out, command):
    # Watch the same file the real adapter is still writing, the way the old runs
    # viewer did: only whole lines count, so a half-written tail is never an event.
    live, seen = [], 0
    with subprocess.Popen(command, start_new_session=True) as proc:
        deadline = time.monotonic() + 300
        while proc.poll() is None:
            observed = read_events(out / "events.jsonl")
            if not any(isinstance(event, dict) and event.get("type") == "result"
                       for event in observed):
                live.extend(event for event in observed[seen:]
                            if isinstance(event, dict) and event.get("type") != "result")
            seen = len(observed)
            if time.monotonic() >= deadline:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                raise AssertionError("Claude smoke call exceeded five minutes")
            time.sleep(0.05)
        assert proc.returncode == 0, f"Claude worker exited {proc.returncode}"
    events = [json.loads(line) for line in (out / "events.jsonl").read_text().splitlines()]
    results = [event for event in events if event.get("type") == "result"]
    assert results and not results[-1].get("is_error"), "no successful result event"
    assert any(event in events[:events.index(results[0])] for event in live), \
        "no worker output was visible before the result"
    assert (out / "final.md").read_text() == results[-1]["result"] + "\n"
    assert (out / "session_id").read_text().strip() == results[-1]["session_id"]
    (out / "live.txt").write_text("\n".join(json.dumps(event) for event in live) + "\n")
    print(f"Claude streamed {len(events)} real events; output was visible before exit")


def turn(workspace, out):
    """Check 3a's turn: Claude's [check] model, no instructions, on the login the check runs."""
    from check4_pair import login
    from agentkit import config, worker
    cfg = config.load()
    entry = config.model(cfg, "opus")
    entry.update(config.manifest(entry["harness"])["check"])
    with patch.dict(worker.PREAMBLES, {"executor-scratch": ""}):
        code, *_ = worker.turn(cfg, "opus",
                               "Say STREAM_READY, then run pwd, then reply DONE. Do not edit files.\n",
                               workspace, out, role="executor-scratch",
                               env=config.account_env(login(cfg, entry["provider"])))
    return code


if __name__ == "__main__":
    if sys.argv[1] == "--turn":
        sys.exit(turn(*sys.argv[2:]))
    out = Path(sys.argv[1]).resolve()
    check(out, [sys.executable, __file__, "--turn", sys.argv[2], str(out)])
