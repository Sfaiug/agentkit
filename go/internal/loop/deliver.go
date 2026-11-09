package loop

import (
	"cmp"
	"crypto/sha256"
	"errors"
	"fmt"
	neturl "net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/gh"
	"agentkit/internal/gitcall"
	"agentkit/internal/host"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

// Delivery is Python's deliver.merge and what it stands on: a passed run's work is taken in on
// the target's tip, checked there once more, and delivered under the repository's delivery lock.
// An account that may only read the repository delivers a PR from a fork, which waits for the
// maintainer; any other joins the landing line (line.go) and, woken on its verdict, pushes and
// merges its own PR (merge.go).

// forkRemote is the remote a run adds for its fork; `origin` stays the upstream.
const forkRemote = "fork"

var (
	prURL = regexp.MustCompile(`https://\S+?/pull/\d+`)
	// a clone URL spelled `user@host:path`, Python's remote_key: a path starting `//` is a URL's
	scpURL      = regexp.MustCompile(`^(?:[^@/]+@)?([^:/]+):(.+)$`)
	failureLine = regexp.MustCompile(`^(?:FAIL(?:ED)?|ERROR|not ok)\b`)
)

// merge delivers the passed work, Python's merge with its loop's catch: a git or gh that stopped
// here leaves a PASS needing one command, which `merge_failed` lets `ak run merge` pick up.
func (r *repoPlace) merge(l *loop) error {
	err := r.deliver(l)
	var stopped *gitcall.Stopped
	if errors.As(err, &stopped) {
		return r.note(l, stopped.Why, true)
	}
	return err
}

func (r *repoPlace) deliver(l *loop) error {
	record, err := run.Read(l.dir)
	if record == nil {
		return cmp.Or(err, errors.New("run.json cannot be read"))
	}
	// a member of the line answers to its lander's verdict, which its delivery checks again
	if landingLine(record) == "" {
		if err := r.requireReviewPass(l); err != nil {
			return err
		}
	}
	if err := l.save(func(record *run.Object) {
		run.SetAll(record, "merged", false, "merge_failed", false, "merge_note", nil, "on_target", false)
	}); err != nil {
		return err
	}
	if err := l.step("merge"); err != nil {
		return err
	}
	// merging is the job, so a run that cannot merge failed to deliver
	if _, err := exec.LookPath("gh"); err != nil {
		return r.note(l, "no `gh` on PATH; push and open the PR yourself", true)
	}
	remotes, err := r.git().Try("remote")
	if err != nil {
		return err
	}
	if !slices.Contains(strings.Fields(remotes), "origin") {
		return r.note(l, r.repo+" has no `origin` remote to merge into", true)
	}
	upstream := r.upstream()
	target := strings.TrimPrefix(upstream, "origin/")
	if r.branch == target {
		return r.note(l, fmt.Sprintf("this run works directly on %s, which is the branch it would merge into, so there is no PR to open", r.branch), true)
	}
	repo, permission, said, err := gh.Rights(r.wt)
	if err != nil {
		return err
	}
	if repo == "" {
		l.say("WARN gh repo view could not say whether this account may push: " + tail(said, 200))
	}
	if repo == "" || gh.Writable(permission) {
		return r.joinLine(l, upstream, func() error { return r.deliverOwn(l, target, upstream) })
	}
	return r.land(l, upstream, func() error { return r.forkAndPR(l, target, repo, permission) })
}

// requireReviewPass ends a delivery that has no review of the commit it would deliver.
func (r *repoPlace) requireReviewPass(l *loop) error {
	passed, current, err := r.reviewed(l)
	switch {
	case err != nil:
		return err
	case !passed:
		return &exhausted{"delivery requires a successful reviewer allowed by the model policy; resume the run to obtain review", false}
	case !current:
		return &exhausted{"delivery requires done-when and review of the current commit; resume the run to obtain review", false}
	}
	return nil
}

// reviewed is whether the record holds a successful review, and whether it is of the commit and
// tree the checkout has out, Python's current_review.
func (r *repoPlace) reviewed(l *loop) (bool, bool, error) {
	record, err := run.Read(l.dir)
	if record == nil {
		return false, false, cmp.Or(err, errors.New("run.json cannot be read"))
	}
	if !run.ReviewPass(record, run.Models()) {
		return false, false, nil
	}
	head, tree, err := r.identity()
	review := record.Dict("review")
	return true, review.Str("head_sha") == head && review.Str("tree_sha") == tree, err
}

// note is why the branch is not merged, Python's note: failed is the run not doing its job.
func (r *repoPlace) note(l *loop, reason string, failed bool) error {
	reason = strings.Join(strings.Fields(reason), " ") // result.md gives it one line
	word := "WARN "
	if failed {
		word = "ERROR "
	}
	l.say(word + "not merged: " + reason)
	return l.save(func(record *run.Object) { run.SetAll(record, "merge_note", reason, "merge_failed", failed) })
}

// park leaves the run waiting on the next merge to ref, Python's park_waiting: the work passed
// review and only the world stands in its way, so the tick retries it there.
func (r *repoPlace) park(l *loop, reason, ref, sha string) error {
	if err := r.note(l, reason, false); err != nil {
		return err
	}
	if err := l.save(func(record *run.Object) {
		run.SetAll(record, "state", "waiting", "error", reason, "waiting_on", run.Fields("ref", ref, "sha", sha))
		record.Delete("recovery_pending") // the wait is the tick's now
	}); err != nil {
		return err
	}
	l.say("--- merge: parked waiting; retried after the next merge to " + ref)
	return nil
}

// land is Python's land off a landing line: the work is verified on the target's tip, then
// delivered under the delivery lock while that tip is still the one verified.  A Go driver is the
// program it started as, so Python's pickup of newer code before landing has nothing to pick up.
func (r *repoPlace) land(l *loop, upstream string, deliver func() error) error {
	return r.landingMark(l, func() error {
		if ok, err := r.integrate(l, upstream); err != nil || !ok {
			return err
		}
		if ok, err := r.finalCheck(l); err != nil || !ok {
			return err
		}
		held, err := r.mergeLock(l, upstream)
		if err != nil {
			return err
		}
		defer held.Close()
		code, out, err := r.git().Fetch("origin", "--prune")
		if err != nil {
			return err
		}
		if code != 0 {
			return r.note(l, "git fetch origin --prune failed: "+tail(out, 400), true)
		}
		tip, err := r.git().Must("rev-parse", upstream+"^{commit}")
		if err != nil {
			return err
		}
		if tip != r.baseSHA {
			return r.park(l, upstream+" changed since verification", upstream, r.baseSHA)
		}
		return deliver()
	})
}

// landingMark marks the run `landing` while landing runs, however it ends, Python's landing_mark:
// its checks wait as a lander's, and a landing counts from its own first wait.
func (r *repoPlace) landingMark(l *loop, landing func() error) error {
	host.ClearLandingWait(l.dir)
	if err := l.save(func(record *run.Object) { record.Set("landing", true) }); err != nil {
		return err
	}
	err := landing()
	host.ClearLandingWait(l.dir)
	write(l.dir, func(record *run.Object) { record.Delete("landing") })
	return err
}

// integrate takes in the target's tip, Python's integrate: a branch that does not hold it yet is
// rebased onto it, or merged with it, and checked again there, and its review stands when the
// checks pass on the commit the integration made; a conflict's fixer has its work reviewed again.
// A red, or checks that leave work to review again, are Python's; a branch with nothing left over
// the tip ends PASS as already on the target.
func (r *repoPlace) integrate(l *loop, upstream string) (bool, error) {
	g := r.git()
	// --prune: a merged PR's branch, deleted on origin, otherwise leaves its tracking ref behind,
	// and push's lease holds a later run that reuses the name to that dead head
	code, out, err := g.Fetch("origin", "--prune")
	if err != nil {
		return false, err
	}
	if code != 0 {
		return false, r.note(l, "git fetch origin failed: "+tail(out, 400), true)
	}
	tip, err := g.Try("rev-parse", "--verify", "--quiet", upstream+"^{commit}")
	if err != nil {
		return false, err
	}
	if tip == "" {
		return false, r.note(l, upstream+" does not exist on origin; nothing to merge into", true)
	}
	record, err := run.Read(l.dir)
	if record == nil {
		return false, cmp.Or(err, errors.New("run.json cannot be read"))
	}
	how, err := r.how(record)
	if err != nil {
		return false, err
	}
	head, _, err := r.identity()
	if err != nil {
		return false, err
	}
	code, _, err = g.Out("merge-base", "--is-ancestor", tip, "HEAD")
	if err != nil {
		return false, err
	}
	held := code == 0
	saved, verdict := record.Dict("review"), record.Get("verdict")
	landing := landingReview(record)
	if !held {
		// before git rewrites HEAD: an interruption must not leave a PASS saved on it, and a
		// landing's review already pending stays as it was
		if landing {
			err = l.save(func(record *run.Object) { run.SetAll(record, "verdict", nil, "review", nil) })
		} else {
			err = r.pendingReview(l, "Re-review after the "+how+" of "+upstream+".")
		}
		if err != nil {
			return false, err
		}
	}
	if how == "merge" {
		l.say(fmt.Sprintf("--- merge: merging %s (%s) into %s", upstream, tip[:12], r.branch))
		l.say(fmt.Sprintf("--- merge: merging %s into %s", upstream, r.branch))
	} else {
		l.say(fmt.Sprintf("--- merge: rebasing %s onto %s (%s)", r.branch, upstream, tip[:12]))
	}
	carried, fixed, err := r.integrateTip(l, upstream, how, tip, true)
	if err != nil || !carried {
		return false, err
	}
	switch {
	case landing && !fixed:
		if passed, err := r.reviewLanding(l, upstream, how); err != nil || !passed {
			return false, err
		}
	case held:
		l.say("--- merge: unchanged commit; reusing done-when and review evidence")
	case !fixed:
		if err := r.recheck(l, upstream, how, head, saved, verdict); err != nil {
			return false, err
		}
	}
	code, _, err = g.Out("diff", "--quiet", tip, "HEAD")
	if err != nil || code != 0 {
		return err == nil, err // a diff left over the tip is work to deliver
	}
	if err := l.save(func(record *run.Object) { record.Set("on_target", true) }); err != nil {
		return false, err
	}
	return false, r.note(l, "its work is already on "+strings.TrimPrefix(upstream, "origin/"), false)
}

// how is the way the branch takes the target's tip in, Python's how_to_integrate: a branch carrying
// merges, or a task asking for one, keeps its history with a merge; any other rebases.
func (r *repoPlace) how(record *run.Object) (string, error) {
	merges, err := r.git().Try("rev-list", "--merges", r.baseSHA+"..HEAD")
	if record.Str("merge_method") == "merge" || merges != "" {
		return "merge", err
	}
	return "rebase", err
}

// integration is git's arguments taking tip in that way.
func integration(how, tip string) []string {
	if how == "merge" {
		return []string{"merge", "--no-edit", tip}
	}
	return []string{"rebase", tip}
}

// abort puts the branch back after an integration that stopped or conflicted, Python's
// abort_integration and abort_stopped_integration: whoever carries the run on starts from a clean
// tree.  An abort that fails is said, never claimed clean.
func (r *repoPlace) abort(l *loop, how string, stopped bool) {
	code, out, err := r.git().Out(how, "--abort")
	if err != nil {
		out = err.Error()
	}
	switch {
	case err != nil || code != 0:
		l.say(fmt.Sprintf("WARN could not abort the %s of %s: %s; the retry starts from whatever the %s left behind", how, r.branch, tail(out, 200), how))
	case stopped:
		l.say(fmt.Sprintf("--- merge: aborted the stopped %s; %s back on its head", how, r.branch))
	}
}

// pendingReview takes the passed review off the record until the integrated commit earns it,
// Python's pending_review: a landing review spends no round.
func (r *repoPlace) pendingReview(l *loop, reason string) error {
	return l.save(func(record *run.Object) {
		summary := ""
		if entries := record.List("round_summaries"); len(entries) > 0 {
			if entry, ok := entries[len(entries)-1].(*run.Object); ok {
				summary = entry.Str("summary")
			}
		}
		pending := run.Fields("round", l.rnd, "record", false, "summary", summary, "reason", reason)
		if passed := passedReviewHead(record); passed != "" {
			pending.Set("passed_head_sha", passed)
		}
		run.SetAll(record, "verdict", nil, "review", nil, "review_pending", pending)
	})
}

// passedReviewHead is the last reviewed head whose task checks passed, Python's passed_review_head.
func passedReviewHead(record *run.Object) string {
	pending, reviewed := cmp.Or(record.Dict("review_pending"), run.NewObject()), cmp.Or(record.Dict("review"), run.NewObject())
	if passed := cmp.Or(pending.Str("passed_head_sha"), reviewed.Str("passed_head_sha")); passed != "" {
		return passed
	}
	if reviewed.Str("verdict") == "PASS" && reviewed.Truthy("done_when") {
		return cmp.Or(reviewed.Str("rebased_from"), reviewed.Str("head_sha"))
	}
	entries := record.List("round_summaries")
	for i := len(entries) - 1; i >= 0; i-- {
		if entry, ok := entries[i].(*run.Object); ok && entry.Str("verdict") == "PASS" && entry.Truthy("done_when") && entry.Truthy("head_sha") {
			return cmp.Or(entry.Str("passed_head_sha"), entry.Str("head_sha"))
		}
	}
	return ""
}

// checkedAgain is the round's checks on the commit a clean integration made, Python's verify_work
// there: what they printed once they pass, and a red is a fixer's at landing, not Go's yet.
func (l *loop) checkedAgain(upstream, how string) (string, error) {
	ok, text, err := l.verify()
	if err != nil {
		return "", err
	}
	if !ok {
		l.say("done-when after the " + how + ": FAILED")
		return "", notYet(fmt.Sprintf("done-when after the %s of %s failed: %s", how, upstream, firstFailure(text)), "a fixer at landing")
	}
	l.say("done-when after the " + how + ": all passed")
	return text, nil
}

// recheck runs the round's checks on the commit an integration made, Python's integrate after a
// clean one: passing on that same commit, the review saved before it stands for it.
func (r *repoPlace) recheck(l *loop, upstream, how, before string, saved *run.Object, verdict any) error {
	head, tree, err := r.identity()
	if err != nil {
		return err
	}
	text, err := l.checkedAgain(upstream, how)
	if err != nil {
		return err
	}
	if moved, err := r.changedSince(head, tree); err != nil || moved {
		return cmp.Or(err, notYet("the checks after the "+how+" changed the commit", "reviewing it again at landing"))
	}
	l.say(fmt.Sprintf("--- merge: clean %s of %s; done-when passed again, review kept", how, upstream))
	return l.save(func(record *run.Object) {
		// patch_id, which nothing reads, is left out
		review := run.SetAll(saved, "head_sha", head, "tree_sha", tree, "passed_head_sha", none(passedReviewHead(record)), "rebased_from", before)
		run.SetAll(record, "review", review, "verdict", verdict)
		keepFlakes(record, text)
		record.Delete("review_pending")
	})
}

// finalCheck runs the round's checks and those deferred to landing on the commit about to be
// delivered, Python's final_check: the task's and the target's declarations at the tip it was
// taken in on, pinned to that commit.  A red is a final check's fixer's, which is Python's.
func (r *repoPlace) finalCheck(l *loop) (bool, error) {
	_, cmds, err := task.Read(filepath.Join(l.dir, "task.md"))
	if err != nil {
		return false, err
	}
	suite := gitcall.Suite(r.wt, r.baseSHA)
	every, once := task.Group(task.RoundCommands(cmds, suite, true))
	if len(once) == 0 {
		return true, nil
	}
	l.once = once // what takes a heavy-suite turn, here and in its probes: a rebase may change the suite
	head, tree, err := r.identity()
	if err != nil {
		return false, err
	}
	l.say(fmt.Sprintf("--- merge: final check: %d commands (%d once) on %s", len(every)+len(once), len(once), head[:12]))
	code, _, err := r.git().Out("diff", "--quiet", "HEAD")
	if err != nil {
		return false, err
	}
	path := filepath.Join(l.dir, "final-check.log")
	ok, text, err := r.checks(l, append(every, once...), path, nil)
	if err != nil {
		return false, err
	}
	moved, err := r.changedSince(head, tree)
	if err != nil {
		return false, err
	}
	if code != 0 || moved {
		ok = false
		text += "\n\nCheckout changed during the final check; these commands do not verify the pinned commit."
	}
	text = fmt.Sprintf("Commit: %s\nTree: %s\n\n%s", head, tree, text)
	if err := os.WriteFile(path, []byte(text), 0o666); err != nil {
		return false, err
	}
	if !ok {
		line := firstFailure(text)
		l.say("final check: FAILED")
		if err := l.save(func(record *run.Object) {
			record.Set("final_check", run.Fields("outcome", "failed", "sha", head, "where", "landing", "line", line))
		}); err != nil {
			return false, err
		}
		return false, notYet("the final check failed: "+line, "a final check's fixer")
	}
	l.say("final check: all passed")
	_, current, err := r.reviewed(l)
	if err != nil {
		return false, err
	}
	return true, l.save(func(record *run.Object) {
		checked := run.Fields("outcome", "passed", "sha", head, "where", "landing")
		// the checked tree: a later integration can carry the commit without the suite again
		if suite != "" && slices.Contains(once, suite) {
			run.SetAll(checked, "suite", suite, "tree_sha", tree)
		}
		record.Set("final_check", checked)
		if current {
			record.Dict("review").Set("passed_head_sha", head)
		}
		keepFlakes(record, text)
	})
}

// firstFailure is the first failing command and the line that says what failed, for a person,
// Python's first_failure: the first line it printed starting FAIL, FAILED, ERROR or `not ok`,
// else its last, else the command alone; with no command failing, what the loop said instead.
func firstFailure(text string) string {
	failing, named, last, note := "", "", "", ""
	for _, record := range strings.Split(text, "\n\n") {
		if strings.HasPrefix(record, "flaky: ") {
			continue
		}
		if mark := checkRecord.FindStringSubmatch(record); mark != nil {
			if failing != "" {
				break // the next command's record: the first failing one said all it had
			}
			if mark[2] != "exit 0" {
				failing = mark[1]
			}
			record = record[len(mark[0]):]
		}
		for _, line := range config.SplitLines(record) {
			switch line = gitcall.Strip(line); {
			case loopNote.MatchString(line):
				note = cmp.Or(note, line)
			case failing != "" && line != "":
				if named == "" && failureLine.MatchString(line) {
					named = line
				}
				last = line
			}
		}
	}
	said := cmp.Or(named, last, note)
	line := said
	if failing != "" {
		line = "`" + failing + "`"
		if said != "" {
			line += " — " + said
		}
	}
	if runes := []rune(line); len(runes) > 200 {
		line = string(runes[:199]) + "…"
	}
	return line
}

// mergeLock serializes deliveries to one repository and target, Python's merge_lock, on the file
// Python's takes: the kernel releases a dead holder.  A delivery waiting on another, which can
// spend an hour on PR checks, says so on its record, so nobody reads it as stalled.
func (r *repoPlace) mergeLock(l *loop, upstream string) (*os.File, error) {
	path, err := r.turn(upstream)
	if err != nil {
		return nil, err
	}
	if err := os.MkdirAll(run.Runs(), 0o777); err != nil {
		return nil, err
	}
	return l.deliveryLock(path)
}

// turn is the delivery lock for the repository and target, Python's turn_path: the landing line
// is named for it.
func (r *repoPlace) turn(upstream string) (string, error) {
	url, err := r.git().Try("remote", "get-url", "origin")
	return filepath.Join(run.Runs(), fmt.Sprintf(".merge-%x.lock", sha256.Sum256([]byte(RemoteKey(cmp.Or(url, r.repo))+"\n"+upstream)))), err
}

// RemoteKey is `host/owner/repo` for a clone URL however it spells the repository, Python's
// remote_key: no user, port, trailing `.git` or the case GitHub ignores.  A local path is itself.
func RemoteKey(url string) string {
	host, path := "", ""
	if parts := scpURL.FindStringSubmatch(url); parts != nil && !strings.HasPrefix(parts[2], "//") {
		host, path = parts[1], parts[2]
	} else if parsed, err := neturl.Parse(url); err == nil {
		host, path = parsed.Hostname(), parsed.Path
	}
	if host == "" {
		return url
	}
	return strings.ToLower(host + "/" + strings.TrimSuffix(strings.Trim(path, "/"), ".git"))
}

// forkAndPR pushes the branch to this account's fork and opens the PR upstream from there,
// Python's fork_and_pr: merging is the maintainer's decision now, so the run ends PASS, not
// merged, and not a failure.
func (r *repoPlace) forkAndPR(l *loop, target, repo, permission string) error {
	if err := r.requireReviewPass(l); err != nil {
		return err
	}
	l.say(fmt.Sprintf("--- merge: %s permission on %s; pushing to a fork", cmp.Or(permission, "no"), repo))
	remotes, err := r.git().Try("remote")
	if err != nil {
		return err
	}
	if !slices.Contains(strings.Fields(remotes), forkRemote) {
		// --remote-name keeps `origin` pointing upstream, which the diff and the PR are against;
		// an existing fork is reused, gh only adds the remote for it
		code, said, err := asked(r.wt, "repo", "fork", "--remote", "--remote-name", forkRemote)
		if err != nil {
			return err
		}
		if code != 0 {
			return r.note(l, "gh repo fork failed: "+tail(said, 400), true)
		}
	}
	code, out, err := r.git().Out("push", "--force-with-lease", "-u", forkRemote, r.branch)
	if err != nil {
		return err
	}
	if code != 0 {
		return r.note(l, fmt.Sprintf("pushing %s to the fork failed: %s", r.branch, tail(out, 400)), true)
	}
	l.say(fmt.Sprintf("--- merge: pushed %s to %s", r.branch, forkRemote))
	record, err := run.Read(l.dir)
	if record == nil {
		return cmp.Or(err, errors.New("run.json cannot be read"))
	}
	if record.Truthy("pr") {
		if ok, err := r.refreshPR(l, record); err != nil || !ok {
			return err
		}
		if err := l.save(func(record *run.Object) { record.Set("foreign", true) }); err != nil {
			return err
		}
		return r.note(l, "waiting for the maintainer", false)
	}
	code, me, err := asked(l.dir, "api", "user", "-q", ".login")
	if err != nil {
		return err
	}
	if lines := config.SplitLines(gitcall.Strip(me)); len(lines) > 0 {
		me = lines[len(lines)-1]
	}
	if code != 0 || me == "" {
		return r.note(l, "gh api user could not say whose fork this is: "+tail(me, 200), true)
	}
	path := filepath.Join(l.dir, "pr-body.md")
	if err := os.WriteFile(path, []byte(prBody(record)), 0o666); err != nil {
		return err
	}
	code, said, err := gh.Call(r.wt, "pr", "create", "--repo", repo, "--base", target, "--head", me+":"+r.branch,
		"--title", record.Str("title"), "--body-file", path)
	if err != nil {
		return err
	}
	url := prURL.FindString(said)
	if url == "" {
		if gh.Halted(code, said) {
			return &gitcall.Stopped{Why: said}
		}
		return r.note(l, fmt.Sprintf("gh pr create on %s failed: %s", repo, tail(said, 400)), true)
	}
	if err := l.save(func(record *run.Object) { run.SetAll(record, "pr", url, "foreign", true) }); err != nil {
		return err
	}
	open := ""
	if code != 0 {
		open = " (already open)"
	}
	l.say("--- merge: PR " + url + open)
	return r.note(l, "waiting for the maintainer", false)
}

// asked is gh's exit and what it said, Python's gitcall.gh, a gh that stopped raised.
func asked(dir string, args ...string) (int, string, error) {
	code, said, err := gh.Call(dir, args...)
	if err == nil && gh.Halted(code, said) {
		err = &gitcall.Stopped{Why: said}
	}
	return code, said, err
}
