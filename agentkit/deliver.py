"""A run's delivery.

The push of its branch and the pull request that opens on it (its body, its
checks and their wait, the rights a fork needs), the gh calls that read GitHub's
answers, the merge and what it may merge (a diff of wording alone needs no
review), the landing line a run joins, releases and rejoins, the landing itself
under the repository's lock, and the endings a delivery can have: blocked, on a
dependency, or a landing that failed and goes back to the writer.
"""

import fcntl
import hashlib
import json
import os
import re
import shutil
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote, urlsplit

from . import (config, gitcall, handback, history, land as landing, prompts, record as run_record,
               roundloop, transitions, turns)


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
    rc, out = git_push(lp, f"--force-with-lease={branch}:{seen}", "-u", "origin", branch)
    if rc != 0:
        # a name this run never pushed, already on origin: another run took it while this one
        # worked, and the lease git refuses to break is the only thing that says so
        if re.search(r"stale info", out, re.I):
            return roundloop.note(lp, f"origin already has {branch} and this run did not push it; the "
                            f"branch was taken by another run: {out[-400:]}", failed=True)
        return roundloop.note(lp, f"pushing {branch} to origin failed: {out[-400:]}", failed=True)
    lp.log(f"--- merge: pushed {branch} to origin")
    lp.state["delivery_sha"] = head
    lp.write()
    return True


def git_push(lp, *args):
    """`git push` with `args`, as `gitcall.git_out` answers it, GitHub refusing it for a reason
    of its own waited out and tried again up to GITHUB_RETRIES times: the same push over the
    same lease, so a retry can never replace what anyone pushed meanwhile."""
    for tried in range(1, GITHUB_RETRIES + 1):
        rc, out = gitcall.git_out(lp.wt, "push", *args)
        refused = REMOTE_REJECTED.search(out) if rc else None
        if not refused:
            return rc, out
        delay = turns.transient_delay(tried)
        lp.log(f"WARN GitHub refused the push: {refused[0].strip()}; pushing again over the same "
               f"lease in {delay}s ({tried}/{GITHUB_RETRIES})")
        step = history.close_step(lp.state.get("run_id"), log=lp.log)   # a wait, not work
        time.sleep(delay)
        history.open_step(lp.state.get("run_id"), step, log=lp.log)
    return gitcall.git_out(lp.wt, "push", *args)


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
    """Does every change between `base` and `head` touch only a document people read?

    A document is a README, CHANGELOG, LICENSE, ARCHITECTURE or the like, at any depth, or
    prose under the top-level `docs/`.  Markdown elsewhere may be what a product or a model
    reads (a support assistant's knowledge, a rulebook) and translations are the product's
    own words, so they are reviewed.  Both sides of a rename count: moving code into a
    document's name still needs review.  AGENTS.md is executable configuration: its front
    matter supplies shell commands.  Only a regular file counts: a submodule's commit or a link
    names code elsewhere, and a local `diff.ignoreSubmodules` hides nothing here.  A file is
    binary when its committed bytes hold a NUL, whatever `.gitattributes` tells the diff.
    Names are read byte for byte, so each is looked up as the file it is, never a lookalike.
    An AGENTS.md at any depth that is a link makes its target executable configuration too,
    so then nothing skips review.
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
    return (bool(files) and len(modes) == len(files)
            and all(mode.lstrip(":") in ("000000", "100644", "100755")
                    for pair in modes for mode in pair)
            and all(len(row) == 3 and row[0].isdigit() and row[1].isdigit()
                    and document(row[2]) for row in files)
            and all(text_blob(repo, ref, row[2]) for pair, row in zip(modes, files)
                    for mode, ref in zip(pair, (base, head)) if mode.lstrip(":") != "000000"))


def document(name):
    """Is the file `name` a document people read, as `text_only_pr` counts them?"""
    path = Path(name)
    suffix = path.suffix.lower()
    prose = suffix in (".md", ".markdown", ".rst", ".adoc", ".txt", ".text")
    if path.name.upper() == "AGENTS.MD":
        return False        # executable configuration, wherever it sits
    if path.stem.upper() in ("README", "CHANGELOG", "LICENSE", "COPYING", "NOTICE", "AUTHORS",
                             "ARCHITECTURE"):
        return prose or not suffix
    return prose and len(path.parts) > 1 and path.parts[0] == "docs"


def text_blob(repo, ref, path):
    """Do the bytes `path` names at `ref` read back, with no NUL among them?"""
    try:
        return "\0" not in gitcall.git_bytes(repo, "cat-file", "blob", f"{ref}:{path}")
    except (config.Error, gitcall.Stopped):
        return False


MERGE_METHODS = {"squash": "--squash", "merge": "--merge", "rebase": "--rebase"}
# the race a merge can lose to a merge to the target between the push and this call; the
# answer is a retry, never an ending -- see `do_merge`
BASE_BRANCH_MODIFIED = re.compile(r"Base branch was modified", re.I)
# the same answer about the head right after delivery pushed it: GitHub has not yet taken the
# push in, and the re-check ends the run if the head really moved
HEAD_BRANCH_MODIFIED = re.compile(r"Head branch was modified", re.I)
# GitHub's own server failing the call, which its answer says to resubmit: the merge may or
# may not have gone through, so it is re-checked and retried like the race above
GITHUB_5XX = re.compile(r"status code: 5\d\d|HTTP 5\d\d|Bad Gateway|Gateway Timeout|"
                        r"Service Unavailable|couldn't respond to your request in time", re.I)
# GitHub refusing a push for a reason of its own (`! [remote rejected] HEAD -> b (failed)`),
# which the same push went through a minute later: tried again -- see `git_push`.  The lease's
# refusal is git's own `! [rejected] ... (stale info)` and ends the run at once
REMOTE_REJECTED = re.compile(r"^.*\[remote rejected\].*$", re.M)
GITHUB_RETRIES = 3     # how often any of them is waited out and tried again
# GitHub refusing a head pushed seconds before, while it has not yet worked out whether it
# merges: its state is asked again while UNKNOWN, and a PR it then calls CLEAN is tried once
# more -- see `do_merge`
NOT_MERGEABLE = re.compile(r"Pull Request is not mergeable", re.I)


PICKUP_HELD = threading.local()   # delivery locks this thread holds or waits for


# --- the merge pipeline: PASS -> origin -> a PR -> its checks -> merged -----


def merged(lp, url, method):
    """Record the PR as merged, with what proving it live stands on; True, for the merge step
    to return."""
    from . import watch  # here, not at the top: it reaches run
    lp.state.update(merged=True, **watch.merge_record(lp.wt, lp.state.get("delivery_sha")))
    lp.write()
    lp.log(f"--- merge: merged {url} with --{method}, remote branch deleted")
    return True


def is_delivery(lp, current, upstream):
    """Is this PR (`pr_head`) still this run's delivery: the reviewed head, aimed at `upstream`?"""
    return (current["head"]["sha"] == lp.state["delivery_sha"]
            and (current.get("base") or {}).get("ref") == upstream.removeprefix("origin/"))


