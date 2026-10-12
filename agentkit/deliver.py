"""A run's delivery: the pull request.

The push of its branch and the pull request that opens on it (its body and the
suite trailer it carries, its checks and their wait, the rights a fork needs),
the gh calls that read GitHub's answers, and what may merge without a review:
a diff of wording alone.
"""

import json
import os
import re
import time
from pathlib import Path
from urllib.parse import quote, urlsplit

from . import config, gitcall, prompts, roundloop, transitions, turns


GITHUB_BODY_CAP = 60_000         # below GitHub's 65,536-character body limit, including UTF-8


CHECKS_CAP = 60 * 60            # a check suite still running after an hour is not going to finish
CHECKS_POLL = 10
PR_URL = re.compile(r"https://\S+?/pull/\d+")


PUSH_RIGHTS = ("ADMIN", "MAINTAIN", "WRITE")
FORK_REMOTE = "fork"            # the remote a run adds for its fork; `origin` stays the upstream
CLASSIC_CHECKS_QUERY = (
    "query($owner:String!,$name:String!,$branch:String!){repository(owner:$owner,name:$name){"
    "ref(qualifiedName:$branch){branchProtectionRule{requiresStatusChecks "
    "requiredStatusChecks{context app{databaseId}}}}}}")


def push(lp):
    require_review_pass(lp)
    branch = lp.state["branch"]
    head = gitcall.git(lp.wt, "rev-parse", "HEAD", check=False)
    if lp.state.get("merge_method") == "rebase":
        # Rebase merges preserve the branch's messages, ignoring a merge commit body.
        # Change only the message: staged or untracked files cannot become checked code.
        old = gitcall.git(lp.wt, "show", "-s", "--format=%B", head)
        message = re.sub(r"(?m)^Suite-Passed-Tree:.*\n?", "", old).rstrip()
        body = merge_body(lp, head)
        if body:
            message = add_suite_trailer(lp, message, body[-1])
        if message != old.rstrip():
            gitcall.git(lp.wt, "-c", f"core.hooksPath={os.devnull}", "commit", "--amend", "--only",
                "-m", message)
            head = gitcall.git(lp.wt, "rev-parse", "HEAD")
            lp.state["review"]["head_sha"] = head
            if body:
                lp.state["final_check"]["sha"] = head
            lp.write()
    # origin as integrate's pruning fetch saw it: a name another run pushed before that fetch
    # is refused here, unless it holds a commit this run pushed -- or set out to, since origin
    # may take a push that stops before it is recorded, and the retry may have rebased since
    seen = gitcall.git(lp.wt, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}",
               check=False)
    ours = lp.state.setdefault("pushed", [])
    if seen and seen not in (lp.state.get("delivery_sha"), *ours):
        return roundloop.note(lp, f"origin already has {branch} at {seen[:12]} and this run did not push "
                        "it; the branch was taken by another run", failed=True)
    ours.append(head)
    lp.write()
    # --force-with-lease from the start: a rebased branch is a rewrite, and a resumed or
    # retried run finds its own earlier push already on origin.  Pinned to what was seen, so
    # a fetch in another worktree since cannot move the lease onto another run's commit
    rc, out = gitcall.git_out(lp.wt, "push", f"--force-with-lease={branch}:{seen}", "-u", "origin", branch)
    if rc != 0:
        # a name this run never pushed, already on origin: another run took it while this one
        # worked, and the lease git refuses to break is the only thing that says so
        if re.search(r"stale info|rejected", out, re.I):
            return roundloop.note(lp, f"origin already has {branch} and this run did not push it; the "
                            f"branch was taken by another run: {out[-400:]}", failed=True)
        return roundloop.note(lp, f"pushing {branch} to origin failed: {out[-400:]}", failed=True)
    lp.log(f"--- merge: pushed {branch} to origin")
    lp.state["delivery_sha"] = head
    lp.write()
    return True


def github_body(text, run_id):
    """Keep publication within GitHub's limit; the run retains the complete records."""
    data = text.encode("utf-8")
    if len(data) <= GITHUB_BODY_CAP:
        return text
    note = f"\n\n[body truncated; complete findings and summaries are in agentkit run {run_id}]\n"
    return data[:GITHUB_BODY_CAP - len(note.encode("utf-8"))].decode("utf-8", "ignore") + note


