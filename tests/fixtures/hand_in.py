"""Typed records for fake adapters whose scripted plans still use Markdown."""

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


def records(text, command="echo 'fixture evidence'; exit 1"):
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
                   "evidence": {"quote": "fixture evidence"} if kind == "follow-up" else {
                       "run": command, "returncode": 1,
                       "output": "fixture evidence\n"}}
            if kind == "follow-up":
                row["before"] = "base abc123 (fixture)"
            rows.append(row)
    if verdicts[-1].upper() == "FAIL" and not any(row["kind"] == "finding" for row in rows):
        rows.insert(0, {"kind": "finding", "path": "deliverable", "line": 1,
                        "what": "fixture blocking finding", "why": "fixture defect",
                        "evidence": {"run": command, "returncode": 1,
                                     "output": "fixture evidence\n"}})
    return rows + [{"kind": "done"}]


def reported(text):
    rows = records(text)
    for row in rows:
        if row["kind"] == "finding":
            row["evidence"]["commit"] = "workspace"
    return hand_in.Review(rows).text


def executor_records(text):
    summary = re.search(r"^##[ \t]*Summary\b", text or "", re.M | re.I)
    blocked = re.search(r"^##[ \t]*Blocked\b[^\n]*\n(.*)", text or "", re.S | re.M | re.I)
    if blocked and not summary:
        return [{"kind": "blocked", "why": blocked.group(1).strip()}]
    unnecessary = re.search(r"^[ \t>]*(?:[-*+][ \t]+|\d+[.)][ \t]+)?[*_`]*not needed"
                            r"[*_`]*:[*_`]*[ \t]*(\S.*)", text or "", re.M | re.I)
    if unnecessary:
        return [{"kind": "not-needed", "why": unnecessary.group(1).strip()}]
    return [{"kind": "done"}] if summary else []


def author_turns(run_dir):
    count = 0
    for path in Path(run_dir).glob("round-*/*/hand-in.jsonl"):
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        count += bool(rows) and not rows[0].get("role", "reviewer").startswith("reviewer") and rows[-1]["kind"] == "done"
    return count


def proof_command(workspace, out):
    # Scripted findings stand for a defect in this revision. A fake repair must make
    # their proof pass too: a new commit, or a completed author turn in scratch.
    if (Path(workspace) / ".git").exists():
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=workspace,
                              check=True, capture_output=True, text=True).stdout.strip()
        return f"echo 'fixture evidence'; test \"$(git rev-parse HEAD)\" != {shlex.quote(head)}"
    run_dir = Path(out).parent.parent
    return " ".join(map(shlex.quote, [sys.executable, os.path.relpath(__file__, workspace),
        "proof", os.path.relpath(run_dir, workspace), str(author_turns(run_dir))]))


def submitting(fake):
    """Mocked worker calls hand in their scripted result just like fake adapters."""
    def call(*args, **kwargs):
        answer = fake(*args, **kwargs) if callable(fake) else fake
        role = kwargs.get("role", args[5] if len(args) > 5 else "executor")
        rows = (records(answer[1], proof_command(args[3], args[4])) if role.startswith("reviewer") else
                executor_records(answer[1]) if answer[0] == 0 else [])
        if rows:
            out = Path(args[4])
            out.mkdir(parents=True, exist_ok=True)
            (out / "final.md").write_text(answer[1])
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
    if hand_in.read(file).closing:
        return
    reviewing = (out / "prompt.md").read_text().startswith("You are the reviewer")
    text = (out / "final.md").read_text()
    workspace = json.loads(Path(file).read_text().splitlines()[0])["workspace"]
    rows = records(text, proof_command(workspace, out)) if reviewing else executor_records(text)
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
    if sys.argv[1] == "proof":
        print("fixture evidence")
        raise SystemExit(author_turns(sys.argv[2]) <= int(sys.argv[3]))
    elif sys.argv[1] == "smoke":
        smoke(sys.argv[2], sys.argv[3])
    else:
        write(sys.argv[1])
