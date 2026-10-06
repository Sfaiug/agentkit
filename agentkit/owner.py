"""The owner's parts of a repository: what lands only on the owner's yes.

A repository names them on one front-matter line of its AGENTS.md, read from the target
branch, so a change never loosens its own guard: `owner: <file or folder>, <file>#<Heading>`.
Once it names any, the front matter itself is the owner's too.  A section runs from its
`## Heading` line to the next line starting `## `; one holding a code fence, or a heading the
file lacks, runs to the end of the file.

A change touches a part when the part differs between the change's merge base and its head:
a file's or folder's git object, or a section's text.  The owner's yes is for the exact
content of every part at the commit asked about, so a later change to them asks again.  It
is kept under ak's state, which a run's box cannot write.
"""

import hashlib
import json
import os
import subprocess

from . import config

FRONT = "---"               # the heading that names a file's front matter


def parts(declaration):
    """(path, heading or None) for each part an `owner:` value names, the front matter last."""
    named = []
    for item in (declaration or "").split(","):
        path, _, heading = item.strip().partition("#")
        if path.strip().strip("/"):
            named.append((path.strip().strip("/"), heading.strip() or None))
    return named + [("AGENTS.md", FRONT)] if named else []


def name(path, heading):
    """How a part is called to the owner."""
    return path if heading is None else (f"{path} front matter" if heading == FRONT
                                         else f"{path}#{heading}")


def piece(text, heading):
    """A file's front matter or `## heading` section; the whole text when it has none."""
    lines = text.splitlines(keepends=True)
    if heading == FRONT:
        end = next((i for i in range(1, len(lines)) if lines[i].rstrip("\r\n") == "---"), None)
        return "".join(lines[:end + 1]) if lines[:1] and lines[0].rstrip("\r\n") == "---" \
            and end is not None else text
    start = next((i for i, line in enumerate(lines) if line.rstrip() == f"## {heading}"), None)
    if start is None:
        return text
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    section = "".join(lines[start:end])
    return "".join(lines[start:]) if "```" in section else section


def git(wt, *args):
    """git's output, or None where it names no such object (a part that is not there)."""
    proc = subprocess.run(["git", "-C", str(wt), *args], capture_output=True, timeout=60)
    if proc.returncode == 0:
        return proc.stdout
    if b"Not a valid object name" in proc.stderr or proc.returncode == 1:
        return None
    raise config.Error(f"git {' '.join(args)}: {proc.stderr.decode(errors='replace').strip()}")


def content(wt, rev, path, heading):
    """What one part is at `rev`: its git object, or its section's text; None when absent."""
    obj = git(wt, "rev-parse", "--verify", "--quiet", f"{rev}:{path}")
    if obj is None or heading is None:
        return obj.decode().strip() if obj else None
    blob = git(wt, "cat-file", "blob", obj.decode().strip())
    return piece(blob.decode("utf-8", "replace"), heading) if blob is not None else None


def touched(wt, declaration, base, head):
    """The names of the parts a change from `base` to `head` touches."""
    return [name(path, heading) for path, heading in parts(declaration)
            if content(wt, base, path, heading) != content(wt, head, path, heading)]


def digest(wt, declaration, rev):
    """One fingerprint of every part's content at `rev`."""
    whole = [[path, heading, content(wt, rev, path, heading)] for path, heading in parts(declaration)]
    return hashlib.sha256(json.dumps(whole).encode()).hexdigest()


def _record(run_id):
    if not run_id or os.path.basename(run_id) != run_id or run_id in (".", ".."):
        raise config.Error(f"not a run id: {run_id!r}")
    return config.STATE / "owner-yes" / f"{run_id}.json"


def said(run_id):
    """The fingerprint the owner said yes to for that run, or None."""
    try:
        return json.loads(_record(run_id).read_text()).get("digest")
    except (OSError, ValueError, AttributeError):
        return None


def say(run_id, fingerprint):
    """Keep the owner's yes to that content for that run."""
    path = _record(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}")
    tmp.write_text(json.dumps({"digest": fingerprint}) + "\n")
    os.replace(tmp, path)