def pr_body(state):
    last = state["round_summaries"][-1]["summary"].strip() if state["round_summaries"] else ""
    lines = [last, "", "---", "",
             f"- verdict: {state['verdict']}",
             f"- rounds: {len(state['round_summaries'])} of {state['rounds']}",
             f"- executor: {state['executor']}, reviewer: {state['reviewer']}",
             f"- run: {state['run_id']}"]
    if prompts.base_proof_line(state):
        lines.append(f"- {prompts.base_proof_line(state)}")
    if state.get("followups"):
        lines += ["", "## Follow-ups", "",
                  *("- " + item.replace("\n", "\n  ") for item in state["followups"])]
    if state.get("notes"):
        lines += ["", "## Notes", "",
                  *("- " + item.replace("\n", "\n  ") for item in state["notes"])]
    return github_body("\n".join(lines + [""]), state["run_id"])


def refresh_pr_body(lp):
    """A later passing review replaces the list on the already-open PR too."""
    path = lp.run_dir / "pr-body.md"
    body = pr_body(lp.state)
    if path.is_file() and path.read_text() == body:
        return True
    pending = lp.run_dir / "pr-body-update.md"
    pending.write_text(body)
    # through the REST API: `gh pr edit` asks GraphQL for Projects (classic) too, and since
    # GitHub retired them some gh releases (2.46) fail that ask and change nothing
    parts = pr_parts(lp.state["pr"])
    if parts is None:
        return roundloop.note(lp, f"cannot update the description of {lp.state['pr']}: not a PR URL",
                    failed=True)
    api, owner, repo, number = parts
    rc, out = gitcall.gh(lp.wt, *api, "-X", "PATCH", f"repos/{owner}/{repo}/pulls/{number}",
                 "-F", f"body=@{pending}")
    if rc != 0:
        if gitcall.stopped(rc, out):
            raise gitcall.Stopped(out)
        return roundloop.note(lp, f"updating the PR description failed: {out[-400:]}", failed=True)
    pending.replace(path)      # only a confirmed update may be skipped on a delivery retry
    return True


def open_pr(lp, target_branch):
    """The PR's URL, opening it first unless this branch already has one."""
    if lp.state.get("pr"):
        return lp.state["pr"] if refresh_pr_body(lp) else None
    path = lp.run_dir / "pr-body.md"
    path.write_text(pr_body(lp.state))
    rc, out = gitcall.gh(lp.wt, "pr", "create", "--base", target_branch, "--head", lp.state["branch"],
                 "--title", lp.state["title"], "--body-file", str(path))
    # gh names the existing PR in the error it refuses a duplicate with, so one regex covers both
    found = PR_URL.search(out)
    view = None
    if not found:
        # the create may still have happened server-side: the view says so, or stops too
        vrc, view = gitcall.gh(lp.wt, "pr", "view", lp.state["branch"], "--json", "url", "-q", ".url")
        found = None if gitcall.stopped(vrc, view) else PR_URL.search(view)
    if not found:
        if gitcall.stopped(rc, out) or (view is not None and gitcall.stopped(vrc, view)):
            raise gitcall.Stopped(out if gitcall.stopped(rc, out) else view)
        roundloop.note(lp, f"gh pr create failed: {out[-400:]}", failed=True)
        return None
    lp.state["pr"] = found.group(0)
    lp.write()
    lp.log(f"--- merge: PR {lp.state['pr']}" + (" (already open)" if rc != 0 else ""))
    return lp.state["pr"]


def poll_cap(deadline):
    """One poll of the checks wait: capped like any other call, never shrunk to fit the hour.

    Shrinking the last poll below a real round trip manufactures a stop out of a healthy gh:
    the loop sleeps to exactly the deadline before re-polling, so a clamped budget always
    expires on a `gh` that was still answering, and the deadline branch below -- which names
    the checks that never finished -- never runs.  The hour cap is enforced by that post-poll
    deadline test instead.
    """
    return gitcall.TOOL_CAP


def pr_parts(url):
    """(`gh api` and the host it needs, owner, repository, number) of the PR at `url`, or None
    for a URL that is not one PR on an https host."""
    pr = urlsplit(url)
    match = re.fullmatch(r"/([^/\s]+)/([^/\s]+)/pull/(\d+)/?", pr.path)
    if not match or pr.scheme != "https" or not pr.hostname or pr.username or pr.query or pr.fragment:
        return None
    api = ("api",) if pr.netloc == "github.com" else ("api", "--hostname", pr.netloc)
    return (api, *match.groups())


