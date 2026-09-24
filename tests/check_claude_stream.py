"""Smoke's live Claude assertion. Model calls are launched only by tests/smoke.sh."""

import json
import os
from pathlib import Path
import subprocess
import signal
import sys
import time


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


if __name__ == "__main__":
    check(Path(sys.argv[1]).resolve(), sys.argv[2:])
