"""A task file as the orchestrator writes one from templates/task.md, and the runs it started.

`write` puts it at `<root>/tasks/<slug>.md`, outside HOME and the repository: front matter
between `---` lines (`repo:`, then each `front` key in order, a list repeating its key), then
`# <title>`, `## Goal`, `## Constraints` as `- ` lines, `## Done when` holding a bash fence of
one check a line, and `body`.  A part that would be empty is left out.

A run is found by listing HOME/.agentkit/runs, never by reading what ak printed.

    from fixtures.akbin import Home
    from fixtures import taskfile
    with Home() as home:
        task = taskfile.write(home, home.path / "code/widgets", front={"rounds": 1})
        home.ak("run", str(task), "--no-merge")
        run = taskfile.only_run(home)
"""

import re

GOAL = "Nothing: the fake adapters do the work."


def write(home, repo, title="Add retry file", *, goal=GOAL, constraints=(),
          done_when=("test -f retry.txt",), front=None, body="", name=None):
    """Write the task file and return its path; `body` is text after the last section."""
    lines = [f"repo: {repo}"] if repo is not None else []
    for key, value in (front or {}).items():
        for item in value if isinstance(value, (list, tuple)) else [value]:
            lines.append(f"{key}: {item}")
    # An empty front matter is no front matter: ak reads `---` then `---` as one left open.
    lines = ["---", *lines, "---"] if lines else []
    lines += [f"# {title}", "", "## Goal", goal, ""]
    if constraints:
        lines += ["## Constraints", *(f"- {line}" for line in constraints), ""]
    if done_when:
        lines += ["## Done when", "```bash", *done_when, "```", ""]
    path = home.root / "tasks" / f"{name or slug(title)}.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(lines) + body)
    return path


def slug(title):
    """The title's words in lowercase, joined by hyphens."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def runs(home):
    """Every run's directory, oldest first by name."""
    root = home.path / ".agentkit" / "runs"
    found = root.iterdir() if root.is_dir() else ()
    return sorted(path for path in found if path.is_dir() and not path.name.startswith("."))


def only_run(home):
    """The one run's directory; anything else fails the test, naming what is there."""
    found = runs(home)
    assert len(found) == 1, f"one run expected, found {[path.name for path in found]}"
    return found[0]
