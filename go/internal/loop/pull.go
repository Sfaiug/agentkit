package loop

import (
	"cmp"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/gh"
	"agentkit/internal/gitcall"
	"agentkit/internal/run"
	"agentkit/internal/seat"
	"agentkit/internal/task"
	"agentkit/internal/usage"
)

const (
	// noTestsCheck is what a review's task.md holds as its one check where the repository declares none.
	noTestsCheck = "true   # AGENTS.md declares no tests:"
	noTestsRun   = "(AGENTS.md declares no `tests:` command; nothing was run)"
	// githubBodyCap is below GitHub's 65,536-character body limit, UTF-8 included.
	githubBodyCap = 60_000
	// githubRetries is how often GitHub's own refusal is waited out and tried again: a pull ref it
	// has not published yet, a push or a merge it refused for a reason of its own.
	githubRetries = 3
)

// pullPlace is a review of somebody else's pull request: its head checked out for the run, judged by
// the reviewer alone, and the verdict posted back on the commit it judged.  It has no executor stage.
type pullPlace struct {
	*repoPlace
	url, sha string
	untested bool // no `tests:` line ran and no rule failed: the review's done_when is null
}

func pullFrom(record *run.Object) *pullPlace {
	return &pullPlace{repoPlace: repoFrom(record), url: record.Str("review_pr"), sha: record.Str("head_sha")}
}

// checkout is the repository's checkout here, cloned under ~/code if there is none yet, Python's
// checkout_for.
func checkout(l *loop, pull *gh.Pull) (string, error) {
	slug := pull.Owner + "/" + pull.Name
	if found := seat.CheckoutFor(slug); found != "" {
		return found, nil
	}
	code := filepath.Join(filepath.Dir(config.Home()), "code")
	target := filepath.Join(code, pull.Name)
	if exists(target) {
		return "", fmt.Errorf("%s exists and is not a clone of %s", target, slug)
	}
	if err := os.MkdirAll(code, 0o700); err != nil {
		return "", err
	}
	l.say(fmt.Sprintf("cloning %s into %s", slug, target))
	exit, said, err := gh.Call(code, "repo", "clone", slug, target, "--", "-q")
	if err != nil {
		return "", err
	}
	if exit != 0 {
		return "", fmt.Errorf("gh repo clone %s failed: %s", slug, tail(said, 400))
	}
	return target, nil
}

// tail is the last of text, at most that many characters.
func tail(text string, most int) string {
	runes := []rune(text)
	return string(runes[max(0, len(runes)-most):])
}

// fetchPull fetches the pull ref and the base, Python's fetch_pr: GitHub can publish a PR before its
// pull ref, so that alone is waited for.
func fetchPull(l *loop, repo string, pull *gh.Pull) error {
	ref := "pull/" + pull.Number + "/head"
	for tried := 0; ; tried++ {
		code, said, err := gitcall.Git{Repo: repo}.Fetch("origin", ref, pull.Base)
		if err != nil || code == 0 {
			return err
		}
		if said != "fatal: couldn't find remote ref "+ref || tried == githubRetries {
			return fmt.Errorf("git fetch origin %s %s failed in %s: %s", ref, pull.Base, repo, said)
		}
		delay := transientDelay(tried + 1)
		l.say(fmt.Sprintf("WARN GitHub has not published %s; fetching again in %ds (%d/%d)", ref, int(delay.Seconds()), tried+1, githubRetries))
		select {
		case <-l.ctx.Done():
			return l.ctx.Err()
		case <-time.After(delay):
		}
	}
}

// located is the pull request fetched into repo: its target's tip, and where its head left that.
func located(l *loop, repo string, pull *gh.Pull) (targetSHA, baseSHA string, err error) {
	if err := fetchPull(l, repo, pull); err != nil {
		return "", "", err
	}
	g := gitcall.Git{Repo: repo}
	if _, err := g.Must("rev-parse", "--verify", "--quiet", pull.Head+"^{commit}"); err != nil {
		return "", "", err
	}
	if targetSHA, err = g.Must("rev-parse", "origin/"+pull.Base+"^{commit}"); err != nil {
		return "", "", err
	}
	baseSHA, err = g.Must("merge-base", targetSHA, pull.Head)
	return targetSHA, baseSHA, err
}