def merged_anyway(lp, url, upstream):
    """Did GitHub merge this delivery whatever `gh pr merge` answered?  Records it when it did.

    A 5xx or a stopped call may have merged it, and `--delete-branch` exits non-zero on a
    merge that went through when the repository deleted the head branch first (`Reference
    does not exist`).  Only `merged` says so -- mergeability is never the outcome -- and only
    a merge of the delivery into its target is this run's work: a head another writer
    replaced, or a PR retargeted and merged elsewhere, is not.
    """
    try:
        current = pr_head(lp.run_dir, url)
    except gitcall.Stopped:
        raise
    except config.Error:
        return False
    return (current.get("merged") and is_delivery(lp, current, upstream)
            and merged(lp, url, lp.state["merge_method"]))


def do_merge(lp, url, upstream):
    """Merge the PR, integrating once more if origin moved under it while the checks ran.

    Task runs and a seat's own PR (`merge_own_pr`) both end here: a rule on what may merge
    holds on both paths, and a guard on one alone is a bypass.

    `gh pr merge` answering `Base branch was modified` is a race with a merge to the
    target between the push and this call, not an ending: the answer is re-fetched, the
    PR is re-checked to still be mergeable, and the merge is tried again -- three times,
    with a growing wait -- and only then does the run park `waiting` with the reason,
    retried after the next merge to the target.  GitHub answering with a 5xx of its own
    takes the same road, and a merge it went through with anyway counts as merged; so does
    `Head branch was modified` straight after the delivery's own push, which the re-check
    ends only when git shows the PR head is another commit (`pr_head`).  After `Pull Request
    is not mergeable`, GitHub is asked again while it reports the PR's state UNKNOWN, up to
    GITHUB_RETRIES times, and a PR it then calls CLEAN is tried once more.  Work
    that passed review is never thrown away over one lost race or one bad answer.
    """
    method = lp.state["merge_method"]
    why, raced = "", 0
    for attempt in (1, 2):
        ready, lost = True, False
        while True:
            require_review_pass(lp)
            if lp.state["review"].get("head_sha") != lp.state["delivery_sha"]:
                return roundloop.note(lp, "the delivery SHA is not the tested and reviewed commit", failed=True)
            if ready:
                if (lp.state.get("waiting_on") or {}).get("line"):
                    gitcall.fetch(lp.wt, "origin", "--prune", check=True)
                    if not roundloop.integrated(lp.wt, upstream):
                        return rejoin_line(lp, upstream, "the PR's target moved")
                body = [] if method == "rebase" else merge_body(lp, lp.state["delivery_sha"], url)
                rc, out = gitcall.gh(lp.run_dir, "pr", "merge", url, MERGE_METHODS[method], "--delete-branch",
                             "--match-head-commit", lp.state["delivery_sha"], *body)
            if rc == 0 or gitcall.stopped(rc, out):
                break
            if BASE_BRANCH_MODIFIED.search(out or ""):
                cause = "the base branch was modified under the merge"
            elif HEAD_BRANCH_MODIFIED.search(out or ""):
                cause = "GitHub had not yet taken the pushed head"
            elif GITHUB_5XX.search(out or ""):
                cause = "GitHub failed the merge call"
            else:
                break
            if raced >= GITHUB_RETRIES:
                lost = True
                break
            raced += 1
            delay = turns.transient_delay(raced)
            lp.log(f"WARN {cause}; re-fetching, re-checking and retrying in {delay}s "
                   f"({raced}/{GITHUB_RETRIES})")
            step = history.close_step(lp.state.get("run_id"), log=lp.log)   # a wait, not work
            time.sleep(delay)
            history.open_step(lp.state.get("run_id"), step, log=lp.log)
            frc, fetched = gitcall.fetch(lp.wt, "origin")
            if frc != 0:
                return roundloop.note(lp, f"git fetch origin failed: {fetched[-400:]}", failed=True)
            try:
                current = pr_head(lp.run_dir, url)
            except gitcall.Stopped:
                raise
            except config.Error as exc:
                return roundloop.note(lp, f"could not re-check the PR: {exc}", failed=True)
            if not is_delivery(lp, current, upstream):
                return roundloop.note(lp, "PR head or target changed since PASS; a new run is required",
                            failed=True)
            if current.get("merged"):
                return merged(lp, url, method)
            if current.get("state") != "open":
                return roundloop.note(lp, "PR is closed without a merge", failed=True)
            # A moving target can change both the patch and its checks. Reuse the same
            # integration path as a BEHIND retry before authorizing the new head.
            head = lp.state["delivery_sha"]
            if (lp.state.get("waiting_on") or {}).get("line"):
                if not roundloop.integrated(lp.wt, upstream):
                    return rejoin_line(lp, upstream, "the PR's target moved")
            elif not roundloop.integrate(lp, upstream):
                return False
            if gitcall.git(lp.wt, "rev-parse", "HEAD") != head:
                if not roundloop.final_check(lp, upstream) or not push(lp) or not wait_checks(lp, url):
                    return False
                if not refresh_pr_body(lp):
                    return False
                ready = True
            else:
                # GitHub may still be computing mergeability. An unconfirmed answer
                # uses the remaining retries to re-check before authorizing a merge.
                ready = current.get("mergeable") is True
        if rc == 0:
            return merged(lp, url, method)
        if lost:
            # the last attempt's 5xx may have merged too, and no re-check followed it
            if merged_anyway(lp, url, upstream):
                return True
            return roundloop.park_waiting(
                lp, f"gh pr merge --{method} failed after {GITHUB_RETRIES} retries: {cause}; "
                    f"the PR is open at {url}", upstream,
                gitcall.git(lp.wt, "rev-parse", f"{upstream}^{{commit}}", check=False) or None)
        refused = bool(NOT_MERGEABLE.search(out or ""))
        for polled in range(GITHUB_RETRIES + 1):
            if polled:
                time.sleep(CHECKS_POLL)     # GitHub still working out a head pushed just now
            vrc, why = gitcall.gh(lp.run_dir, "pr", "view", url, "--json", "mergeStateStatus",
                          "-q", ".mergeStateStatus")
            if not refused or vrc != 0 or why != "UNKNOWN":
                break
        if gitcall.stopped(rc, out) or gitcall.stopped(vrc, why):
            # a merge that stopped may still have gone through server-side
            if merged_anyway(lp, url, upstream):
                return True
            raise gitcall.Stopped(out if gitcall.stopped(rc, out) else why)
        if attempt == 2 or why not in ("BEHIND", "DIRTY", "CLEAN"):
            break
        if why == "CLEAN":
            if not refused:
                break
            lp.log("WARN GitHub called the PR not mergeable, then CLEAN: it had not yet worked "
                   "out the head just pushed; retrying the merge")
            continue
        lp.log(f"WARN the PR is {why}; taking {upstream} in once more and retrying the merge")
        if (lp.state.get("waiting_on") or {}).get("line"):
            return rejoin_line(lp, upstream, f"the PR is {why}")
        # the retry pushes a new head, so its checks are a new run: wait them out again rather
        # than merging on the strength of the ones that passed for the commit just replaced --
        # and its `# once` commands too, which have only ever run on that commit
        if (not roundloop.integrate(lp, upstream) or not roundloop.final_check(lp, upstream) or not push(lp)
                or not wait_checks(lp, url)):
            return False
        if not refresh_pr_body(lp):
            return False
    if merged_anyway(lp, url, upstream):
        return True
    return roundloop.note(lp, f"gh pr merge --{method} failed"
                    f"{f' with the PR {why}' if why else ''}; the PR is open at {url}: {out[-400:]}",
                failed=True)


