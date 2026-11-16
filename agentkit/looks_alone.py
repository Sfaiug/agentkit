"""Which changes are of looks alone: every path a change names against its target -- added,
edited, removed, either side of a rename -- a stylesheet, a raster image, a font or prose, and
none of them AGENTS.md, which holds ak's own rules for the project.  Only on a target that
declares both `health:` and `deployed:`, so ak reverts a release whose health breaks
(`watch.after_merge_revert`), does such a change land on its own quick checks and no whole
suite (`land._looks`), its merge saying so with TRAILER.  What it breaks the next whole run
finds as any red on the target.

Owner, 16 Nov 2026: "Yes, once auto-undo works" -- such a change waited a median 3.2 h in a line
for a suite that reads almost none of it.
"""

from pathlib import PurePosixPath

from . import change_rules, gitcall

TRAILER = "Looks-Alone-Tree"
# SVG and page wording inside markup are not here: either can hold a script.  Nor MDX, whose
# prose imports and runs components.
SUFFIXES = {".css", ".scss", ".sass", ".less",
            ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".bmp", ".ico",
            ".woff", ".woff2", ".ttf", ".otf", ".eot",
            *change_rules.PROSE} - {".mdx"}


def changes(repo, target, heads):
    """Those of `heads` whose change against `target` is of looks alone, where `target` declares
    both `health:` and `deployed:`; none elsewhere, `heads` then never read, nor where git
    cannot say."""
    if not all(gitcall.declared_at(repo, target, key) for key in ("health", "deployed")):
        return set()
    alone = set()
    for head in heads:
        code, out = gitcall.git_out(repo, "diff", "--name-only", "--no-renames", "-z",
                                    f"{target}...{head}")
        paths = [PurePosixPath(path) for path in out.split("\0") if path]
        if not code and paths and all(path.name != "AGENTS.md" and path.suffix.lower() in SUFFIXES
                                      for path in paths):
            alone.add(head)
    return alone
