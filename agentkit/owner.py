"""The owner's parts of a repository: what lands only on the owner's yes.

A repository names them on one front-matter line of its AGENTS.md, read from the target branch,
so a change never loosens its own guard: `owner: <file or folder>, <file>#<Heading>`.  Once it
names any, the front matter itself is the owner's too.  A section runs from its `## Heading` line
to the next line starting `## `; one holding a code fence (``` or ~~~), or a heading the file
lacks, runs to the end of the file.

This module only reads and compares; run.py does the git, with its own runner and
`GIT_NO_REPLACE_OBJECTS`, and hands the bytes here.  A part is compared byte for byte, so a
change git cannot read as the same object or the same section text is a change.
"""

import hashlib

FRONT = "---"               # the heading that names a file's front matter
FENCES = ("```", "~~~")     # either opens a fenced block a `## ` inside does not close


def unquote(item):
    """One `owner:` path as written, with a single layer of surrounding quotes removed."""
    item = item.strip()
    if len(item) >= 2 and item[0] == item[-1] and item[0] in "'\"":
        item = item[1:-1].strip()
    return item.strip("/")


def parts(declaration):
    """(path, heading or None) for each part an `owner:` value names, the front matter last.

    A value YAML would read as more than the flat list ak writes -- a block or flow form, a
    path with a `..`, a quote left inside after unwrapping -- names nothing but the front matter,
    so the owner is still asked rather than the guard quietly dropped.
    """
    named, safe = [], True
    for raw in (declaration or "").split(","):
        path, _, heading = unquote(raw).partition("#")
        if not path:
            continue
        if any(ch in path for ch in "'\"") or ".." in path.split("/"):
            safe = False
            continue
        named.append((path, heading.strip() or None))
    if not named and not safe:
        named = []            # an unreadable value protects the front matter alone, below
    return (named + [("AGENTS.md", FRONT)]) if (named or not safe) else []


def name(path, heading):
    """How a part is named to the owner."""
    return path if heading is None else (f"{path} front matter" if heading == FRONT
                                         else f"{path}#{heading}")


def piece(blob, heading):
    """A file's front matter or `## heading` section; the whole file when it has none.

    `blob` is the file's text kept byte-lossless (surrogateescape), so the comparison stays
    byte for byte.  Measured as a reader reads it: either fence marker holds a `## ` line inside
    the section, and a section that opens one runs to the end of the file.
    """
    if blob is None:
        return None
    lines = blob.splitlines(keepends=True)
    if heading == FRONT:
        if not lines or lines[0].rstrip("\r\n") != "---":
            return blob
        end = next((i for i in range(1, len(lines)) if lines[i].rstrip("\r\n") == "---"), None)
        return "".join(lines[:end + 1]) if end is not None else blob
    want = "## " + heading
    start = next((i for i, line in enumerate(lines) if line.rstrip() == want), None)
    if start is None:
        return blob
    end, fenced = len(lines), False
    for i in range(start + 1, len(lines)):
        stripped = lines[i].lstrip()
        if any(stripped.startswith(f) for f in FENCES):
            fenced = not fenced
        elif lines[i].startswith("## ") and not fenced:
            end = i
            break
    return "".join(lines[start:end])


def digest(contents):
    """One fingerprint of every part's content, byte for byte: [(path, heading, text|None)].

    The text is the byte-lossless surrogateescape form, hashed as its own bytes, so two
    different files never fold to one fingerprint.
    """
    sink = hashlib.sha256()
    for path, heading, body in contents:
        sink.update(repr((path, heading, body is None)).encode())
        if body is not None:
            sink.update(b"\0" + body.encode("utf-8", "surrogateescape") + b"\0")
    return sink.hexdigest()
