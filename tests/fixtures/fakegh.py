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

`repo view` gives the viewer ADMIN on its own repositories and READ on others unless `grant`
says, and `repo fork` makes its fork beside them.  `require` has a branch's ruleset require
checks, `check` adds a check run to a commit, and `pr merge` refuses a required check that
has not passed.  `auth status` and `api` answer too: user, graphql's protection and
merge-body queries, search/issues, and under repos/<slug>/: the open pulls, a PR as the REST
API has it and its reviews, branch rules, and a commit's check runs and statuses.  `reply`
scripts an answer ahead of all of it: LOGGED_OUT and OFFLINE are what gh says when it cannot
reach GitHub.

The state is `<root>/github.json`; every call is logged where `home.calls("gh")` reads it, and
with when it came where `asked` does.

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
import time

LOGGED_OUT = ("To get started with GitHub CLI, please run:  gh auth login\nAlternatively, "
              "populate the GH_TOKEN environment variable with a GitHub API authentication "
              "token.\n")
OFFLINE = ("error connecting to api.github.com\n"
           "check your internet connection or https://githubstatus.com\n")
FLAGS = {"--squash", "--merge", "--rebase", "--delete-branch", "--paginate", "--draft",
         "--remote", "--admin", "--auto", "--fill", "--include", "--silent", "--web"}
PULL = re.compile(r"https://github\.com/([^/]+/[^/]+)/pull/(\d+)/?")
REVIEWED = {"APPROVE": "APPROVED", "REQUEST_CHANGES": "CHANGES_REQUESTED",
            "COMMENT": "COMMENTED"}
REMOTES = None    # the Home's remotes, set as each call reads the state


class Refused(Exception):
    """What gh prints on stderr, exiting 1, for a call GitHub refuses."""


class GitHub:
    def __init__(self, home, *, login="acme"):
        self.home, self.file = home, home.root / "github.json"
        _save(self.file, {"login": login, "remotes": str(home.root / "remotes"), "prs": [],
                          "ids": 0, "access": {}, "replies": [], "checks": {}, "required": {}})
        home.fake("gh", "#!/bin/sh\nexec " + shlex.join(
            [sys.executable, "-I", __file__, str(self.file), str(home.log("gh"))]) + ' "$@"\n')

    def prs(self):
        """Every PR, oldest first: gh's fields for it, its `repo`, its `head` as
        `<slug>:<branch>`, and once merged its `merge`: the `method`, the `commit` made, the
        `head` merged, the `match` and `body` it was given, and whether its branch was
        `deleted`."""
        return json.loads(self.file.read_text())["prs"]

    def asked(self):
        """Each call, oldest first, as (when it came in epoch seconds, its argv)."""
        try:
            lines = self.file.with_suffix(".calls").read_text().splitlines()
        except FileNotFoundError:
            return []
        return [tuple(json.loads(line)) for line in lines]

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

    def check(self, sha, name, *, conclusion="success", status="completed",
              app="github-actions"):
        """A check run on a commit; a later one of the same name is the latest."""
        with _locked(self.file) as state:
            state["ids"] += 1
            state["checks"].setdefault(sha, []).append(
                {"id": state["ids"], "name": name, "status": status, "conclusion": conclusion,
                 "app": {"id": 1, "slug": app}, "head_sha": sha})

    def require(self, slug, branch, *names):
        """A ruleset on the branch: these checks pass before a merge."""
        with _locked(self.file) as state:
            state["required"][f"{slug}:{branch}"] = list(names)

    def grant(self, slug, permission):
        """The viewer's permission on a repository: READ, WRITE, MAINTAIN or ADMIN."""
        with _locked(self.file) as state:
            state["access"][slug] = permission

    def reply(self, prefix, out="", *, err="", code=0, times=None):
        """Answer the calls whose space-joined argv starts with `prefix` so, `times` times or
        for good, ahead of everything else; "" is every call."""
        with _locked(self.file) as state:
            state["replies"].append({"prefix": prefix, "out": out, "err": err, "code": code,
                                     "times": times})

    def restore(self):
        """Forget every `reply`: GitHub answers for itself again."""
        with _locked(self.file) as state:
            state["replies"] = []


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


def _rest(pr):
    """The PR as GitHub's REST API has it, each side's `clone_url` its bare origin."""
    graph = _graph(pr)
    sides = {"head": (pr["head"].split(":")[0], pr["headRefName"], graph["headRefOid"]),
             "base": (pr["repo"], pr["baseRefName"], _tip(pr["repo"], pr["baseRefName"]))}
    return {"number": pr["number"], "html_url": pr["url"], "title": pr["title"],
            "body": pr["body"], "state": "open" if pr["state"] == "OPEN" else "closed",
            "merged": pr["state"] == "MERGED", "draft": pr["isDraft"], "user": pr["author"],
            "mergeable": graph["mergeable"] == "MERGEABLE" if pr["state"] == "OPEN" else None,
            "merge_commit_sha": (pr["mergeCommit"] or {}).get("oid"),
            **{side: {"ref": ref, "sha": sha,
                      "repo": {"full_name": slug, "clone_url": str(_bare(slug))}}
               for side, (slug, ref, sha) in sides.items()}}


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
    for name in state["required"].get(f"{pr['repo']}:{pr['baseRefName']}", []):
        runs = [run for run in state["checks"].get(sha, []) if run["name"] == name]
        if not runs or runs[-1]["conclusion"] not in ("success", "neutral", "skipped"):
            raise Refused(f'GraphQL: Required status check "{name}" is expected. '
                          "(mergePullRequest)")
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


