"""One checked worker channel for every harness: append evidence and close turns."""

from dataclasses import dataclass, field
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
FINDINGS_ENV = "AK_HAND_IN_FINDINGS"
FINDINGS_FILE = "findings.json"
OUTPUT_CAP = 8 * 1024
CLOSING = ("done", "blocked", "not-needed")


def output_excerpt(output, start=0):
    size = output.tell() - start
    output.seek(start)
    if size > OUTPUT_CAP:
        head = output.read(OUTPUT_CAP // 2).decode("utf-8", "replace")
        output.seek(-OUTPUT_CAP // 2, os.SEEK_END)
        return (head + "\n[output truncated; rerun the command for full evidence]\n"
                + output.read(OUTPUT_CAP // 2).decode("utf-8", "replace"))
    return output.read(OUTPUT_CAP).decode("utf-8", "replace")


def proof_text(proof):
    status = "did not finish" if proof.get("killed") or proof["returncode"] < 0 else f"exit {proof['returncode']}"
    return f"[{status}]\n{proof['output']}"


def proof_failed(proof):
    # Output can report a missing application file even when the proof ran.
    return (proof["returncode"] > 0 and proof["returncode"] not in (126, 127)
            and not proof.get("killed"))


def item_text(row):
    text = (item_text(row["finding"]) + "\nDispute: " + row["why"] if row["kind"] == "dispute"
            else f"{row['path']}:{row['line']} - {row['what']} - {row['why']}")
    evidence = row["evidence"]
    if "quote" in evidence:
        text += "\nQuote:\n" + evidence["quote"]
    else:
        text += f"\n$ {evidence['run']}\n"
        if "commit" in evidence:
            text += f"Commit {evidence['commit']}:\n"
        text += proof_text(evidence)
        if "base" in evidence:
            text += f"\nBase {evidence['base']['sha']}:\n" + proof_text(evidence["base"])
    if row["kind"] == "follow-up" or row.get("dropped"):
        text += "\nBefore the task: " + row["before"]
    if row.get("dropped"):
        text += "\nDropped follow-up: " + row["dropped"]
    return text.strip()


@dataclass
class Review:
    records: list
    handed_findings: list = field(default_factory=list)

    @property
    def closing(self):
        return self.records[-1] if self.records and self.records[-1]["kind"] in CLOSING else None

    @property
    def done(self):
        return bool(self.records) and self.records[-1]["kind"] == "done"

    @property
    def findings(self):
        return [row for row in self.records if row["kind"] == "finding"]

    @property
    def disputes(self):
        return [row for row in self.records if row["kind"] == "dispute"]

    @property
    def verdict(self):
        return ("FAIL" if self.findings else "PASS") if self.done else None

    @property
    def followups(self):
        return [item_text(row) for row in self.records if row["kind"] == "follow-up"]

    @property
    def notes(self):
        return [item_text(row) for row in self.records if row["kind"] == "note"]

    @property
    def text(self):
        parts = [f"VERDICT: {self.verdict}"] if self.done else []
        for kind, heading in (("finding", "Findings"), ("follow-up", "Follow-ups"),
                              ("note", "Notes"), ("dispute", "Disputes")):
            items = ["- " + item_text(row).replace("\n", "\n  ")
                     for row in self.records if row["kind"] == kind]
            if items:
                parts.append(f"## {heading}\n" + "\n".join(items))
        return "\n\n".join(parts) + "\n"


def read(path):
    """None means a stub never reached worker.call; an empty turn still needs a closing."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        if not rows or rows[0].get("kind") != "turn":
            return Review([])
        records = rows[1:]
        role = rows[0].get("role", "reviewer")
        allowed = (("finding", "follow-up", "done") if role.startswith("reviewer")
                   else ("dispute", *CLOSING) if role.startswith("fixer") else CLOSING)
        if any(row.get("kind") not in allowed for row in records):
            return Review([])
        for row in records:
            if row["kind"] in ("blocked", "not-needed"):
                if not isinstance(row.get("why"), str) or not row["why"].strip():
                    return Review([])
            elif row["kind"] != "done":
                item_text(row)
        if any(row["kind"] in CLOSING for row in records[:-1]):
            return Review([])
        return Review(records, rows[0].get("findings", []))
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return Review([])


def start(out_dir, workspace, previous=None, role="reviewer", findings=None):
    """A resumed session keeps its records, but completion belongs to this call alone."""
    path = Path(out_dir).resolve() / FILE
    review = read(previous) if previous else None
    handed = (json.loads(Path(findings).read_text()) if findings
              else review.handed_findings if review else [])
    rows = [{"kind": "turn", "workspace": str(Path(workspace).resolve()), "role": role,
             "findings": handed}]
    if review:
        rows += [row for row in review.records if row["kind"] not in CLOSING]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return str(path)


def checked_site(site, workspace, quote=None):
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
    if quote is not None and (not quote.strip() or quote not in content):
        raise config.Error("use a quote found verbatim in the named file")
    return root, path, line


def checked(argv, workspace, role="reviewer", findings=()):
    reviewing = role.startswith("reviewer")
    if argv and argv[0] in ("blocked", "not-needed"):
        if reviewing:
            raise config.Error("blocked and not-needed are only for executor or fixer turns")
        if len(argv) != 2 or not argv[1].strip():
            raise config.Error('use blocked or not-needed with one nonempty "why"')
        return {"kind": argv[0], "why": argv[1].strip()}
    if argv and argv[0] in ("finding", "follow-up") and not reviewing:
        raise config.Error("finding and follow-up are only for review turns")
    if argv and argv[0] == "dispute" and not role.startswith("fixer"):
        raise config.Error("dispute is only for fixer turns")
    if argv == ["done"]:
        return {"kind": "done"}
    if argv and argv[0] == "dispute":
        if len(argv) < 3 or not argv[2].strip():
            raise config.Error('use dispute with path:line, "why it is wrong" and evidence')
        kind, site, why, *args = argv
        finding = next((row for row in findings if site == f"{row['path']}:{row['line']}"), None)
        if finding is None:
            allowed = ", ".join(f"{row['path']}:{row['line']}" for row in findings) or "none"
            raise config.Error(f"dispute must name a blocking finding handed to this turn; you may dispute: {allowed}")
        what = finding["what"]
    else:
        if not argv or argv[0] not in ("finding", "follow-up") or len(argv) < 4:
            raise config.Error("use finding or follow-up with path:line, what, why it matters and evidence, dispute, or done alone")
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
        raise config.Error("add --before with the base or an ancestor commit, or verbatim lines from the named file at base")
    if kind != "follow-up" and "--before" in flags:
        raise config.Error("use follow-up for a defect that existed before the task")
    root, path, line = checked_site(site, workspace, flags.get("--quote"))
    if "--quote" in flags:
        evidence = {"quote": flags["--quote"]}
    else:
        env = dict(os.environ)
        env.pop(ENV, None)
        env.pop(CONTINUE, None)
        env.pop(FINDINGS_ENV, None)
        # Spool rather than holding an arbitrarily large reproduction in memory.
        with tempfile.TemporaryFile(dir=root) as output:
            result = subprocess.run(["bash", "-c", flags["--run"]], cwd=root, env=env,
                                    stdout=output, stderr=subprocess.STDOUT)
            text = output_excerpt(output)
        if kind == "finding" and result.returncode == 0:
            raise config.Error("the command exited 0; write it to fail while the defect exists, or use --quote")
        if kind == "dispute" and result.returncode != 0:
            raise config.Error("a dispute's command must exit 0 to show the behaviour is right")
        evidence = {"run": flags["--run"], "returncode": result.returncode,
                    "output": text}
    row = {"kind": kind, "path": str(path.relative_to(root)), "line": line,
           "what": what, "why": why, "evidence": evidence}
    if kind == "follow-up":
        row["before"] = flags["--before"]
    if kind == "dispute":
        row["finding"] = finding
    return row


def main(argv):
    if command_help.show("hand-in", argv):
        return 0
    path = os.environ.get(ENV)
    if not path or not Path(path).is_file():
        raise config.Error("hand-in needs an active worker turn; use it from the worker's shell")
    try:
        with Path(path).open("r+", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            rows = [json.loads(line) for line in fh]
            if not rows or rows[0].get("kind") != "turn":
                raise config.Error("the worker turn's record file is invalid; ask the loop to retry")
            if any(row.get("kind") in CLOSING for row in rows):
                raise config.Error("this turn is already closed; hand in records before done, blocked or not-needed")
            row = checked(argv, rows[0]["workspace"], rows[0].get("role", "reviewer"),
                          rows[0].get("findings", []))
            fh.write(json.dumps(row) + "\n")
    except (OSError, ValueError, KeyError, AttributeError) as exc:
        raise config.Error("cannot hand in this record: " + " ".join(str(exc).split())) from None
    return 0