def checks(lp, url):
    """Wait for the target's required names, including checks that have not registered yet."""
    parts = pr_parts(url)
    if parts is None:
        return False, f"cannot read required checks for {url}"
    api, owner, repo, _ = parts
    target = lp.target.removeprefix("origin/")
    endpoint = f"repos/{owner}/{repo}/rules/branches/{quote(target, safe='')}"
    rules, why = gh_json(lp.run_dir, *api, "--paginate", endpoint + "?per_page=100")
    required = {}
    try:
        if not isinstance(rules, list) or any(not isinstance(page, list) for page in rules):
            raise ValueError(why or "invalid branch rules response")
        for page in rules:
            for rule in page:
                if rule["type"] == "required_status_checks":
                    for check in rule["parameters"]["required_status_checks"]:
                        name = check["context"]
                        if not isinstance(name, str) or not name:
                            raise ValueError("required check has no name")
                        required.setdefault(name, set()).add(check.get("integration_id") or None)
    except (KeyError, TypeError, ValueError) as exc:
        return False, f"cannot read required checks for {target}: {exc}"
    # Branch rules cover rulesets only. Read the matching classic protection rule through
    # GraphQL, which does not require the REST protection endpoint's administration access.
    classic, why = gh_json(lp.run_dir, *api, "graphql", "-f", f"query={CLASSIC_CHECKS_QUERY}",
                           "-f", f"owner={owner}", "-f", f"name={repo}",
                           "-f", f"branch=refs/heads/{target}")
    try:
        if not isinstance(classic, dict) or classic.get("errors"):
            raise ValueError(why or "invalid classic protection response")
        protection = classic["data"]["repository"]["ref"]["branchProtectionRule"]
        if protection is not None and protection["requiresStatusChecks"]:
            for check in protection["requiredStatusChecks"]:
                name = check["context"]
                if not isinstance(name, str) or not name:
                    raise ValueError("required check has no name")
                app = check["app"]
                required.setdefault(name, set()).add(app["databaseId"] if app else None)
    except (KeyError, TypeError, ValueError) as exc:
        return False, f"cannot read classic required checks for {target}: {exc}"
    if not required:
        lp.log(f"checks: {target} requires no status checks")
        return True, ""
    lp.log(f"--- checks: {target} requires {', '.join(sorted(required))}")
    head = lp.state.get("delivery_sha") or lp.state.get("head_sha")
    if not head:
        return False, "cannot verify required checks without the PR head SHA"
    deadline = time.monotonic() + CHECKS_CAP
    rerun = {}      # a check GitHub cancelled ran nothing: asked again until GitHub takes it
    while True:
        # The server's gh supports REST pagination but not `pr checks --json`. Read the
        # recorded commit directly, including all check-run and legacy status pages.
        data, why = gh_json(lp.run_dir, *api, "--paginate",
                            f"repos/{owner}/{repo}/commits/{head}/check-runs?filter=latest&per_page=100",
                            timeout=poll_cap(deadline))
        try:
            if not isinstance(data, list):
                raise ValueError(why or "invalid check-runs response")
            runs = [check for page in data for check in page["check_runs"]]
            latest = {}
            for check in runs:
                key = (check["name"], check["app"]["id"])
                if key not in latest or check["id"] > latest[key]["id"]:
                    latest[key] = check
            states, missing_apps = {}, set()
            for name, apps in required.items():
                matches = [check for (context, app), check in latest.items()
                           if context == name and (None in apps or app in apps)]
                states[name] = ["pending" if check["status"] != "completed" else
                                "pass" if check["conclusion"] in ("success", "neutral", "skipped")
                                else "pending" if check["conclusion"] == "cancelled"
                                else "fail" for check in matches]
                for check in matches:
                    if (check["conclusion"] == "cancelled" and rerun.get(check["id"]) != 0
                            and check["app"].get("slug") == "github-actions"):
                        # GitHub refuses a job's rerun while its workflow still runs: next poll
                        rc, out = gitcall.gh(lp.run_dir, *api, "-X", "POST",
                                     f"repos/{owner}/{repo}/actions/jobs/{check['id']}/rerun")
                        if gitcall.stopped(rc, out):
                            raise gitcall.Stopped(out)
                        if rc == 0 or check["id"] not in rerun:
                            lp.log(f"checks: GitHub cancelled {name}; asked it to run again"
                                   + ("" if rc == 0 else f", refused for now: {out.strip()[-200:]}"))
                        rerun[check["id"]] = rc
                if not (apps - {None}).issubset({check["app"]["id"] for check in matches}):
                    missing_apps.add(name)
                    states[name] = []  # a same-named check from another app cannot satisfy it
        except (KeyError, TypeError, ValueError) as exc:
            return False, f"cannot read required check runs: {exc}"
        latest_status = {}
        if any(None in apps for apps in required.values()):
            data, why = gh_json(lp.run_dir, *api, "--paginate",
                                f"repos/{owner}/{repo}/commits/{head}/statuses?per_page=100",
                                timeout=poll_cap(deadline))
            try:
                if not isinstance(data, list) or any(not isinstance(page, list) for page in data):
                    raise ValueError(why or "invalid statuses response")
                latest_status = {}
                for page in data:
                    for status in page:
                        name = status["context"]
                        if name not in latest_status or status["id"] > latest_status[name]["id"]:
                            latest_status[name] = status
                for name, status in latest_status.items():
                    if name in required and None in required[name] and name not in missing_apps:
                        states[name].append("pass" if status["state"] == "success" else
                                            "fail" if status["state"] in ("failure", "error") else "pending")
            except (KeyError, TypeError, ValueError) as exc:
                return False, f"cannot read required commit statuses: {exc}"
        failed = sorted(name for name, buckets in states.items()
                        if "fail" in buckets)
        if failed:
            why = f"required checks failed: {', '.join(failed)}"
            if (lp.state.get("waiting_on") or {}).get("line"):
                # Keep the check's output and details URL for the landing fixer.
                why += "\n\n" + json.dumps({
                    "check_runs": [check for check in latest.values() if check["name"] in failed],
                    "statuses": [status for name, status in latest_status.items() if name in failed]},
                    indent=2)
            return False, why
        missing = sorted(name for name, buckets in states.items() if not buckets)
        pending = sorted(name for name, buckets in states.items()
                         if any(bucket not in ("pass", "skipping") for bucket in buckets))
        if not missing and not pending:
            lp.log("checks: required checks green")
            return True, ""
        if time.monotonic() >= deadline:
            reasons = []
            if missing:
                reasons.append(f"required checks never registered: {', '.join(missing)}")
            if pending:
                reasons.append(f"required checks did not finish: {', '.join(pending)}")
            return False, "; ".join(reasons)
        time.sleep(min(CHECKS_POLL, max(0, deadline - time.monotonic())))