# a landing's failures, each counted apart and each bounded by CONFLICT_ROUNDS: a conflict with
# the target is the world moving, so it never spends the budget of the work's own red checks
LANDING_COUNTS = ("landing_reds", "landing_conflicts")


def landing_count(failure):
    """The count a landing failure spends: `landing_conflicts` for the lander's conflict with
    the target's tip, `landing_reds` for a red check or anything else."""
    return "landing_conflicts" if failure.get("conflict") else "landing_reds"


def forget_landing_counts(state):
    for key in LANDING_COUNTS:
        state.pop(key, None)


def join_line(lp, upstream, deliver):
    """Leave a passed run's place on disk; a fresh process consumes the lander's verdict."""
    if (lp.state.get("waiting_on") or {}).get("line"):
        return land_from_line(lp, upstream, deliver)
    require_review_pass(lp)
    lp.state.update(state="waiting", waiting_on={"line": turn_path(lp, upstream).name,
                                               "joined": time.time()},
                    error="waiting for the lander", finished_at=None)
    lp.state.pop("recovery_pending", None)
    lp.write()
    return False


def release_line(run_dir, log):
    """Finish this attempt's cleanup before the lander can wake a new record owner."""
    with run_record.recovery_lock(run_dir):
        state = run_record.read_state(run_dir) or {}
        if (state.get("state") != "waiting" or state.get("pid") != os.getpid()
                or not (state.get("waiting_on") or {}).get("line")):
            return
        turns.stop_run_tree(state, log)
        state.update(pid=None, process_identity=None)
        run_record.save_state(run_dir, state)
    landing.start_line(config.RUNS / state["waiting_on"]["line"], log)


