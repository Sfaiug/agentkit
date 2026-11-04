"""Scope and rule refusals, shared by the round loop and a worker's hand-in."""

import re

from . import config, gitcall


# The front matter lines ak reads; any other name (a typo of `tests:` included) is read by nothing.
# `content:` names, as space-separated path prefixes, the project's own product text (its pages,
# its knowledge base): words that are the product, not notes about the code.
# `setup:` names the file that makes the machine ak runs on ready for the project (`machine_setup`).
# `alive:` names the command that tells ak, from its own machine, the product is up (`alive`).
# `nightly:` names the command that prints the project's newest night (`nightly`).
# config.POLICY's keys are the project's own numbers (`config.policy`).
FRONT_KEYS = ("tests", "health", "deployed", "cleanup", "users", "features", "suite_image", "content",
              "setup", "alive", "nightly", *config.POLICY)


# The words an AGENTS.md body may grow to: what the project is, and the few facts no code can
# hold.  A floor, not a target: past it a body only shrinks, so what a branch would add there
# moves into the test, check or comment that holds it by itself, and no file ever needs a cleanup.
BODY_WORDS = 300


# Prose is where a branch would put facts no check holds.  Past AGENTS.md (`BODY_WORDS`) and a
# root README of `README_WORDS` (what the project is and how to start it), a prose file only
# shrinks and a new one holds nothing, so no guide, map or notes file ever regrows; the product
# text the base's `content:` names grows freely.
PROSE = (".md", ".markdown", ".mdx", ".rst", ".adoc")
README_WORDS = 300


# An answer key: a black-box test of the program from outside, which a port to another language
# answers to.  Once a base holds one, every change to its Python brings one (`keyless_python`).
KEY = re.compile(r"tests/test_key_[^/]*\.py")


def _diff_refs(wt, base_sha, head):
    # A workspace tree starts at HEAD's fork point; the run's base still supplies its rules.
    return ((f"{base_sha}...HEAD",) if head == "HEAD"
            else (gitcall.git(wt, "merge-base", base_sha, "HEAD"), head))


def files_scope(wt, base_sha, specs=(), scratch=False, *, head="HEAD"):
    """A gate failure for paths outside the task's Git pathspecs, else an empty string."""
    if not specs or scratch:
        return ""
    cmd = ["git", "-C", str(wt), "diff", "--name-only", "--no-renames", "-z",
           *_diff_refs(wt, base_sha, head)]
    paths = []
    for suffix in ([], ["--", *specs]):
        # gitcall.git() strips whitespace, which can be part of the first path's name.
        code, out, err = gitcall.tool_run(cmd + suffix)
        if code != 0:
            raise (gitcall.Stopped if gitcall.stopped(code, err) else config.Error)(
                f"files: git diff failed in {wt}: {err.strip()}")
        paths.append(set(out.split("\0")) - {""})
    outside = sorted(paths[0] - paths[1])
    return "outside files: " + ", ".join(outside) if outside else ""


def rules_check(wt, base_sha, scratch=False, *, head="HEAD"):
    """Refuse a branch that grows prose past what it may hold (`prose_grown`), changes Python
    with no answer key (`keyless_python`), or changes AGENTS.md so workers would not get it as
    written: a link, a Git filter, more than a harness reads of it, or a front matter line ak
    does not read; or grows its body past `BODY_WORDS` and past what the base holds.  A branch
    that leaves the file alone, or deletes it, passes that part."""
    if scratch:
        return ""
    failure = prose_grown(wt, base_sha, head) or keyless_python(wt, base_sha, head)
    if failure:
        # a name `git_bytes` keeps whole can hold bytes no log or prompt written as UTF-8 takes
        return failure.encode("utf-8", "surrogateescape").decode("utf-8", "backslashreplace")
    if not gitcall.git(wt, "diff", "--name-only", "--no-renames", *_diff_refs(wt, base_sha, head), "--", "AGENTS.md"):
        return ""
    entry = gitcall.git(wt, "ls-tree", head, "--", "AGENTS.md")
    if not entry:
        return ""       # the branch deleted it
    if entry.startswith("120000 "):
        # following it would mean redoing how Linux opens a path, inside Git's trees
        return ("AGENTS.md is a link, which ak does not follow, so workers would get no rules "
                "from it: make AGENTS.md the file itself.")
    if not gitcall.git(wt, "check-attr", "filter", "--", "AGENTS.md").endswith(("unspecified", "unset")):
        return "AGENTS.md must not go through a Git filter: ak reads its front matter as committed."
    ceiling = config.instruction_ceiling()
    try:
        held = gitcall.rules_bytes(wt, head)
    except gitcall.Stopped:
        raise
    except config.Error as exc:
        unknown = (f"its size against the {ceiling[0]} bytes {ceiling[1]} reads of it is unknown"
                   if ceiling else "ak cannot check it")
        return f"AGENTS.md could not be read as a checkout holds it, so {unknown}: {exc}"
    if ceiling and len(held) > ceiling[0]:
        return (f"AGENTS.md is {len(held)} bytes, past the {ceiling[0]} bytes {ceiling[1]} "
                "reads of it: tighten it.")
    words = len(gitcall.agents_body(wt, head).split())
    before = len(gitcall.agents_body(wt, base_sha).split())
    if words > max(BODY_WORDS, before):
        return (f"AGENTS.md's body grows from {before} to {words} words; past {BODY_WORDS} it "
                "only shrinks. Move what this adds into a test, a check or a comment at the code "
                "it is about.")
    text = held.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
    unread = unknown_front_lines(text.strip())
    if not unread:
        return ""
    return (f"AGENTS.md front matter has lines ak does not read: "
            f"{', '.join(f'`{line}`' for line in unread)} (it reads {', '.join(FRONT_KEYS)}): "
            "remove them, or fix the misspelled name.")