def wait_checks(lp, url):
    """Sit on the PR's checks until they are green.  False leaves the PR open, and says why."""
    green, why = checks(lp, url)
    if green:
        return True
    wait = lp.state.get("waiting_on") or {}
    if wait.get("line") and why.startswith("required checks failed:"):
        path = lp.run_dir / "pr-checks.log"
        path.write_text(f"{why}\nPR: {url}\n")
        lp.state["waiting_on"] = {**wait, "fix": {"line": why.splitlines()[0], "log": str(path)}}
        lp.write()
        return False
    return roundloop.note(lp, f"{why}; the PR is open at {url}", failed=True)


def rights(lp):
    """(upstream repo, this account's permission on it), or (None, None) when gh cannot say.

    A gh that ran out of time, or that was refused the login prompt it wanted, said nothing at
    all -- which is not the same as saying it does not know.  Pushing on the strength of it
    would deliver on an assumption, so that ends the delivery with its remedy instead.
    """
    rc, out = gitcall.gh(lp.wt, "repo", "view", "--json", "nameWithOwner,viewerPermission")
    if gitcall.stopped(rc, out):
        raise gitcall.Stopped(out)
    try:
        data = json.loads(out) if rc == 0 else {}
    except ValueError:
        data = {}
    if not isinstance(data, dict) or not data.get("nameWithOwner"):
        lp.log(f"WARN gh repo view could not say whether this account may push: {out[-200:]}")
        return None, None
    return data["nameWithOwner"], data.get("viewerPermission")