def rejoin_line(lp, upstream, reason):
    """A rejoining run keeps its place, repaired work included: checked again soon, it meets
    the target it was fixed against, not one moved by every landing a lap at the back takes."""
    wait = lp.state["waiting_on"]
    lp.log(f"rejoins the line: {reason}")
    lp.state.update(state="waiting", error=reason, merge_failed=False, merge_note=reason,
                    waiting_on={"line": turn_path(lp, upstream).name, "joined": wait["joined"]})
    lp.state.pop("recovery_pending", None)
    lp.write()
    return False


def land_from_line(lp, upstream, deliver):
    """Consume the lander's verdict in this run; only delivery holds the plain merge flock."""
    wait = lp.state["waiting_on"]
    if landing.green_delivery(wait):
        turn = turn_path(lp, upstream)
        try:
            with merge_lock(lp, upstream):
                gitcall.fetch(lp.wt, "origin", "--prune", check=True)
                tip = gitcall.git(lp.wt, "rev-parse", f"{upstream}^{{commit}}")
                how = roundloop.how_to_integrate(lp)
                args = ("merge", "--no-edit", tip) if how == "merge" else ("rebase", tip)
                saved = dict(lp.state["review"])
                try:
                    code, _ = gitcall.git_out(lp.wt, *args)
                except gitcall.Stopped:
                    roundloop.abort_stopped_integration(lp, how)
                    raise
                if code:
                    roundloop.abort_integration(lp, how)
                    reason = (f"its {how} onto {upstream} at {tip[:12]} stopped on a conflict; "
                              "the lander checks it again")
                    return rejoin_line(lp, upstream, reason)
                roundloop.set_base(lp, tip)
                identity = gitcall.commit_identity(lp.wt)
                lp.state["review"] = {**saved, **identity,
                                      "passed_head_sha": roundloop.passed_review_head(lp.state),
                                      "rebased_from": saved["head_sha"]}
                lp.write()
                if identity["tree_sha"] != wait["land"]:
                    # Its tree alone on the tip is not the stack the lander passed: a change
                    # stacked ahead of it has not landed yet, or the target moved.
                    reason = (f"on {upstream} at {tip[:12]} its tree is {identity['tree_sha'][:12]}, "
                              f"not the {wait['land'][:12]} the lander checked: a change stacked "
                              f"ahead of it has not landed yet, or {upstream} moved")
                    return rejoin_line(lp, upstream, reason)
                if gitcall.git_out(lp.wt, "diff", "--quiet", tip, "HEAD")[0] == 0:
                    lp.state.update(on_target=True)
                    lp.state.pop("waiting_on", None)
                    forget_landing_counts(lp.state)
                    return roundloop.note(lp, f"its work is already on {upstream.removeprefix('origin/')}")
                if saved.get("skipped") and not text_only_pr(lp.wt, tip, "HEAD"):
                    # work not on the target yet: the target may have carried the wording onto
                    # files that need review (a rename, say)
                    path = lp.run_dir / "review-needed.log"
                    path.write_text("Rebased onto the target, this wording PR now changes files "
                                    "that need review; push the rebased branch and it is reviewed.\n")
                    return fail_pr_landing(lp, {"line": path.read_text().strip(), "log": str(path)},
                                           landing=False)
                lp.state["final_check"] = {"outcome": "passed", "where": "landing",
                                           "sha": identity["head_sha"],
                                           "tree_sha": identity["tree_sha"],
                                           "tested": wait.get("tested") or (
                                               landing.passed(turn, wait["land"]) or {}).get(
                                                   "tested", identity["tree_sha"]),
                                           "suite": gitcall.declared_suite(lp.wt, lp.target, ref=tip)}
                lp.write()
                result = deliver()
                if "fix" in lp.state.get("waiting_on", {}):
                    # Red required checks need a fixer, which this attempt was admitted without
                    # weighing (`gate.claim_slot`): it parks on that verdict for the lander's wake.
                    lp.state["state"] = "waiting"
                    lp.write()
                    return False
                if result:
                    lp.state.pop("waiting_on", None)
                    forget_landing_counts(lp.state)
                    lp.write()
                return result
        finally:
            # Departures and changed-target rejoins were written under this flock.
            landing.start_line(turn, lp.log)
    if "fix" not in wait:
        return rejoin_line(lp, upstream, "waiting for the lander")
    failure = wait["fix"]
    if lp.state.get("review_pr"):
        # a head the seat pushed past its review is new work, reviewed as a round: no landing red
        return fail_pr_landing(lp, failure, landing=not failure.get("moved"))
    count = landing_count(failure)
    if not wait.get("fixing"):
        lp.state[count] = lp.state.get(count, 0) + 1
        if suite_red(lp.state, failure):
            history.add_landing_break(lp.state.get("run_id"), log=lp.log)
        lp.state["waiting_on"] = {**wait, "fixing": True}
        lp.write()
    if lp.state[count] > roundloop.CONFLICT_ROUNDS:
        lp.state.pop("waiting_on", None)
        # The counts bound one landing; a person who resumes the ended run starts a new one.
        forget_landing_counts(lp.state)
        how = "conflicted with the target" if count == "landing_conflicts" else "failed"
        return roundloop.note(lp, f"landing {how} four times: {failure['line']}; see {failure['log']}",
                    failed=True)
    if not roundloop.integrate(lp, upstream):
        if lp.state.get("merge_failed"):
            raise config.Error(lp.state["merge_note"])
        lp.state["state"] = "running"
        if not lp.state.get("review_pending") or roundloop.resume_review(lp) != "PASS":
            lp.state.pop("waiting_on", None)
            lp.write()
            return False
    if not lp.state["waiting_on"].get("fixed"):
        text = Path(failure["log"]).read_text(errors="replace")
        if not roundloop.fix_final_check(lp, upstream, text):
            lp.state.pop("waiting_on", None)
            lp.write()
            return False
    return rejoin_line(lp, upstream, "landing fixes passed review")


