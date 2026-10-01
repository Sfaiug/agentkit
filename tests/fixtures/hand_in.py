"""Typed review records for fake adapters whose scripted plans still use Markdown."""

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from agentkit import hand_in, run


def records(text):
    verdicts = run.review_verdicts(text)
    if not verdicts:
        return []
    rows = []
    for kind, items in (("finding", [item.group(1) for line in run.findings_section(text).splitlines()
                                    if (item := run.FOLLOWUP_ITEM.match(line))]),
                        ("follow-up", run.followups_in(text))):
        for item in items:
            if item.lower() in ("none", "none."):
                continue
            site, _, details = item.partition(" - ")
            path, _, line = site.rpartition(":")
            what, _, why = details.partition(" - ")
            row = {"kind": kind, "path": path or "deliverable", "line": int(line) if line.isdigit() else 1,
                   "what": what or item, "why": why or "fixture defect",
                   "evidence": {"quote": "fixture evidence"}}
            if kind == "follow-up":
                row["before"] = "base abc123 (fixture)"
            rows.append(row)
    if verdicts[-1].upper() == "FAIL" and not any(row["kind"] == "finding" for row in rows):
        rows.insert(0, {"kind": "finding", "path": "deliverable", "line": 1,
                        "what": "fixture blocking finding", "why": "fixture defect",
                        "evidence": {"quote": "fixture evidence"}})
    return rows + [{"kind": "done"}]


def reported(text):
    return hand_in.Review(records(text)).text


def write(out):
    # Only a worker's own file is reachable, even when its test inherited another turn's env.
    out = Path(out)
    file = os.environ.get(hand_in.ENV)
    if file != str((out / hand_in.FILE).resolve()) or not (out / "final.md").exists():
        return
    if not (out / "prompt.md").read_text().startswith("You are the reviewer"):
        return
    rows = records((out / "final.md").read_text())
    if rows:
        with Path(file).open("a") as fh:
            fh.write("".join(json.dumps(row) + "\n" for row in rows))


def scripted(body):
    """Fake providers exit early too, so submit their planned records at exit."""
    if "final.md" not in body:
        return body
    if body.startswith("#!/bin/") or body.startswith("#!/usr/bin/env bash"):
        first, _, rest = body.partition("\n")
        return first + "\ntrap " + shlex.quote(f"{shlex.quote(sys.executable)} {shlex.quote(__file__)} \"$6\"") + " EXIT\n" + rest
    return ("import atexit, pathlib, runpy, sys\n"
            f"atexit.register(lambda: runpy.run_path({__file__!r})['write'](pathlib.Path(sys.argv[6])) "
            "if len(sys.argv) > 6 and sys.argv[1] == 'run' else None)\n" + body)


def smoke(out, workspace):
    """A fake smoke worker still crosses the same checker as a real harness."""
    env = {**os.environ, hand_in.ENV: hand_in.start(out, workspace)}
    for args in (["finding", "hello.txt:1", "Smoke record", "Checks the hand-in channel", "--quote", "hello"],
                 ["done"]):
        subprocess.run([sys.executable, str(REPO / "bin/ak"), "hand-in", *args],
                       cwd=workspace, env=env, check=True)


if __name__ == "__main__":
    if sys.argv[1] == "smoke":
        smoke(sys.argv[2], sys.argv[3])
    else:
        write(sys.argv[1])