def fork_and_pr(lp, target_branch, upstream_repo, permission):
    """No push rights on origin: push the branch to a fork and open the PR upstream from there.

    The run ends `waiting for the maintainer` -- a PASS, not merged, and not a failure: merging
    is somebody else's decision now, and `ak watch` follows what they decide.
    """
    require_review_pass(lp)
    branch = lp.state["branch"]
    lp.log(f"--- merge: {permission or 'no'} permission on {upstream_repo}; pushing to a fork")
    if FORK_REMOTE not in gitcall.git(lp.wt, "remote", check=False).split():
        # --remote-name keeps `origin` pointing upstream, which is what the diff and the PR are
        # against; an existing fork is reused, gh only adds the remote for it
        rc, out = gitcall.gh(lp.wt, "repo", "fork", "--remote", "--remote-name", FORK_REMOTE)
        if rc != 0:
            if gitcall.stopped(rc, out):
                raise gitcall.Stopped(out)
            return roundloop.note(lp, f"gh repo fork failed: {out[-400:]}", failed=True)
    rc, out = gitcall.git_out(lp.wt, "push", "--force-with-lease", "-u", FORK_REMOTE, branch)
    if rc != 0:
        return roundloop.note(lp, f"pushing {branch} to the fork failed: {out[-400:]}", failed=True)
    lp.log(f"--- merge: pushed {branch} to {FORK_REMOTE}")
    if not lp.state.get("pr"):
        rc, me = gitcall.gh(lp.run_dir, "api", "user", "-q", ".login")
        # classify before reducing to the last line: the remedy tool_run appends is the last
        # line, and it matches none of PROMPTED's patterns, so a refused prompt checked after
        # the reduction would never read as the stop it is
        if gitcall.stopped(rc, me):
            raise gitcall.Stopped(me)
        me = me.strip().splitlines()[-1] if me.strip() else ""
        if rc != 0 or not me:
            return roundloop.note(lp, f"gh api user could not say whose fork this is: {me[-200:]}",
                        failed=True)
        path = lp.run_dir / "pr-body.md"
        path.write_text(pr_body(lp.state))
        rc, out = gitcall.gh(lp.wt, "pr", "create", "--repo", upstream_repo, "--base", target_branch,
                     "--head", f"{me}:{branch}", "--title", lp.state["title"],
                     "--body-file", str(path))
        found = PR_URL.search(out)
        if not found:
            if gitcall.stopped(rc, out):
                raise gitcall.Stopped(out)
            return roundloop.note(lp, f"gh pr create on {upstream_repo} failed: {out[-400:]}", failed=True)
        lp.state["pr"] = found.group(0)
        lp.log(f"--- merge: PR {lp.state['pr']}" + (" (already open)" if rc != 0 else ""))
    elif not refresh_pr_body(lp):
        return False
    lp.state["foreign"] = True
    return roundloop.note(lp, "waiting for the maintainer")


def add_suite_trailer(lp, message, trailer):
    # Keep existing attribution in the trailer block Git and GitHub recognize.
    path = lp.run_dir / "merge-body.txt"
    path.write_text(message)
    return gitcall.git(lp.wt, "interpret-trailers", "--no-divider", "--where", "end",
               "--if-exists", "replace", "--trailer", trailer, str(path))


def merge_body(lp, head, url=None):
    checked = lp.state.get("final_check") or {}
    suite = gitcall.declared_suite(lp.wt, lp.target, ref=lp.state.get("target_sha"))
    if (suite and checked.get("suite") == suite and checked.get("outcome") == "passed"
            and checked.get("sha") == head and checked.get("tree_sha")
            and checked.get("tested", checked["tree_sha"]) == checked["tree_sha"]
            and checked["tree_sha"] == gitcall.git(lp.wt, "rev-parse", f"{head}^{{tree}}")):
        body = f"Suite-Passed-Tree: {checked['tree_sha']}"
        if url:
            # An explicit body replaces GitHub's defaults, including co-author credit.
            parts = pr_parts(url)
            if parts is None:
                lp.log(f"WARN cannot read the merge commit body for {url}; merging without suite trailer")
                return []
            api, owner, name, number = parts
            try:
                default, why = gh_json(
                    lp.run_dir, *api, "graphql", "-f",
                    "query=query($owner:String!,$name:String!,$number:Int!,$method:PullRequestMergeMethod!){"
                    "repository(owner:$owner,name:$name){pullRequest(number:$number){"
                    "viewerMergeBodyText(mergeType:$method)}}}",
                    "-f", f"owner={owner}", "-f", f"name={name}", "-F", f"number={number}",
                    "-f", f"method={(lp.state.get('merge_method') or 'squash').upper()}",
                    "-q", ".data.repository.pullRequest.viewerMergeBodyText | tojson")
            except gitcall.Stopped as exc:
                # Only the CI shortcut needs this read; the reviewed head stays pinned.
                default, why = None, str(exc)
            if not isinstance(default, str):
                lp.log(f"WARN could not read the merge commit body for {url}: "
                       f"{why or 'GitHub returned no body text'}; merging without suite trailer")
                return []
            body = add_suite_trailer(lp, default, body)
        return ["--body", body]
    return []


