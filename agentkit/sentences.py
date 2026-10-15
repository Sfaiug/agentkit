"""Markdown merged sentence by sentence: the merge driver every git call of ak's carries.

Prose keeps a paragraph on one line, so git's line rule calls two edits of one paragraph a
conflict even where they change different sentences: the lease scan parks a run on it and the
landing line hands it to a fixer.  ak's git calls (`gitcall.tool_env`) name this the driver
for `*.md`: each text is cut after every sentence, the cut texts are merged by git's own
three-way merge, and the result is joined back byte for byte.  Edits inside one sentence that
clash are merged as git merges them without this driver, conflict markers included.  A
repository's own `.gitattributes` still decides its paths first.

Git runs this file as a script, so it imports nothing of ak's.
"""

import os
import re
import subprocess
import sys
import tempfile

NAME = "ak-sentences"

# a private-use character no text carries: the cut ends its line with it, the join takes it out
MARK = ""

# a sentence's end: its stop, any closing quote, bracket or emphasis, then the spaces before
# the next sentence on the same line
END = re.compile(r"[.!?;][\"')\]*_`]* +(?=\S)")


def cut(text):
    """`text` with a line break, marked, after every sentence that ends inside a line."""
    return END.sub(lambda found: found.group(0) + MARK + "\n", text)


def joined(text):
    """The text `cut` was given back."""
    return text.replace(MARK + "\n", "")


def read(path):
    with open(path, "rb") as handle:
        return handle.read().decode("utf-8", "surrogateescape")


def write(path, text):
    with open(path, "wb") as handle:
        handle.write(text.encode("utf-8", "surrogateescape"))


def merge(base, ours, theirs, marker_size="7"):
    """Git's merge driver (`%O %A %B %L`): `ours` overwritten with the three-way merge of the two
    sides of `base`; 0 when it merged cleanly.  Sentence by sentence first; where that leaves a
    clash, or a text already carries the mark, the line merge git would have made."""
    texts = [read(path) for path in (ours, base, theirs)]
    if not any(MARK in text for text in texts):
        with tempfile.TemporaryDirectory(prefix="ak-sentences-") as work:
            files = []
            for n, text in enumerate(texts):
                files.append(os.path.join(work, str(n)))
                write(files[-1], cut(text))
            merged = subprocess.run(["git", "merge-file", "-p", *files], capture_output=True)
        result = joined(merged.stdout.decode("utf-8", "surrogateescape"))
        if merged.returncode == 0 and MARK not in result:
            write(ours, result)
            return 0
    lines = subprocess.run(["git", "merge-file", f"--marker-size={marker_size}",
                            "-L", "current", "-L", "base", "-L", "incoming", ours, base, theirs])
    return 0 if lines.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(merge(*sys.argv[1:5]))
