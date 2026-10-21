"""GitHub for an answer-key Home: a `gh` that keeps pull requests in a file and merges on disk.

`GitHub(home)` puts a `gh` first on the program's PATH that answers as GitHub would for the
repositories tests/fixtures/gitrig.py makes: the slug `<owner>/<name>` is the bare origin
`<root>/remotes/<owner>/<name>.git`, a PR is `https://github.com/<slug>/pull/<n>`, and the
viewer is `login`.

`pr create` opens a PR, numbered from 1 in its repository, and writes `refs/pull/<n>/head`
into the origin; `open_pr` opens one as somebody else.  `pr merge` merges it there as its
author (`--squash`, `--merge` or `--rebase`), refusing a head other than
`--match-head-commit`, a draft or a conflict; `--delete-branch` deletes its branch.  `pr
view`, `pr list` and `pr comment` answer from the same state, a body handed in by file kept
as its text; `--json` takes gh's field names and `-q` a path such as `.data.login`, then
`| tojson` if asked.  Anything else is refused, naming the call.

The state is `<root>/github.json`; every call is logged where `home.calls("gh")` reads it.

    from fixtures.akbin import Home
    from fixtures.fakegh import GitHub
    from fixtures.gitrig import Rig
    with Home() as home:
        rig, gh = Rig(home, "widgets"), GitHub(home)
        sha = rig.branch("fix-api", {"api.py": "x = 2\\n"})
        home.run("gh", "pr", "create", "--head", "fix-api", "--title", "Fix api", "--body", "",
                 cwd=rig.path)
        home.run("gh", "pr", "merge", "1", "--squash", "--match-head-commit", sha, cwd=rig.path)
        assert gh.pr(1)["merge"]["method"] == "squash" and "api.py" in rig.files()
"""

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

FLAGS = {"--squash", "--merge", "--rebase", "--delete-branch", "--paginate", "--draft",
         "--remote", "--admin", "--auto", "--fill", "--include", "--silent", "--web"}
PULL = re.compile(r"https://github\.com/([^/]+/[^/]+)/pull/(\d+)/?")
REMOTES = None    # the Home's remotes, set as each call reads the state


class Refused(Exception):
    """What gh prints on stderr, exiting 1, for a call GitHub refuses."""


class GitHub:
    def __init__(self, home, *, login="acme"):
        self.home, self.file = home, home.root / "github.json"
        _save(self.file, {"login": login, "remotes": str(home.root / "remotes"), "prs": [],
                          "ids": 0})
        home.fake("gh", "#!/bin/sh\nexec " + shlex.join(
            [sys.executable, "-I", __file__, str(self.file), str(home.log("gh"))]) + ' "$@"\n')

    def prs(self):
        """Every PR, oldest first: gh's fields for it, its `repo`, its `head` as
        `<slug>:<branch>`, and once merged its `merge`: the `method`, the `commit` made, the
        `head` merged, the `match` and `body` it was given, and whether its branch was
        `deleted`."""
        return json.loads(self.file.read_text())["prs"]

    def pr(self, number, slug=None):
        return next(pr for pr in self.prs() if pr["number"] == number
                    and slug in (None, pr["repo"]))

    def open_pr(self, rig, head, *, base="main", title="Add contrib", body="", author=None):
        """Open a PR from a pushed branch of the rig, as `author` (the viewer unless given);
        its URL."""
        with _locked(self.file) as state:
            return _create(state, rig.slug, rig.slug, head, base, title, body, author)["url"]

    def edit(self, number, slug=None, **fields):
        """Set gh's fields on a PR: `state`, `isDraft`, `reviewDecision`,
        `mergeStateStatus`..."""
        slug = slug or self.pr(number)["repo"]
        with _locked(self.file) as state:
            _find(state, slug, str(number)).update(fields)


@contextmanager
def _locked(file):
    """The state, to one call at a time: a run and its lander may call gh at once."""
    global REMOTES
    with file.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(file.read_text())
        REMOTES = Path(state["remotes"])
        yield state
        _save(file, state)


def _save(file, state):
    file.with_suffix(".new").write_text(json.dumps(state, indent=1))
    file.with_suffix(".new").replace(file)