// reviewPull is the review of the pull request the record names, Python's review_pr_round.
func (l *loop) reviewPull() error {
	record, err := run.Read(l.dir)
	if record == nil {
		return cmp.Or(err, errors.New("run.json cannot be read"))
	}
	pull, err := gh.View(l.pull)
	if err != nil {
		return err
	}
	if pull.State != "OPEN" {
		return fmt.Errorf("%s is %s, not open", l.pull, pull.State)
	}
	wt, branch := record.Str("worktree"), record.Str("branch")
	if wt != "" {
		at, err := gitcall.Git{Repo: wt}.Must("rev-parse", "HEAD")
		if err != nil {
			return err
		}
		if at != record.Str("head_sha") || at != pull.Head {
			return errors.New("the PR head or review checkout changed; existing work is kept for inspection")
		}
	}
	started := record.Get("started_at")
	if !record.Truthy("started_at") {
		started = clock()
	}
	// on the record before fetch, checkout or provider work: the PR can move at any of those steps
	if err := l.save(func(record *run.Object) {
		run.SetAll(record, "run_id", l.id, "state", "running", "launched_session", nil, "review_pr", l.pull, "head_sha", pull.Head,
			"own_pr", false, "own_orchestrator", nil, "own_orchestrator_effort", nil, "started_at", started, "review_posted", false)
	}); err != nil {
		return err
	}
	repo, err := checkout(l, pull)
	if err != nil {
		return err
	}
	targetSHA, baseSHA, err := located(l, repo, pull)
	if err != nil {
		return err
	}
	if wt == "" {
		cut := &repoPlace{repo: repo}
		if err := cut.makeWorktree(l, "pr-"+pull.Number, pull.Head); err != nil {
			return err
		}
		wt, branch = cut.wt, cut.branch
	}
	// the target's line, which a PR cannot loosen; else the checkout's
	tests := gitcall.Suite(wt, targetSHA)
	body, title := pullTask(l.pull, pull, tests)
	path := filepath.Join(l.dir, "task.md")
	if err := os.WriteFile(path, []byte(fmt.Sprintf("---\nrepo: %s\nrounds: 1\n---\n%s", repo, body)), 0o666); err != nil {
		return err
	}
	_, declared, err := task.Read(path)
	if err != nil {
		return err
	}
	words, points := task.Size(body)
	if err := l.save(func(record *run.Object) {
		run.SetAll(record, "title", title, "task", path, "repo", repo, "scratch", false, "pr", l.pull, "author", pull.Author,
			"base", "origin/"+pull.Base, "target", pull.Base, "base_sha", baseSHA, "target_sha", targetSHA, "branch", branch,
			"worktree", wt, "executor", nil, "exec_session", nil, "reviewer", nil, "rounds", 1, "verdict", nil, "finished_at", nil,
			"round_summaries", []any{}, "findings", "", "merge_method", "squash", "no_merge", true, "merged", false,
			"merge_note", nil, "reported", false, "task_words", words, "task_points", points, "task_checks", len(declared))
		record.Delete("review")
	}); err != nil {
		return err
	}
	if record, err = run.Read(l.dir); record == nil {
		return cmp.Or(err, errors.New("run.json cannot be read"))
	}
	place := pullFrom(record)
	l.place, l.workspace, l.title, l.budget, l.rnd = place, wt, title, 1, 1
	l.usersAt, l.reviewLines = place.upstream(), numbersOf(record)
	l.say(fmt.Sprintf("worktree %s on %s: PR #%s by %s at %s, base origin/%s (%s)", wt, branch, pull.Number, pull.Author, pull.Head[:12], pull.Base, baseSHA[:12]))
	if err := place.settle(l); err != nil {
		return err
	}
	if tests != "" {
		l.cmds = []string{tests}
		l.every, l.once = task.Group(l.cmds)
	}
	l.body = body + place.rules()
	if err := l.pickReviewer("no executor: this is a review of somebody else's PR"); err != nil {
		return err
	}
	if err := os.MkdirAll(l.roundDir(), 0o777); err != nil {
		return err
	}
	ok, text, err := l.verify()
	if err != nil {
		return err
	}
	summary := fmt.Sprintf("PR #%s by %s: %s. agentkit executed nothing; review the author's diff.", pull.Number, pull.Author, pull.Title)
	if _, err := l.review(summary, ok, text, ""); err != nil {
		return err
	}
	return place.settleVerdict(l, pull)
}

