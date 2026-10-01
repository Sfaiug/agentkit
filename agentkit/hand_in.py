"""One checked review channel for every harness: append records, derive the verdict."""

from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import subprocess
import tempfile

from . import command_help, config

FILE = "hand-in.jsonl"
REPORT = "review.md"
ENV = "AK_HAND_IN"
CONTINUE = "AK_HAND_IN_CONTINUE"
OUTPUT_CAP = 8 * 1024


def item_text(row):
    text = f"{row['path']}:{row['line']} - {row['what']} - {row['why']}"
    evidence = row["evidence"]
    if "quote" in evidence:
        text += "\nQuote:\n" + evidence["quote"]
    else:
        text += f"\n$ {evidence['run']}\n[exit {evidence['returncode']}]\n{evidence['output']}"
    if row["kind"] == "follow-up":
        text += "\nBefore the task: " + row["before"]
    return text.strip()


@dataclass
class Review:
    records: list

    @property
    def done(self):
        return bool(self.records) and self.records[-1]["kind"] == "done"

    @property
    def findings(self):
        return [row for row in self.records if row["kind"] == "finding"]

    @property
    def verdict(self):
        return ("FAIL" if self.findings else "PASS") if self.done else None

    @property
    def followups(self):
        return [item_text(row) for row in self.records if row["kind"] == "follow-up"]

    @property
    def text(self):
        parts = [f"VERDICT: {self.verdict}"] if self.done else []
        for kind, heading in (("finding", "Findings"), ("follow-up", "Follow-ups")):
            items = ["- " + item_text(row).replace("\n", "\n  ")
                     for row in self.records if row["kind"] == kind]
            if items:
                parts.append(f"## {heading}\n" + "\n".join(items))
        return "\n\n".join(parts) + "\n"


def read(path):
    """None means a stub never reached worker.call; an empty review still needs done."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        if not rows or rows[0].get("kind") != "turn":
            return Review([])
        records = rows[1:]
        if any(row.get("kind") not in ("finding", "follow-up", "done") for row in records):
            return Review([])
        for row in records:
            if row["kind"] != "done":
                item_text(row)
        if any(row["kind"] == "done" for row in records[:-1]):
            return Review([])
        return Review(records)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return Review([])


def start(out_dir, workspace, previous=None):
    """A resumed session keeps its records, but completion belongs to this call alone."""
    path = Path(out_dir).resolve() / FILE
    review = read(previous) if previous else None
    rows = [{"kind": "turn", "workspace": str(Path(workspace).resolve())}]
    if review:
        rows += [row for row in review.records if row["kind"] != "done"]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return str(path)


def checked(argv, workspace):
    if argv == ["done"]:
        return {"kind": "done"}
    if not argv or argv[0] not in ("finding", "follow-up") or len(argv) < 4:
        raise config.Error("use finding or follow-up with path:line, what, why it matters and evidence, or done alone")
    kind, site, what, why, *args = argv
    if not what.strip() or not why.strip():
        raise config.Error("supply both what is wrong and why it matters")
    flags = {}
    for i in range(0, len(args), 2):
        flag = args[i]
        if flag not in ("--run", "--quote", "--before") or flag in flags or i + 1 == len(args):
            raise config.Error("use one evidence flag, --run COMMAND or --quote LINES, and --before PROOF for a follow-up")
        flags[flag] = args[i + 1]
    if ("--run" in flags) == ("--quote" in flags) or not (flags.get("--run") or flags.get("--quote") or "").strip():
        raise config.Error("supply evidence with exactly one of --run COMMAND or --quote LINES")
    if kind == "follow-up" and not flags.get("--before", "").strip():
        raise config.Error("add --before with the base commit or a quote proving the defect existed before the task")
    if kind == "finding" and "--before" in flags:
        raise config.Error("use follow-up for a defect that existed before the task")
    name, colon, line = site.rpartition(":")
    if not colon or not name or not line.isdecimal():
        raise config.Error("name the location as path:line with a numeric line")
    root = Path(workspace).resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise config.Error("name a file that exists inside this checkout")
    content = path.read_text(errors="replace")
    line = int(line)
    if not 1 <= line <= len(content.splitlines()):
        raise config.Error(f"choose a line from 1 to {len(content.splitlines())} in {path.relative_to(root)}")
    if "--quote" in flags:
        if flags["--quote"] not in content:
            raise config.Error("use a quote found verbatim in the named file")
        evidence = {"quote": flags["--quote"]}
    else:
        # A reproduction may exit zero while printing the wrong result; retain both facts.
        env = dict(os.environ)
        env.pop(ENV, None)
        env.pop(CONTINUE, None)
        # Spool rather than holding an arbitrarily large reproduction in memory.
        with tempfile.TemporaryFile(dir=root) as output:
            result = subprocess.run(["bash", "-c", flags["--run"]], cwd=root, env=env,
                                    stdout=output, stderr=subprocess.STDOUT)
            size = output.tell()
            output.seek(0)
            if size > OUTPUT_CAP:
                head = output.read(OUTPUT_CAP // 2).decode("utf-8", "replace")
                output.seek(-OUTPUT_CAP // 2, os.SEEK_END)
                text = (head + "\n[output truncated; rerun the command for full evidence]\n"
                        + output.read(OUTPUT_CAP // 2).decode("utf-8", "replace"))
            else:
                text = output.read(OUTPUT_CAP).decode("utf-8", "replace")
        evidence = {"run": flags["--run"], "returncode": result.returncode,
                    "output": text}
    row = {"kind": kind, "path": str(path.relative_to(root)), "line": line,
           "what": what, "why": why, "evidence": evidence}
    if kind == "follow-up":
        row["before"] = flags["--before"]
    return row


def main(argv):
    if command_help.show("hand-in", argv):
        return 0
    path = os.environ.get(ENV)
    if not path or not Path(path).is_file():
        raise config.Error("hand-in needs an active review turn; use it from the worker's shell")
    try:
        with Path(path).open("r+", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            rows = [json.loads(line) for line in fh]
            if not rows or rows[0].get("kind") != "turn":
                raise config.Error("the review turn's record file is invalid; ask the loop to retry")
            if any(row.get("kind") == "done" for row in rows):
                raise config.Error("this review is already done; hand in records before done")
            row = checked(argv, rows[0]["workspace"])
            fh.write(json.dumps(row) + "\n")
    except (OSError, ValueError, KeyError, AttributeError) as exc:
        raise config.Error("cannot hand in this record: " + " ".join(str(exc).split())) from None
    return 0