def require_review_pass(lp):
    if not transitions.review_pass(lp.state, lp.cfg):
        raise turns.Exhausted("delivery requires a successful reviewer allowed by the model policy; "
                        "resume the run to obtain review")
    if not roundloop.current_review(lp):
        raise turns.Exhausted("delivery requires done-when and review of the current commit; "
                        "resume the run to obtain review")


def gh_json(cwd, *args, timeout=None):
    """The parsed JSON a gh command prints, or None with the reason why not.

    A stop is never an empty answer: a timeout, or a prompt it was refused, raises Stopped,
    so no caller can deliver on the strength of a gh that said nothing at all.
    """
    rc, out = gitcall.gh(cwd, *args, timeout=timeout)
    if gitcall.stopped(rc, out):
        raise gitcall.Stopped(out)
    if rc != 0:
        return None, out[:400] or "gh timed out"
    try:
        return (config.json_pages(out) if "--paginate" in args else json.loads(out)), ""
    except ValueError as exc:
        return None, f"gh printed no JSON ({exc}): {out[-200:]}"


def text_only_pr(repo, base, head):
    """Does every change between `base` and `head` touch only a prose or translation file?

    Both sides of a rename count: moving code into a prose filename still needs review.
    AGENTS.md is executable configuration: its front matter supplies shell commands.  Only a
    regular file counts: a submodule's commit or a link names code elsewhere, and a local
    `diff.ignoreSubmodules` hides nothing here.  A file is binary when its committed bytes hold
    a NUL, whatever `.gitattributes` tells the diff.  Names are read byte for byte, so each is
    looked up as the file it is, never a lookalike.  An AGENTS.md at any depth that is a link
    makes its target executable configuration too, so then nothing skips review.
    """
    raw = ("--no-renames", "--no-ext-diff", "--no-textconv", "--ignore-submodules=none", "-z")
    try:
        trees = [gitcall.git_bytes(repo, "ls-tree", "-r", "-z", ref) for ref in (base, head)]
        if any(meta.split(" ", 1)[0] not in ("100644", "100755")
               for tree in trees for meta, _, name in (entry.partition("\t")
                                                       for entry in tree.split("\0") if entry)
               if Path(name).name.upper() == "AGENTS.MD"):
            return False        # an AGENTS.md anywhere that is a link or a submodule
        entries = gitcall.git_bytes(repo, "diff", "--raw", *raw, base, head, "--").split("\0")
        modes = [entry.split()[:2] for entry in entries[0::2] if entry.startswith(":")]
        entries = gitcall.git_bytes(repo, "diff", "--numstat", *raw, base, head, "--").split("\0")
    except (config.Error, gitcall.Stopped):
        return False        # a diff nobody could read cannot be shown to be wording
    files = [entry.split("\t", 2) for entry in entries if entry]
    extensions = {".md", ".markdown", ".rst", ".adoc", ".po", ".pot", ".xlf", ".xliff",
                  ".strings", ".stringsdict", ".srt", ".vtt"}
    names = {"README", "LICENSE", "COPYING", "NOTICE", "AUTHORS", "CHANGELOG"}
    return (bool(files) and len(modes) == len(files)
            and all(mode.lstrip(":") in ("000000", "100644", "100755")
                    for pair in modes for mode in pair)
            and all(len(row) == 3 and row[0].isdigit() and row[1].isdigit()
                    and Path(row[2]).name.upper() != "AGENTS.MD"
                    and (Path(row[2]).suffix.lower() in extensions
                         or Path(row[2]).name.upper() in names
                         or Path(row[2]).suffix.lower() in (".txt", ".text")
                         and Path(row[2]).stem.upper() in names) for row in files)
            and all(text_blob(repo, ref, row[2]) for pair, row in zip(modes, files)
                    for mode, ref in zip(pair, (base, head)) if mode.lstrip(":") != "000000"))


def text_blob(repo, ref, path):
    """Do the bytes `path` names at `ref` read back, with no NUL among them?"""
    try:
        return "\0" not in gitcall.git_bytes(repo, "cat-file", "blob", f"{ref}:{path}")
    except (config.Error, gitcall.Stopped):
        return False