def land(lp, upstream, verify, deliver, execv=None):
    """Consume a line verdict, or verify once before taking the delivery lock.

    Only delivery holds the repository lock; checks and fixers run outside it.
    """
    from . import gate  # here, not at the top: it reaches run
    from . import run  # here, not at the top: run imports deliver
    if (lp.state.get("waiting_on") or {}).get("line"):
        return land_from_line(lp, upstream, deliver)
    run.pickup_new_code(lp, execv=execv)
    gate.clear_landing_wait(lp.run_dir)
    lp.state["landing"] = True
    lp.write()
    try:
        if not verify():
            return False
        with merge_lock(lp, upstream):
            gitcall.fetch(lp.wt, "origin", "--prune", check=True)
            tip = gitcall.git(lp.wt, "rev-parse", f"{upstream}^{{commit}}")
            if tip != lp.base_sha:
                return roundloop.park_waiting(lp, f"{upstream} changed since verification",
                                    upstream, lp.base_sha)
            return deliver()
    finally:
        lp.state.pop("landing", None)
        gate.clear_landing_wait(lp.run_dir)
        try:
            lp.write()
        except (OSError, run_record.StopRequested):
            pass            # the landing is over however the record ends


@contextmanager
def merge_lock(lp, upstream):
    """Serialize deliveries to one repository and target; the kernel releases a dead holder."""
    from . import gate  # here, not at the top: it reaches run
    config.RUNS.mkdir(parents=True, exist_ok=True)
    held = getattr(PICKUP_HELD, "count", 0)
    PICKUP_HELD.count = held + 1
    try:
        turn = turn_path(lp, upstream)
        with turn.open("a") as lock:
            try:
                while True:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        # Another delivery can spend an hour on PR checks; its waiter is not stalled.
                        lp.state["delivery_wait"] = os.getpid()
                        lp.write()
                        fcntl.flock(lock, fcntl.LOCK_EX)
                    members = landing.line(turn) if landing.green_delivery(
                        lp.state.get("waiting_on") or {}) else []
                    if (not members or members[0][0] == lp.run_dir
                            or not landing.green_delivery(members[0][1]["waiting_on"])):
                        break
                    # Flock does not order contenders; a checked suffix needs its prefix delivered.
                    fcntl.flock(lock, fcntl.LOCK_UN)
                    lp.state["delivery_wait"] = os.getpid()
                    lp.write()
                    run_record.stop_check(lp.run_dir)
                    time.sleep(gate.SLOT_POLL)
            finally:
                if lp.state.pop("delivery_wait", None) is not None:
                    lp.write()
            yield
    finally:
        PICKUP_HELD.count = held