// pullTask is what a review of somebody else's PR is told to do: its task's body, and its title.
func pullTask(url string, pull *gh.Pull, tests string) (string, string) {
	title := fmt.Sprintf("Review PR #%s: %s", pull.Number, pull.Title)
	said := strings.TrimFunc(pull.Body, config.Space)
	if said == "" {
		said = "(no description)"
	}
	var cmds []string
	if tests != "" {
		cmds = []string{tests}
	}
	return fmt.Sprintf("# %s\n\n## Goal\nJudge %s by %s against this repository: its AGENTS.md, README, tests and conventions. "+
		"Nobody from agentkit executed anything here; the diff is the author's, and the PR states its intent.\n\n"+
		"## The PR says\n%s\n\n%s", title, url, pull.Author, said, doneWhenBlock(cmds)), title
}

// pickReviewer picks who judges the head, saying why it is the one: the first of the run's
// reviewers with room, beside everyone who wrote part of it (headWriters).
func (l *loop) pickReviewer(why string) error {
	record, err := read(l)
	if err != nil {
		return err
	}
	rules, ok := l.rules()
	if !ok {
		return notYet("the models cannot be picked here", "a pick Python makes")
	}
	readings, err := usage.Read()
	if err != nil {
		return notYet("the meters cannot be read: "+err.Error(), "a pick without them")
	}
	order := rules.Beside(ready{readings, unable()}, headWriters(record), rawLog{l.dir})
	if len(order) == 0 {
		return notYet("no reviewer can run now", "an exhausted run")
	}
	l.reviewer = order[0]
	if err := l.save(func(record *run.Object) { record.Set("reviewer", l.reviewer) }); err != nil {
		return err
	}
	l.say(fmt.Sprintf("reviewer=%s (%s)", l.reviewer, why))
	return nil
}

// role is the reviewer's own rules: only a reviewer turns here.
func (p *pullPlace) role(string) string { return "reviewer-pr" }

// verify is the tests line on the PR's head, Python's verify_work for a review: nothing of the
// author's is committed, and a test that rewrites a tracked file is undone before the review.
func (p *pullPlace) verify(l *loop, path string) (bool, string, error) {
	if err := p.followTarget(l); err != nil {
		return false, "", err
	}
	head, tree, err := p.identity()
	if err != nil {
		return false, "", err
	}
	p.checked = [2]string{head, tree}
	rules, err := p.rulesCheck()
	if err != nil {
		return false, "", err
	}
	if len(l.cmds) == 0 {
		l.say(noTestsRun)
		if rules != "" {
			l.say(rules)
			return false, noTestsRun + "\n\n" + rules, nil
		}
		p.untested = true
		return true, noTestsRun, nil
	}
	ok, text, _, err := l.checksIn(p.wt, l.every, path)
	if err != nil {
		return false, "", err
	}
	if rules != "" {
		ok, text = false, text+"\n\n"+rules
	}
	said := "FAILED"
	if ok {
		said = "passed"
	}
	l.say(fmt.Sprintf("tests (%s): %s", l.cmds[0], said))
	text = fmt.Sprintf("Commit: %s\nTree: %s\n\n%s", head, tree, text)
	return ok, text, os.WriteFile(path, []byte(text), 0o666)
}