def _api(state, opts, endpoint):
    fields = {}
    for flag in ("-f", "--raw-field", "-F", "--field"):
        for pair in opts.get(flag, ()):
            key, _, value = pair.partition("=")
            typed = flag in ("-F", "--field") and value.startswith("@")
            fields[key] = Path(value[1:]).read_text() if typed else value
    method = _one(opts, "-X", "--method") or ("POST" if fields else "GET")
    path, _, query = endpoint.partition("?")
    asked = fields.get("query", "")
    if path == "user":
        return {"login": state["login"]}
    if path == "graphql" and "viewerMergeBodyText" in asked:
        pr = _find(state, f"{fields['owner']}/{fields['name']}", fields["number"])
        commits = _git(_bare(pr["repo"]), "rev-list", "--reverse",
                       f"{_tip(pr['repo'], pr['baseRefName'])}..{_head(pr)}").split()
        text = _default_body(pr, commits, fields.get("method", "SQUASH").lower())
        return {"data": {"repository": {"pullRequest": {"viewerMergeBodyText": text}}}}
    if path == "graphql" and "branchProtectionRule" in asked:
        return {"data": {"repository": {"ref": {"branchProtectionRule": None}}}}
    if path == "search/issues":
        found = [pr for pr in state["prs"] if pr["state"] == "OPEN"
                 and ("author:@me" not in query or pr["author"]["login"] == state["login"])]
        return {"total_count": len(found), "incomplete_results": False, "items": [
            {"number": pr["number"], "title": pr["title"], "state": "open", "user": pr["author"],
             "html_url": pr["url"], "pull_request": {"html_url": pr["url"]}} for pr in found]}
    parts = path.split("/", 3)
    slug, rest = ("/".join(parts[1:3]), parts[3]) if len(parts) == 4 else ("", "")
    if parts[0] != "repos":
        rest = ""
    if rest == "pulls":
        return [_rest(pr) for pr in state["prs"] if (pr["repo"], pr["state"]) == (slug, "OPEN")]
    if (pull := re.fullmatch(r"pulls/(\d+)(/reviews)?", rest)):
        pr = _find(state, slug, pull[1])
        if not pull[2]:
            pr.update({key: fields[key] for key in ("title", "body") if key in fields})
            return _rest(pr)
        if method == "POST":
            state["ids"] += 1
            pr["reviews"].append({"id": state["ids"], "author": {"login": state["login"]},
                                  "state": REVIEWED.get(fields.get("event"), "PENDING"),
                                  "body": fields.get("body", ""),
                                  "commit": {"oid": fields.get("commit_id") or _head(pr)}})
        return [{"id": review["id"], "user": review["author"], "state": review["state"],
                 "body": review["body"], "commit_id": review["commit"]["oid"]}
                for review in pr["reviews"]]
    if rest.startswith("rules/branches/"):
        names = state["required"].get(f"{slug}:{rest.removeprefix('rules/branches/')}")
        return [{"type": "required_status_checks", "parameters": {"required_status_checks": [
            {"context": name} for name in names]}}] if names else []
    if (commit := re.fullmatch(r"commits/([^/]+)/(check-runs|statuses)", rest)):
        runs = state["checks"].get(commit[1], [])
        return {"total_count": len(runs), "check_runs": runs} if commit[2] == "check-runs" else []
    raise Refused("gh: Not Found (HTTP 404)")


def _answer(state, argv, cwd):
    """What gh prints for `argv`: (stdout, stderr)."""
    opts, pos = _parse(argv)
    verb = " ".join(pos[:2])
    if verb == "auth status":
        return "", f"github.com\n  ✓ Logged in to github.com account {state['login']}\n"
    if pos[:1] == ["api"]:
        return _jq(_api(state, opts, pos[1]), _one(opts, "-q", "--jq")), ""
    if verb == "repo view":
        slug = pos[2] if len(pos) > 2 else _repo(opts, cwd)
        if not _bare(slug).is_dir():
            raise Refused(f"GraphQL: Could not resolve to a Repository with the name '{slug}'.")
        owner = slug.split("/")[0]
        mine = "ADMIN" if owner == state["login"] else "READ"
        return _fields({"nameWithOwner": slug, "owner": {"login": owner}, "isFork": False,
                        "url": f"https://github.com/{slug}", "defaultBranchRef": {"name": "main"},
                        "viewerPermission": state["access"].get(slug, mine)}, opts), ""
    if verb == "repo fork":
        slug = _repo(opts, cwd)
        fork = _bare(f"{state['login']}/{slug.split('/')[1]}")
        if not fork.is_dir():
            _git(cwd, "clone", "-q", "--bare", str(_bare(slug)), str(fork))
        if opts.get("--remote"):
            _git(cwd, "remote", "add", _one(opts, "--remote-name") or "origin", str(fork))
        return "", ""
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
    with Path(file).with_suffix(".calls").open("a") as calls:
        calls.write(json.dumps([time.time(), list(argv)]) + "\n")
    out, err, code = "", "", 0
    with _locked(Path(file)) as state:
        for reply in state["replies"]:
            if " ".join(argv).startswith(reply["prefix"]) and reply["times"] != 0:
                reply["times"] = None if reply["times"] is None else reply["times"] - 1
                out, err, code = reply["out"], reply["err"], reply["code"]
                break
        else:
            try:
                out, err = _answer(state, list(argv), os.getcwd())
            except Refused as refused:
                err, code = f"{refused}\n", 1
    sys.stdout.write(out)
    sys.stderr.write(err)
    return code


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