def _git(where, *args, check=True, env=None):
    # GitHub's git reads no one's configuration, the test's own included.
    clean = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    done = subprocess.run(["git", "-C", str(where), *args], capture_output=True, text=True,
                          env={**clean, "GIT_CONFIG_NOSYSTEM": "1",
                               "GIT_CONFIG_GLOBAL": os.devnull, **(env or {})})
    if check and done.returncode:
        raise Refused(f"git {' '.join(args)}: {done.stderr}")
    return done.stdout.strip() if done.returncode == 0 else None


def _bare(slug):
    return REMOTES / f"{slug}.git"


def _tip(slug, branch):
    return _git(_bare(slug), "rev-parse", "-q", "--verify", f"refs/heads/{branch}^{{commit}}",
                check=False)


def _repo(opts, cwd):
    """The repository a call names, else the one its checkout's origin is."""
    named = _one(opts, "--repo", "-R")
    if named:
        return named.removeprefix("https://github.com/").strip("/")
    origin = Path(_git(cwd, "remote", "get-url", "origin", check=False) or "/").resolve()
    if origin.parent.parent != REMOTES:
        raise Refused("none of the git remotes configured for this repository point to a "
                      "known GitHub host")
    return f"{origin.parent.name}/{origin.name.removesuffix('.git')}"


def _create(state, slug, head_slug, head, base, title, body, author=None):
    for pr in state["prs"]:
        if (pr["repo"], pr["head"], pr["baseRefName"], pr["state"]) == (
                slug, f"{head_slug}:{head}", base, "OPEN"):
            raise Refused(f'a pull request for branch "{head}" into branch "{base}" already '
                          f"exists:\n{pr['url']}")
    sha, base_sha = _tip(head_slug, head), _tip(slug, base)
    if not (sha and base_sha and _git(_bare(head_slug), "rev-list", f"{base_sha}..{sha}")):
        raise Refused(f"pull request create failed: GraphQL: No commits between {base} and "
                      f"{head} (createPullRequest)")
    number = 1 + max((pr["number"] for pr in state["prs"] if pr["repo"] == slug), default=0)
    pr = {"number": number, "url": f"https://github.com/{slug}/pull/{number}", "title": title,
          "body": body, "state": "OPEN", "isDraft": False, "baseRefName": base,
          "headRefName": head, "author": {"login": author or state["login"]},
          "headRepositoryOwner": {"login": head_slug.split("/")[0]}, "reviewDecision": "",
          "mergeCommit": None, "reviews": [], "comments": [], "repo": slug,
          "head": f"{head_slug}:{head}", "merge": None}
    state["prs"].append(pr)
    _head(pr)
    return pr


def _head(pr):
    """The PR's head: while open its branch's tip, kept in the pull ref as GitHub does; after,
    the commit it merged or closed on."""
    ref = f"refs/pull/{pr['number']}/head"
    if pr["state"] != "OPEN":
        return ((pr["merge"] or {}).get("head")
                or _git(_bare(pr["repo"]), "rev-parse", ref, check=False))
    head_slug, branch = pr["head"].split(":", 1)
    fetched = _git(_bare(pr["repo"]), "fetch", "-q", str(_bare(head_slug)),
                   f"+refs/heads/{branch}:{ref}", check=False)
    return None if fetched is None else _git(_bare(pr["repo"]), "rev-parse", ref)


def _find(state, slug, selector, cwd=None):
    """The PR a URL, a number or an open PR's branch names; the checkout's branch if none."""
    match = PULL.fullmatch(selector)
    slug, selector = (match[1], match[2]) if match else (slug, selector)
    selector = selector or _git(cwd, "branch", "--show-current", check=False) or ""
    number = selector.lstrip("#")
    for pr in reversed(state["prs"]):
        if pr["repo"] == slug and (str(pr["number"]) == number if number.isdigit() else
                                   (pr["headRefName"], pr["state"]) == (selector, "OPEN")):
            return pr
    raise Refused(f"GraphQL: Could not resolve to a PullRequest with the number of {number}."
                  if number.isdigit() else f'no pull requests found for branch "{selector}"')