// view is the diff of the PR's head, once what the tests rewrote is undone.
func (p *pullPlace) view(l *loop, j *judging, passed, total int) (string, string, string, error) {
	if err := p.restore(l, "tests"); err != nil {
		return "", "", "", err
	}
	return p.viewOf(l, j, passed, total)
}

// restore puts the checkout back on the PR's head, keeping what that stage changed, Python's
// restore_review_checkout.
func (p *pullPlace) restore(l *loop, stage string) error {
	g := p.git()
	at, err := g.Must("rev-parse", "HEAD")
	if err != nil {
		return err
	}
	if at != p.sha {
		return fmt.Errorf("review checkout HEAD changed during %s; cannot review the pinned PR head", stage)
	}
	code, why, err := g.Out("diff", "--quiet", p.sha)
	if err != nil {
		return err
	}
	switch code {
	case 0:
		return nil
	case 1:
	default:
		return fmt.Errorf("cannot inspect the review checkout after %s: %s", stage, why)
	}
	patch, err := p.raw("diff", "--binary", p.sha)
	if err != nil {
		return err
	}
	saved := filepath.Join(l.dir, stage+"-changes.patch")
	if err := os.WriteFile(saved, []byte(patch), 0o666); err != nil {
		return err
	}
	if _, err := g.Must("restore", "--source="+p.sha, "--staged", "--worktree", "--", "."); err != nil {
		return err
	}
	l.say(fmt.Sprintf("WARN %s changed tracked files; saved %s and restored the PR head", stage, saved))
	return nil
}

// judged is the repository's, with a review that ran no tests recorded as having none to pass.
func (p *pullPlace) judged(l *loop, verdict string) (string, []any, error) {
	verdict, evidence, err := p.repoPlace.judged(l, verdict)
	if p.untested {
		evidence = append(evidence, "done_when", nil)
	}
	return verdict, evidence, err
}

// settleVerdict posts the recorded verdict and offers a passed PR, Python's settle_pr_round: a
// verdict nobody can read on GitHub is no review, so that run ends in error and nothing is offered.
func (p *pullPlace) settleVerdict(l *loop, pull *gh.Pull) error {
	if err := p.restore(l, "reviewer"); err != nil {
		return err
	}
	record, err := run.Read(l.dir)
	if record == nil {
		return cmp.Or(err, errors.New("run.json cannot be read"))
	}
	posted, why, err := p.post(l, pull, record)
	if err != nil {
		return err
	}
	if !posted {
		reason := fmt.Sprintf("the review was not posted to %s: %s", p.url, why)
		l.say("ERROR " + reason)
		return errors.New(reason)
	}
	if record.Str("verdict") != "PASS" {
		return nil
	}
	return p.offer(l, pull)
}