def prose_grown(wt, base_sha, head="HEAD"):
    """The refusal for the first prose file (`PROSE`) the branch grows past what it may hold, or "".

    Measured against the base, whose `content:` is the one that counts: a branch cannot widen
    its own exemption.  A rename is a new file, so no file grows by moving.
    """
    content = (gitcall.declared_at(wt, base_sha, "content") or "").split()
    # a link turned file (T) grows too, and names keep every byte, leading spaces included
    changed = gitcall.git_bytes(wt, "diff", "--name-only", "--no-renames", "--diff-filter=AMT", "-z",
                                *_diff_refs(wt, base_sha, head))
    for path in filter(None, changed.split("\0")):
        if (not path.lower().endswith(PROSE) or path == "AGENTS.md"
                or any(path.startswith(prefix) for prefix in content)):
            continue
        before, words = (len(gitcall.git(wt, "cat-file", "-p", f"{ref}:{path}", check=False).split())
                         for ref in (base_sha, head))
        floor = README_WORDS if path == "README.md" else 0
        if words > max(floor, before):
            return (f"{path} grows from {before} to {words} words; prose outside the project's "
                    f"`content:` {f'past {floor} words ' if floor else ''}only shrinks. Move what "
                    "this adds into a test, a check or a comment at the code it is about; words that are "
                    "the product itself need the base's `content:` to name them first.")
    return ""


def keyless_python(wt, base_sha, head="HEAD"):
    """The refusal for a branch that changes Python outside tests/ with no answer key (`KEY`), or "".

    In force where the base holds a key: the base's keys count, so a branch deleting its own frees
    nothing.  Decided from git's change records alone: a deletion brings nothing, any other record
    brings its new path, and only a pure move (R100) of a file already named .py leaves Python as
    it was.
    """
    # `-r` lists files, never a directory named like a key.  `git` replaces only bytes that are not
    # UTF-8, never "/" or ASCII: a key's name keeps its shape.
    held = gitcall.git(wt, "ls-tree", "-r", "-z", "--name-only", base_sha, "--", "tests/")
    if not any(KEY.fullmatch(name) for name in held.split("\0")):
        return ""
    fields = iter(gitcall.git_bytes(wt, "diff", "--name-status", "--find-renames", "-z",
                                    *_diff_refs(wt, base_sha, head)).split("\0"))
    python, keyed = [], False
    for status in fields:
        if not status:
            break       # the NUL ending the last record
        old = new = next(fields)
        if status == "D":
            continue
        if status[0] == "R":
            new = next(fields)
        if KEY.fullmatch(new):
            keyed = True
        elif (new.endswith(".py") and not new.startswith("tests/")
              and (status != "R100" or not old.endswith(".py"))):
            python.append(new)
    if keyed or not python:
        return ""
    return (f"Python changed with no answer key: {', '.join(python)}. A change to a .py file "
            "outside tests/ adds, edits or moves in a tests/test_key_*.py in the same change: a "
            "black-box test of what it does.")


def unknown_front_lines(text):
    """The front matter lines of AGENTS.md text whose name ak never reads, as written."""
    match = gitcall.FRONT.match(text)
    if not match:
        return []
    return [line.strip() for line in match.group(1).splitlines()
            if line.strip() and not line.lstrip().startswith("#")
            and line.partition(":")[0].strip() not in FRONT_KEYS]
