"""Typed review records for fake adapters whose scripted plans still use Markdown."""

import json
import os
import re
from pathlib import Path
import shlex
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from agentkit import hand_in


FINDINGS = re.compile(r"^(#+)[ \t]*Findings\b[^\n]*$", re.M | re.I)
FINDING_ITEM = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+\S", re.M)
FOLLOWUPS = re.compile(r"^(#+)[ \t]*Follow-ups\b[^\n]*$", re.M | re.I)
FOLLOWUP_ITEM = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+(\S.*)$", re.M)


def review_verdicts(text):
    """Return verdict words in line order, allowing markdown around a verdict line."""
    return re.findall(r"^[\s>#*_`]*VERDICT:\s*(PASS|FAIL)(?=[\W_]|$)", text, re.M | re.I)


def finding_count(text):
    """Count scripted findings, including sites grouped under deeper headings."""
    return len(FINDING_ITEM.findall(findings_section(text)))


def findings_section(text):
    """Scripted findings stop at the next peer or higher heading."""
    text = text or ""
    heading = FINDINGS.search(text)
    if not heading:
        return ""
    section = text[heading.end():]
    end = re.search(rf"^#{{1,{len(heading.group(1))}}}[ \t]", section, re.M)
    return section[:end.start()] if end else section


def followups_in(text):
    """Keep each scripted follow-up's indented evidence and omit empty lists."""
    heading = FOLLOWUPS.search(text or "")
    if not heading:
        return []
    section = text[heading.end():]
    end = re.search(rf"^#{{1,{len(heading.group(1))}}}[ \t]", section, re.M)
    items, marker, indent = [], None, None
    for line in (section[:end.start()] if end else section).splitlines():
        depth = len(line) - len(line.lstrip())
        if marker is not None and (not line.strip() or depth > marker):
            items[-1] += "\n" + line[min(depth, indent):]
            continue
        item = FOLLOWUP_ITEM.match(line)
        marker, indent = (depth, item.start(1)) if item else (None, None)
        if item:
            items.append(item.group(1))
    return [item for item in map(str.strip, items)
            if not re.fullmatch(r"(?:none|n/a)\.?", item, re.I)]


def records(text):
    verdicts = review_verdicts(text)
    if not verdicts:
        return []
    rows = []
    for kind, items in (("finding", [item.group(1) for line in findings_section(text).splitlines()
                                    if (item := FOLLOWUP_ITEM.match(line))]),
                        ("follow-up", followups_in(text))):
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


def submitting(fake):
    """Mocked worker calls must hand in their scripted review just like fake adapters."""
    def call(*args, **kwargs):
        answer = fake(*args, **kwargs) if callable(fake) else fake
        role = kwargs.get("role", args[5] if len(args) > 5 else "executor")
        if role.startswith("reviewer") and (rows := records(answer[1])):
            out = Path(args[4])
            out.mkdir(parents=True, exist_ok=True)
            file = hand_in.start(out, args[3], role=role)
            with Path(file).open("a") as fh:
                fh.write("".join(json.dumps(row) + "\n" for row in rows))
        return answer
    return call


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
        return first + "\ntrap " + shlex.quote(f'if [ "${{1:-}}" = run ]; then {shlex.quote(sys.executable)} {shlex.quote(__file__)} "${{6:-}}"; fi') + " EXIT\n" + rest
    return ("import atexit, pathlib, runpy, sys\n"
            f"atexit.register(lambda: runpy.run_path({__file__!r})['write'](pathlib.Path(sys.argv[6])) "
            "if len(sys.argv) > 6 and sys.argv[1] == 'run' else None)\n" + body)


def smoke(out, workspace):
    """A fake smoke worker still crosses the same checker as a real harness."""
    env = {**os.environ, hand_in.ENV: hand_in.start(out, workspace, role="executor")}
    subprocess.run([sys.executable, str(REPO / "bin/ak"), "hand-in", "done"],
                   cwd=workspace, env=env, check=True)


if __name__ == "__main__":
    if sys.argv[1] == "smoke":
        smoke(sys.argv[2], sys.argv[3])
    else:
        write(sys.argv[1])