// post is the findings as a GitHub review on the commit judged, Python's post_review: whether
// GitHub took it, and why not.  A PR by the account ak posts with always comments: GitHub rejects a
// changes-requested review from the PR's author, which would turn a FAIL into an error.
func (p *pullPlace) post(l *loop, pull *gh.Pull, record *run.Object) (bool, string, error) {
	unposted := func(why string) (bool, string, error) {
		return false, why, l.save(func(record *run.Object) { run.SetAll(record, "review_posted", false, "review_error", why) })
	}
	if err := l.save(func(record *run.Object) {
		record.Set("review_posted", false)
		record.Delete("review_stale")
		record.Delete("review_error")
	}); err != nil {
		return false, "", err
	}
	current, err := gh.View(p.url)
	if errors.Is(err, gh.ErrPython) {
		return false, "", err
	}
	if err != nil {
		return unposted("cannot verify the PR head: " + err.Error())
	}
	if current.Head != p.sha || current.State != "OPEN" {
		why := "PR head changed or closed; discarded review"
		if !record.Truthy("own_pr") {
			why += "; watcher will re-queue" // the watcher queues somebody else's PR again; a seat's own is its seat's
		}
		l.say("WARN " + why)
		if err := l.save(func(record *run.Object) { record.Set("review_stale", true) }); err != nil {
			return false, "", err
		}
		return unposted(why)
	}
	opening := fmt.Sprintf("agentkit review of %s by %s (run %s)\n\n", p.sha[:12], l.reviewer, l.id)
	path := filepath.Join(l.dir, "review.md")
	if err := os.WriteFile(path, []byte(githubBody(opening+overriddenSection(record)+strings.TrimFunc(l.findings, config.Space)+"\n", l.id)), 0o666); err != nil {
		return false, "", err
	}
	how := "REQUEST_CHANGES"
	if record.Str("verdict") == "PASS" || gh.ByViewer(pull.Author) {
		how = "COMMENT"
	}
	code, said, err := gh.Call(l.dir, "api", pull.API()+"/pulls/"+pull.Number+"/reviews", "--method", "POST",
		"-f", "commit_id="+p.sha, "-f", "event="+how, "-F", "body=@"+path)
	if err != nil {
		return false, "", err
	}
	if code != 0 {
		l.say(fmt.Sprintf("WARN could not post the review to %s: %s", p.url, tail(said, 300)))
		return unposted(fmt.Sprintf("gh api review %s exited %d: %s", how, code, tail(said, 300)))
	}
	l.say(fmt.Sprintf("--- review posted to %s (%s)", p.url, how))
	return true, "", l.save(func(record *run.Object) { record.Set("review_posted", true) })
}

// overriddenSection is why the loop failed what the reviewer passed: it lives in the round's review
// record, never in the reviewer's text, whose kept tail a long report would push it out of.
func overriddenSection(record *run.Object) string {
	if review := record.Dict("review"); review != nil && review.Truthy("overridden") {
		return "## Overridden to FAIL\n" + review.Str("overridden") + "\n\n"
	}
	return ""
}

// githubBody keeps a body within GitHub's limit; the run keeps the complete records.
func githubBody(text, id string) string {
	if len(text) <= githubBodyCap {
		return text
	}
	note := "\n\n[body truncated; complete findings and summaries are in agentkit run " + id + "]\n"
	return strings.ToValidUTF8(text[:githubBodyCap-len(note)], "") + note
}

// offer is a posted PASS put to the inbox, once its required checks are green on the same open head.
// A question that did not go out stays on the record for the tick to ask again (`offer_endings`).
func (p *pullPlace) offer(l *loop, pull *gh.Pull) error {
	green, why, err := requiredChecks(l, pull, p.target, p.sha, false)
	if err != nil {
		return err
	}
	current, err := gh.View(p.url)
	if errors.Is(err, gh.ErrPython) {
		return err
	}
	if green && (err != nil || current.Head != p.sha || current.State != "OPEN") {
		green, why = false, "the PR head changed, closed, or could not be verified after the checks"
	}
	if !green {
		note := "not offered for merge: " + why
		l.say("WARN " + note)
		return l.save(func(record *run.Object) { record.Set("merge_note", note) })
	}
	question := fmt.Sprintf("PR #%s by %s: %s. Merge? yes/no", pull.Number, pull.Author, pull.Title)
	pending := run.Fields("question", question, "url", p.url, "sha", p.sha, "asked", false)
	if sent, _ := seat.AskInbox(question, p.url, p.sha, false, func() { pending.Set("asked", true) }, l.say, stampedLog{l.dir}); sent {
		return l.save(func(record *run.Object) {
			record.Set("merge_note", "offered to the "+config.Inbox()+" session at "+p.sha[:12])
		})
	}
	return l.save(func(record *run.Object) {
		run.SetAll(record, "merge_note", "merge question requires retry", "pending_inbox", pending)
	})
}

// declaredChecks is what a result lists of a review's task: a repository that declares no `tests:`
// has its task's stand-in for a check, which nothing ran.
func declaredChecks(record *run.Object, cmds []string) []string {
	if record.Truthy("review_pr") && slices.Equal(cmds, []string{noTestsCheck}) {
		return []string{"(none declared)"}
	}
	return cmds
}