def turn_path(lp, upstream):
    """The delivery lock for `lp`'s repository and target."""
    url = gitcall.git(lp.wt, "remote", "get-url", "origin", check=False) or str(lp.state.get("repo"))
    return merge_lock_path(url, upstream)


def remote_key(url):
    """`host/owner/repo` for a clone URL, however it spells the repository.

    `git@github.com:acme/widget.git`, `ssh://git@github.com:22/acme/widget` and
    `https://github.com/Acme/widget` are one repository: the host and the path are what is
    kept, without a user, a port, a trailing `.git`, or the case GitHub ignores.  A local
    path is itself.
    """
    scp = re.fullmatch(r"(?:[^@/]+@)?([^:/]+):(?!//)(.+)", url)
    parts = urlsplit(url)
    host, path = (scp[1], scp[2]) if scp else (parts.hostname, parts.path)
    return f"{host}/{path.strip('/').removesuffix('.git')}".lower() if host else url


def merge_lock_path(url, upstream):
    """The delivery lock for one repository and target, however a clone spells it."""
    digest = hashlib.sha256(f"{remote_key(url)}\n{upstream}".encode()).hexdigest()
    return config.RUNS / f".merge-{digest}.lock"


def merge(lp):
    """A passed writable run joins the line; a wake delivers its checked tree, a fork its PR.

    Never a model's call.

    Everything here is about `target` -- the branch the PR merges into -- and not about `base`,
    which is only where the run's branch was cut from.  They are the same branch unless the
    task said otherwise.
    """
    if not (lp.state.get("waiting_on") or {}).get("line"):
        require_review_pass(lp)
    lp.state.update(merged=False, merge_failed=False, merge_note=None, on_target=False)
    lp.step("merge")
    branch = lp.state["branch"]
    # merging is the job, so nothing here is a shrug: a run that cannot merge failed to deliver
    # and says so with exit 1.  `--no-merge` is how a run opts out of the job in the first place.
    if shutil.which("gh") is None:
        return roundloop.note(lp, "no `gh` on PATH; push and open the PR yourself", failed=True)
    if "origin" not in gitcall.git(lp.wt, "remote", check=False).split():
        return roundloop.note(lp, f"{lp.state['repo']} has no `origin` remote to merge into", failed=True)
    upstream = lp.target if lp.target.startswith("origin/") else f"origin/{lp.target}"
    target_branch = upstream.split("/", 1)[1]
    if branch == target_branch:
        return roundloop.note(lp, f"this run works directly on {branch}, which is the branch it would merge "
                        "into, so there is no PR to open", failed=True)

    upstream_repo, permission = rights(lp)
    if upstream_repo and permission not in PUSH_RIGHTS:
        return land(lp, upstream, lambda: roundloop.integrate(lp, upstream) and roundloop.final_check(lp, upstream),
                    lambda: fork_and_pr(lp, target_branch, upstream_repo, permission))

    def deliver():
        require_review_pass(lp)
        lp.step("merge")        # integration may have spent rounds of its own on the way here
        if not push(lp):
            return False
        url = open_pr(lp, target_branch)
        if not url or not wait_checks(lp, url):
            return False
        return do_merge(lp, url, upstream)
    return join_line(lp, upstream, deliver)