def _merged_tree(slug, ours, theirs, base=None):
    """The tree merging `theirs` into `ours` makes, None on a conflict."""
    args = [*([f"--merge-base={base}"] if base else []), ours, theirs]
    tree = _git(_bare(slug), "merge-tree", "--write-tree", *args, check=False)
    return tree.split("\n")[0] if tree else None


def _graph(pr):
    """The PR as `gh pr view --json` names it; a field set on the PR wins."""
    sha, base_sha = _head(pr), _tip(pr["repo"], pr["baseRefName"])
    clean = bool(sha and base_sha and _merged_tree(pr["repo"], base_sha, sha))
    status = ("UNKNOWN" if pr["state"] != "OPEN" else "DRAFT" if pr["isDraft"] else
              "CLEAN" if clean else "DIRTY")
    return {"headRefOid": sha, "mergeable": "MERGEABLE" if clean else "CONFLICTING",
            "mergeStateStatus": status, "closed": pr["state"] != "OPEN",
            **{key: value for key, value in pr.items() if key not in ("repo", "head", "merge")}}


def _merge(state, pr, opts):
    method = next((m for m in ("squash", "merge", "rebase") if opts.get(f"--{m}")), None)
    if not method:
        raise Refused("--merge, --rebase, or --squash required when not running interactively")
    if pr["state"] != "OPEN":
        raise Refused(f"Pull request {pr['repo']}#{pr['number']} is {pr['state'].lower()}")
    sha, match = _head(pr), _one(opts, "--match-head-commit")
    if not sha or match and match != sha:
        raise Refused("GraphQL: Head branch was modified. Review and try the merge again. "
                      "(mergePullRequest)")
    if pr["isDraft"]:
        raise Refused("GraphQL: Pull Request is still a draft (mergePullRequest)")
    slug, base, login = pr["repo"], pr["baseRefName"], pr["author"]["login"]
    tip = base_sha = _tip(slug, base)
    who = {f"GIT_{part}_{key}": value for part in ("AUTHOR", "COMMITTER")
           for key, value in (("NAME", login), ("EMAIL", f"{login}@example.com"))}
    commits = _git(_bare(slug), "rev-list", "--reverse", f"{base_sha}..{sha}").split()
    body = _one(opts, "--body", "-b")
    for commit in commits if method == "rebase" else [sha]:
        tree = _merged_tree(slug, tip, commit, f"{commit}^" if method == "rebase" else None)
        if not tree:
            raise Refused("GraphQL: Pull Request is not mergeable (mergePullRequest)")
        message = _git(_bare(slug), "log", "-1", "--format=%B", commit)
        if method != "rebase":
            message = _one(opts, "--subject", "-t") or (
                f"{pr['title']} (#{pr['number']})" if method == "squash" else
                f"Merge pull request #{pr['number']} from {pr['head'].replace(':', '/')}")
            message += "\n\n" + (_default_body(pr, commits, method) if body is None else body)
        parents = [tip, commit] if method == "merge" else [tip]
        tip = _git(_bare(slug), "commit-tree", tree, *(f"-p{parent}" for parent in parents),
                   "-m", message, env=who)
    _git(_bare(slug), "update-ref", f"refs/heads/{base}", tip, base_sha)
    # gh deletes a head branch only in the PR's own repository, never in a fork
    deleted = bool(opts.get("--delete-branch")) and pr["head"].startswith(slug + ":")
    if deleted:
        _git(_bare(slug), "update-ref", "-d", f"refs/heads/{pr['headRefName']}")
    pr.update(state="MERGED", mergeCommit={"oid": tip}, merge={
        "method": method, "commit": tip, "head": sha, "match": match, "body": body,
        "deleted": deleted})


def _default_body(pr, commits, method):
    """The body GitHub gives a merge commit: the PR's title, or a squash's commit list."""
    if method == "merge":
        return pr["title"]
    return "\n".join(f"* {_git(_bare(pr['repo']), 'log', '-1', '--format=%s', commit)}"
                     for commit in commits)