def own_pr_heads(state):
    """The PR heads that are this run's own: the head it reviewed and the one it pushed."""
    return state.get("head_sha"), state.get("delivery_sha")


def merge_own_pr(lp, url):
    """Join the same line as task runs; deliver only the lander's tested PR tree."""
    if lp.state.get("own_pr") and not lp.state.get("own_orchestrator"):
        return roundloop.note(lp, "no recorded writer for this PR; refusing the automatic merge",
                              failed=True)
    upstream = lp.target if lp.target.startswith("origin/") else f"origin/{lp.target}"

    def deliver():
        current = pr_head(lp.run_dir, url)
        remote = current["head"]
        expected = own_pr_heads(lp.state)
        ours = (remote["sha"] in expected
                and (current.get("base") or {}).get("ref") == upstream.removeprefix("origin/"))
        if current.get("merged") and ours:
            from . import watch  # here, not at the top: it reaches run
            lp.state.update(merged=True, **watch.merge_record(lp.wt, remote["sha"]))
            lp.write()
            return True
        if current.get("state") != "open" or not ours:
            path = lp.run_dir / "pr-changed.log"
            path.write_text("The PR head or target changed, or the PR closed, since review.\n")
            lp.state["review_stale"] = True
            return fail_pr_landing(lp, {"line": path.read_text().strip(), "log": str(path)},
                                   landing=False)
        pinned = gitcall.git(lp.wt, "rev-parse", "HEAD")
        # Keep the intended push before calling Git: a killed push may have gone through.
        lp.state["delivery_sha"] = pinned
        lp.write()
        if remote["sha"] != pinned:
            push_pr_branch(lp, remote, remote["sha"])
        lp.state["head_sha"] = pinned
        lp.write()
        return wait_checks(lp, url) and do_merge(lp, url, upstream)

    return join_line(lp, upstream, deliver)


def pr_head(cwd, url):
    """The pull request as GitHub describes it now, its head named, or an error: what a push
    to its branch and a merge of it stand on.

    An open PR's head commit is git's: its head repository's branch, which moves the moment a
    push succeeds, where GitHub's own read of it can show the head from before a push for
    seconds.  A merged or closed PR keeps the head GitHub closed it on, what merged: its branch
    may have moved or gone since."""
    api, owner, repo, number = pr_parts(url)
    current, why = gh_json(cwd, *api, f"repos/{owner}/{repo}/pulls/{number}")
    if not isinstance(current, dict) or not (current.get("head") or {}).get("sha"):
        raise config.Error(f"cannot read the PR: {why}")
    if current.get("state") == "open":
        head = current["head"]
        ref, source = f"refs/heads/{head.get('ref')}", (head.get("repo") or {}).get("clone_url")
        rc, out = (gitcall.git_out(cwd, "ls-remote", "--", source, ref) if source
                   else (1, "GitHub names no head repository"))
        head["sha"] = next((line.split("\t")[0] for line in out.splitlines() if rc == 0
                            and line.endswith(f"\t{ref}")), None)
        if not head["sha"]:
            raise config.Error(f"cannot read the PR head from git: {out[-400:] or f'no {ref}'}")
    return current


def push_pr_branch(lp, remote, lease):
    """The checkout's HEAD onto the PR branch GitHub describes (`remote`, the PR's head), over
    `lease` and nothing else: a push made by hand meanwhile is never overwritten."""
    branch, source = remote.get("ref"), (remote.get("repo") or {}).get("clone_url")
    if not branch or not source:
        raise config.Error("cannot locate the PR branch to push to")
    rc, out = git_push(lp, f"--force-with-lease=refs/heads/{branch}:{lease}",
                       "--", source, f"HEAD:refs/heads/{branch}")
    if rc:
        raise config.Error(f"pushing to the PR branch failed: {out[-400:]}")


def finish_blocked(run_dir, state, exc, log, cfg):
    """The task cannot be done as written: a final state of its own, because there is no
    verdict on work here and nothing a resume could spend.  The orchestrator that wrote
    the task hears why and writes a new one."""
    from . import worktrees  # here, not at the top: it reaches run
    log(f"BLOCKED {exc}")
    state.update({"state": "blocked", "verdict": "BLOCKED", "error": str(exc),
                  "blocked": exc.section, "finished_at": time.time()})
    state.pop("quota_dry", None)
    run_record.save_state(run_dir, state)
    handback.record_result(run_dir, state, log, cfg)
    worktrees.settle_run(state, run_dir, log)
    return state


def end_on_dependency(cfg, run_dir, state, log, why):
    """End a run cut from a dependency's passed tip, blocked, with the branch to relaunch from."""
    return finish_blocked(run_dir, state, turns.Blocked(why, f"## Blocked\n\n{why}"), log, cfg)


def suite_red(state, failure):
    """Whether a landing failure is the change's own tests going red: a suite piece red on its
    tree after the target alone passed, or a required check failed.  A conflict with the
    target, a head moved past its review, a red target or the rules' size is no such failure:
    nothing there says the review let a defect through.  Nor is a piece a target's repair
    fails: it lands on the red target, which the lander never probes for it."""
    return (("piece" in failure and not state.get("repair"))
            or failure.get("line", "").startswith("required checks failed:"))


def fail_pr_landing(lp, failure, landing=True):
    """The PR's writer fixes a red landing tree, just as it fixes review findings.

    A `landing` red -- the line's check, a required check, a rebase the tip conflicts with --
    gets the run's fixer turn on the PR branch and a re-review that spends no round, however
    the round budget stands (`landing_fix`, read by `review_pr_round`), up to CONFLICT_ROUNDS
    times for one landing, as a task run's landing fixer gets.  A PR whose head moved past its
    review, in the line or under its delivery, or that closed (`landing` off) is reviewed as a
    round, as any new head is, while rounds are left.
    """
    text = prompts.saved_findings(lp.run_dir, lp.state) + "\n\n## Landing failed\n" + Path(failure["log"]).read_text()
    path = lp.run_dir / "landing-findings.md"
    path.write_text(text)
    lp.findings = text
    lp.state.update(verdict="FAIL", findings=text[-8000:], findings_file=str(path),
                    final_check={"outcome": "failed", "where": "landing", "line": failure["line"]})
    lp.state["review"] = {**lp.state["review"], "verdict": "FAIL", "overridden": failure["line"]}
    # the round's delivery is settled in this same write: a resume after it reviews the next head
    lp.state.pop("waiting_on", None)
    lp.state.pop("own_pr_round_pending", None)
    lp.state.pop("landing_fix", None)
    count = landing_count(failure)
    reds = lp.state.get(count, 0)
    if landing:
        reds = lp.state[count] = reds + 1
        if suite_red(lp.state, failure):
            history.add_landing_break(lp.state.get("run_id"), log=lp.log)
    if lp.state.get("own_pr") and (reds <= roundloop.CONFLICT_ROUNDS if landing else lp.rnd < lp.rounds):
        lp.state.update(state="running", finished_at=None, own_pr_wait=lp.state["head_sha"])
        if landing:
            lp.state["landing_fix"] = True
    else:
        if landing:
            how = "conflicted with the target" if count == "landing_conflicts" else "failed"
            lp.state["merge_note"] = f"landing {how} {reds} times: {failure['line']}"
        # the counts bound one landing; a person who resumes the ended run starts a new one
        forget_landing_counts(lp.state)
        lp.state.update(state="fail", finished_at=time.time())
    lp.write()
    return False