def _answer(state, argv, cwd):
    """What gh prints for `argv`: (stdout, stderr)."""
    opts, pos = _parse(argv)
    verb = " ".join(pos[:2])
    if verb in ("pr create", "pr comment"):
        body, file = _one(opts, "--body", "-b"), _one(opts, "--body-file", "-F")
        body = Path(cwd, file).read_text() if body is None and file else body
    if verb == "pr create":
        slug, title = _repo(opts, cwd), _one(opts, "--title", "-t")
        owner, _, branch = (_one(opts, "--head", "-H") or
                            _git(cwd, "branch", "--show-current")).rpartition(":")
        if title is None or body is None:
            raise Refused("must provide `--title` and `--body` (or `--fill`) when not running "
                          "interactively")
        pr = _create(state, slug, f"{owner}/{slug.split('/')[1]}" if owner else slug, branch,
                     _one(opts, "--base", "-B") or "main", title, body)
        pr["isDraft"] = bool(opts.get("--draft"))
        return pr["url"] + "\n", ""
    if verb in ("pr view", "pr merge", "pr comment"):
        selector = pos[2] if len(pos) > 2 else ""
        pr = _find(state, None if PULL.fullmatch(selector) else _repo(opts, cwd), selector, cwd)
        if verb == "pr merge":
            _merge(state, pr, opts)
            return "", ""
        if verb == "pr comment":
            state["ids"] += 1
            pr["comments"].append({"id": state["ids"], "author": {"login": state["login"]},
                                   "body": body})
            return f"{pr['url']}#issuecomment-{state['ids']}\n", ""
        return _fields(_graph(pr), opts), ""
    if verb == "pr list":
        slug, want = _repo(opts, cwd), (_one(opts, "--state", "-s") or "open").upper()
        return _fields([_graph(pr) for pr in reversed(state["prs"]) if pr["repo"] == slug
                        and want in ("ALL", pr["state"])
                        and _one(opts, "--head", "-H") in (None, pr["headRefName"])
                        and _one(opts, "--base", "-B") in (None, pr["baseRefName"])
                        and _one(opts, "--author", "-A") in (None, pr["author"]["login"])],
                       opts), ""
    raise Refused(f"fake gh: unexpected {shlex.join(argv)}")


def _fields(data, opts):
    """The fields `--json` names of a record or of each in a list, then `-q` of that."""
    if not _one(opts, "--json"):
        raise Refused("fake gh: give --json")
    names, rows = _one(opts, "--json").split(","), data if isinstance(data, list) else [data]
    for name in names:
        if rows and name not in rows[0]:
            raise Refused(f'Unknown JSON field: "{name}"')
    picked = [{name: row[name] for name in names} for row in rows]
    return _jq(picked if isinstance(data, list) else picked[0], _one(opts, "-q", "--jq"))


def _jq(value, expression):
    for stage in (expression or ".").split("|"):
        stage = stage.strip()
        if stage == "tojson":
            value = json.dumps(value)
            continue
        for key in filter(None, stage.split(".")):
            value = value.get(key) if isinstance(value, dict) else None
    return (value if expression and isinstance(value, str) else json.dumps(value)) + "\n"


def _parse(argv):
    opts, pos, words = {}, [], iter(argv)
    for word in words:
        if word == "--":
            pos += list(words)
        elif word.startswith("-") and len(word) > 1:
            key, eq, value = word.partition("=") if word.startswith("--") else (word, "", "")
            if key in FLAGS:
                opts[key] = True
            else:
                opts.setdefault(key, []).append(value if eq else next(words, ""))
        else:
            pos.append(word)
    return opts, pos


def _one(opts, *names):
    """The last value given to any of these options, else None."""
    given = [value for name in names for value in opts.get(name, ())]
    return given[-1] if given else None


def main(file, log, *argv):
    with open(log, "a") as calls:
        calls.write(json.dumps(list(argv)) + "\n")
    out, err, code = "", "", 0
    with _locked(Path(file)) as state:
        try:
            out, err = _answer(state, list(argv), os.getcwd())
        except Refused as refused:
            err, code = f"{refused}\n", 1
    sys.stdout.write(out)
    sys.stderr.write(err)
    return code


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
