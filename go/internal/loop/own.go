package loop

import (
	"cmp"
	"context"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"time"
	"unicode"

	"agentkit/internal/config"
	"agentkit/internal/gh"
	"agentkit/internal/gitcall"
	"agentkit/internal/handin"
	"agentkit/internal/history"
	"agentkit/internal/plan"
	"agentkit/internal/run"
	"agentkit/internal/seat"
	"agentkit/internal/size"
	"agentkit/internal/task"
)

// noWriter is why the review of a seat's own pull request whose writer cannot be named is refused:
// its reviewer's independence is judged against that model.
const noWriter = "no session record names the writer of this PR; review of the seat's own PR needs its orchestrator"

// deferredRun is what a round of a seat's own pull request says of the suite it leaves to landing.
const deferredRun = "(the repository suite runs once at landing; nothing was run in this review round)"

// An overtaken run ends `fail` on a changed fact, for its seat to decide, Python's pr_review_failed:
// the pull request closed, its head moved under a fix, or a head needs a round it no longer has.
type overtaken struct{ why string }

func (o *overtaken) Error() string { return o.why }

// ownPull is a seat's own pull request under review: judged as a task reviewer judges a task, its
// writer named in the task, its suite left to landing and only the project's rules checked.
type ownPull struct{ *pullPlace }

func (p *ownPull) role(word string) string { return word }

// landing is the task's own checks as it says them: a seat's own PR defers its suite to landing.
func (p *ownPull) landing() (bool, string) { return true, "" }

// beforeTurn sweeps nothing: Python's execute leaves a review's checkout as it is.
func (p *ownPull) beforeTurn(*loop) {}

// verify is the project's rules on the head, Python's review_pr_round for `is_own`: no suite stands
// in for the one landing runs.
func (p *ownPull) verify(l *loop, _ string) (bool, string, error) {
	head, tree, err := p.identity()
	if err != nil {
		return false, "", err
	}
	p.checked = [2]string{head, tree}
	said := noTestsRun
	if len(l.once) > 0 {
		said = deferredRun
	}
	l.say(said)
	failures, err := l.rulesOn(head, p.rulesCheck)
	if err != nil {
		return false, "", err
	}
	if failure := failures[0]; failure != "" {
		l.say(failure)
		return false, said + "\n\n" + failure, nil
	}
	p.untested = true
	return true, said, nil
}

// ownWriter is the model that wrote a seat's own pull request as its review captured it at launch,
// "" where the config no longer names it, Python's pr_writer.
func ownWriter(record *run.Object) string {
	name := record.Str("own_orchestrator")
	if _, err := config.ModelNamed(name); name == "" || err != nil {
		return ""
	}
	return name
}

// OwnRefusal is why a seat's own pull request may not have its review, settled before any reviewer
// is picked as Python's preflight settles it, "" for none: a writer no record names, a budget its
// runs spent, a base that is not origin's default branch, or a first review it may not have.
func OwnRefusal(dir string, pull *gh.Pull) (string, error) {
	record, err := run.Read(dir)
	if record == nil {
		return "", cmp.Or(err, errors.New("run.json cannot be read"))
	}
	if ownWriter(record) == "" {
		return noWriter, nil
	}
	if _, why, err := run.PullLeft(record, dir, 0, time.Now()); err != nil || why != "" {
		return why, err
	}
	l := &loop{ctx: context.Background(), dir: dir, id: filepath.Base(dir), pull: record.Str("review_pr")}
	repo, err := checkout(l, pull)
	if err != nil {
		return "", err
	}
	said, err := gitcall.Git{Repo: repo}.Must("ls-remote", "--symref", "origin", "HEAD")
	if err != nil {
		return "", err
	}
	ref, _, _ := strings.Cut(said, "\t")
	main, named := strings.CutPrefix(ref, "ref: refs/heads/")
	if !named {
		return "", fmt.Errorf("origin names no default branch for %s", repo)
	}
	if pull.Base != main {
		// it would land on its base: stacked on an unmerged change, never on the default branch
		return fmt.Sprintf("PR #%s is based on %s, not %s: ak lands a seat's own PR on %s only. If it builds on an unmerged change, wait for that to land, then rebase this branch onto origin/%s and point the PR at %s",
			pull.Number, pull.Base, main, main, main, main), nil
	}
	target, _, err := located(l, repo, pull)
	if err != nil {
		return "", err
	}
	if why := unanswered(repo, pull.Head); why != "" {
		return why, nil
	}
	return ownFirstReview(dir, repo, l.pull, pull.Number, target, pull.Head)
}

// ownFirstReview is why the first review of a seat's own pull request is refused, Python's
// own_pr_first_review, "" where it is not or none is ahead: once a review of it handed in a verdict,
// its later rounds review whatever the fix left.  The seat builds at most `orchestrator_lines` added
// lines, the moved ones and the files the target's tip marks generated aside, as Go's line counts
// read a task's change, and one that re-adds most of a budget-failed one's lines inherits its rounds.
func ownFirstReview(dir, repo, url, number, target, head string) (string, error) {
	if run.PullReviewed(url) {
		return "", nil
	}
	record, err := run.Read(dir)
	if record == nil {
		return "", cmp.Or(err, errors.New("run.json cannot be read"))
	}
	at := &repoPlace{wt: repo}
	numbers, err := run.Policy(record)
	if err != nil {
		return "", err
	}
	counted, over, err := size.Seat(at.git(), target, head, numbers.SeatLines)
	if err != nil {
		return "", err
	}
	if over {
		// a run with executors off is Python's (run.Carried), so a worker can always build it
		most, _ := numbers.SeatLines.Most()
		return fmt.Sprintf("PR #%s adds %d lines (generated files and unchanged moves aside): too big for the seat, which builds at most %d added lines. Write it as a task and launch it; a worker builds it",
			number, counted, most), nil
	}
	read, _, err := size.Reviewed(at.git(), target, head)
	if err != nil {
		return "", err
	}
	budget, err := run.PolicyRounds(record)
	if err != nil {
		return "", err
	}
	return at.replacement(dir, target, head, number, counted, budget, read)
}

// replacement is why a pull request's first review is refused as a replacement, Python's
// replacement_refusal, "" for none: more than half of the lines it adds that a reviewer reads and
// that hold a letter or digit were added by a pull request whose review failed at the budget, and it
// is no real split of that one: its counted lines are more than half of that one's.  A blank line or
// a lone brace, which any two changes share, charges nothing.
func (r *repoPlace) replacement(dir, base, head, number string, counted, budget int, read map[string]int) (string, error) {
	mine, written := map[string]int{}, 0
	for text, n := range read {
		if strings.IndexFunc(text, func(c rune) bool { return unicode.IsLetter(c) || unicode.IsNumber(c) }) >= 0 {
			mine[text], written = n, written+n
		}
	}
	worst, shared, worstLines := "", 0, 0
	for _, failed := range run.BudgetFailed(r.wt, budget, dir, time.Now()) {
		if written == 0 {
			break
		}
		held := true
		for _, sha := range failed[1:] {
			found, err := r.git().Try("rev-parse", "--verify", "--quiet", sha+"^{commit}")
			if err != nil {
				return "", err
			}
			held = held && found != "" // a pull request whose commits git no longer holds compares nothing
		}
		if !held {
			continue
		}
		theirs, _, err := size.Reviewed(r.git(), failed[1], failed[2])
		if err != nil {
			return "", err
		}
		common, total := 0, 0
		for text, n := range theirs {
			common, total = common+min(n, mine[text]), total+n
		}
		if common*2 > written && counted*2 > total && (worst == "" || common > shared) {
			worst, shared, worstLines = failed[0], common, total
		}
	}
	if worst == "" {
		return "", nil
	}
	return fmt.Sprintf("PR #%s re-adds %d of its %d lines holding a letter or digit from %s, whose review failed after %d rounds; a replacement inherits them: split it into parts under %d lines, or redesign it",
		number, shared, written, worst, budget, worstLines/2+1), nil
}

// reviewOwn is a seat's own pull request reviewed to its end, Python's review_pr for `is_own`: a
// round, and while one fails with rounds left, the fixer turn its findings get before the next.  A
// run woken in its landing line, taken up as Python's pr_loop takes it, lands what its lander
// checked, or has its red fixed as a failed round is.
func (l *loop) reviewOwn() (err error) {
	defer func() {
		// an ending of its own leaves no fix to wait for and no round pending
		if errors.As(err, new(*blocked)) || errors.As(err, new(*overtaken)) {
			if saved := l.save(func(record *run.Object) {
				record.Delete("own_pr_wait")
				record.Delete("own_pr_round_pending")
			}); saved != nil {
				err = saved
			}
		}
	}()
	record, err := read(l)
	if err != nil {
		return err
	}
	if landingLine(record) != "" {
		place := placeOf(record).(*ownPull)
		l.place, l.workspace = place, place.wt
		l.takeUp(record)
		if _, l.cmds, err = task.Read(record.Str("task")); err != nil {
			return err
		}
		if err := place.settle(l); err != nil {
			return err
		}
		if err := place.land(l); err != nil {
			return err
		}
	} else if err := l.ownRound(); err != nil {
		return err
	}
	for {
		record, err := read(l)
		if err != nil || !record.Truthy("own_pr_wait") {
			return err
		}
		if err := l.fixOwn(record); err != nil {
			return err
		}
		if err := l.ownRound(); err != nil {
			return err
		}
	}
}

// ownRound is one review of a seat's own pull request's head, Python's review_pr_round for
// `is_own`: the head a fix or the seat pushed is checked out, its first review held to the seat's
// size, its reviewer picked beside everyone who wrote it, and its verdict posted.
func (l *loop) ownRound() error {
	prior, err := read(l)
	if err != nil {
		return err
	}
	pull, err := gh.View(l.pull)
	if err != nil {
		return err
	}
	if pull.State != "OPEN" {
		return fmt.Errorf("%s is %s, not open", l.pull, pull.State)
	}
	writer := ownWriter(prior)
	if writer == "" {
		return errors.New(noWriter)
	}
	summaries := prior.List("round_summaries")
	budget, _, err := run.PullLeft(prior, l.dir, 0, time.Now())
	if err != nil {
		return err
	}
	landingFix, err := l.landingFixed(prior, pull.Head)
	if err != nil {
		return err
	}
	spent := len(summaries)
	if landingFix {
		spent = 0
	}
	_, why, err := run.PullLeft(prior, l.dir, spent, time.Now())
	switch {
	case err != nil:
		return err
	case why != "" && len(summaries) > 0 && prior.Str("head_sha") != pull.Head:
		// a head the seat pushed needs a round the pull request no longer has
		if err := l.save(func(record *run.Object) { record.Set("head_sha", pull.Head) }); err != nil {
			return err
		}
		return &overtaken{why}
	case why != "":
		return errors.New(why)
	}
	var last *run.Object
	if len(summaries) > 0 {
		last, _ = summaries[len(summaries)-1].(*run.Object)
	}
	advancing := (prior.Truthy("own_pr_wait") || last != nil && (last.Str("verdict") == "FAIL" || prior.Truthy("review_stale"))) &&
		prior.Str("head_sha") != pull.Head
	wt, branch := prior.Str("worktree"), prior.Str("branch")
	if wt != "" {
		at, err := gitcall.Git{Repo: wt}.Must("rev-parse", "HEAD")
		if err != nil {
			return err
		}
		// a reset to the new head may have finished, or the checkout stands on the fix it pushed
		moved := advancing && (at == pull.Head || at == prior.Str("head_sha") || at == prior.Str("delivery_sha"))
		if at != prior.Str("head_sha") && !moved || prior.Str("head_sha") != pull.Head && !advancing {
			return errors.New("the PR head or review checkout changed; existing work is kept for inspection")
		}
	}
	started := prior.Get("started_at")
	if !prior.Truthy("started_at") {
		started = clock()
	}
	head := pull.Head
	if advancing {
		head, l.reviewSession = prior.Str("head_sha"), "" // a new head is judged afresh
	}
	// on the record before fetch, checkout or provider work: the PR can move at any of those steps
	if err := l.save(func(record *run.Object) {
		run.SetAll(record, "run_id", l.id, "state", "running", "review_pr", l.pull, "head_sha", head, "own_pr", true,
			"own_orchestrator", writer, "own_orchestrator_effort", prior.Get("own_orchestrator_effort"), "started_at", started, "review_posted", false)
		if advancing {
			record.Set("review_session", nil)
		}
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
	owner := prior.Str("launched_session")
	// read before any checkout is made: a plan that refuses the review leaves nothing behind
	planned, err := planContext(owner)
	if err != nil {
		return err
	}
	if wt == "" {
		cut := &repoPlace{repo: repo}
		if err := cut.makeWorktree(l, "pr-"+pull.Number, pull.Head); err != nil {
			return err
		}
		wt, branch = cut.wt, cut.branch
	} else if advancing {
		if _, err := (gitcall.Git{Repo: wt}).Must("reset", "--hard", pull.Head); err != nil {
			return err
		}
	}
	var cmds []string
	if tests := cmp.Or(gitcall.DeclaredAt(wt, targetSHA, "tests"), gitcall.Declared(wt, "tests")); tests != "" {
		cmds = []string{tests + "  # once"}
	}
	title := fmt.Sprintf("Review PR #%s: %s", pull.Number, pull.Title)
	// what the seat wrote of its own PR stays on GitHub: its reviewer judges the diff against the
	// plan ak holds, never the author's account of its work
	body := fmt.Sprintf("# %s\n\n## Goal\nJudge %s by %s against this repository: its AGENTS.md, README, tests and conventions. "+
		"The %s seat's orchestrator %s wrote this diff; review it as that model's work.\n\n%s%s", title, l.pull, pull.Author, owner, writer, planned, doneWhenBlock(cmds))
	path := filepath.Join(l.dir, "task.md")
	if err := os.WriteFile(path, []byte(fmt.Sprintf("---\nrepo: %s\nrounds: %d\n---\n%s", repo, budget, body)), 0o666); err != nil {
		return err
	}
	_, declared, err := task.Read(path)
	if err != nil {
		return err
	}
	words, points := task.Size(body)
	rnd, turn := ownFix(prior)
	if err := l.save(func(record *run.Object) {
		run.SetAll(record, "title", title, "task", path, "repo", repo, "scratch", false, "pr", l.pull, "head_sha", pull.Head, "author", pull.Author,
			"base", "origin/"+pull.Base, "target", pull.Base, "base_sha", baseSHA, "target_sha", targetSHA, "branch", branch, "worktree", wt,
			"executor", prior.Get("executor"), "reviewer", nil, "rounds", budget, "verdict", nil, "finished_at", nil, "round_summaries", summaries,
			"findings", l.findings, "merge_method", "squash", "no_merge", repoFrom(prior).noMerge, "merged", false, "merge_note", nil, "reported", false,
			"task_words", words, "task_points", points, "task_checks", len(declared), "own_pr_round_pending", rnd)
		for _, key := range []string{"own_pr_wait", "delivery_sha", "review", "final_check"} {
			record.Delete(key) // this head is checked out and recorded; its review comes with this round
		}
	}); err != nil {
		return err
	}
	if err := seat.JoinProject(owner); err != nil { // a review is a launch too, and votes
		return err
	}
	record, err := read(l)
	if err != nil {
		return err
	}
	history.Start(record, l.say)
	place := placeOf(record).(*ownPull)
	l.place, l.workspace, l.title, l.budget, l.rnd, l.executor = place, wt, title, budget, rnd, record.Str("executor")
	l.usersAt, l.reviewLines = place.upstream(), numbersOf(record)
	l.say(fmt.Sprintf("worktree %s on %s: PR #%s by %s at %s, base origin/%s (%s)", wt, branch, pull.Number, pull.Author, pull.Head[:12], pull.Base, baseSHA[:12]))
	if err := place.settle(l); err != nil {
		return err
	}
	// preflight refused it before the launch; here again on the head checked out, which may have moved
	if why, err := ownFirstReview(l.dir, repo, l.pull, pull.Number, targetSHA, pull.Head); err != nil {
		return err
	} else if why = cmp.Or(unanswered(repo, pull.Head), why); why != "" {
		return &blocked{why, "## Blocked\n\n" + why}
	}
	l.cmds = cmds
	l.every, l.once = task.Group(cmds)
	l.body = body + place.rules()
	l.prompt = place.context(pull.Number, l.body) // what landing's fixers are told first
	if err := l.pickReviewer(fmt.Sprintf("own PR of the %s seat; picked against orchestrator %s", owner, writer)); err != nil {
		return err
	}
	if !prior.Truthy("reviewer") {
		l.sayLaunched() // the first pick starts the review
	}
	if err := os.MkdirAll(l.roundDir(), 0o777); err != nil {
		return err
	}
	ok, text, err := l.verify()
	if err != nil {
		return err
	}
	summary := fmt.Sprintf("PR #%s by %s: %s. %s wrote this; review its diff.", pull.Number, pull.Author, pull.Title, writer)
	if said := fixerWords(l.roundDir(), turn); said != "" {
		summary += "\n\n## What the fixer said\n" + said // for the record alone: the reviewer is never told it
	}
	preface := ""
	switch {
	case landingFix:
		preface = "Re-review after the landing fix.\n\n## The last round\n" + l.findings
		// a review the record keeps off its rounds (review)
		if err := l.save(func(record *run.Object) {
			record.Set("review_pending", run.Fields("round", rnd, "summary", summary, "record", false))
		}); err != nil {
			return err
		}
	case len(summaries) > 0:
		preface = "Re-review after a push.\n\n## The last round\n" + l.findings
	}
	if _, err := l.review(summary, ok, text, preface); err != nil {
		return err
	}
	return place.settled(l, pull)
}

// settled posts the round's verdict and decides what follows, Python's settle_pr_round for `is_own`:
// a PASS lands (land), or is the whole delivery of one launched with --no-merge; a FAIL, or a
// verdict GitHub never took for the head moved, waits for its fix while rounds are left.
func (p *ownPull) settled(l *loop, pull *gh.Pull) error {
	if err := p.restore(l, "reviewer"); err != nil {
		return err
	}
	record, err := read(l)
	if err != nil {
		return err
	}
	posted, why, err := p.post(l, pull, record)
	if err != nil {
		return err
	}
	if record, err = read(l); err != nil {
		return err
	}
	if !posted && !record.Truthy("review_stale") {
		reason := fmt.Sprintf("the review was not posted to %s: %s", p.url, why)
		l.say("ERROR " + reason)
		return errors.New(reason)
	}
	passed := record.Str("verdict") == "PASS" && posted
	if passed && !p.noMerge {
		return p.land(l)
	}
	again := !passed && l.rnd < l.budget
	if err := l.save(func(record *run.Object) {
		if passed && p.noMerge {
			record.Set("merge_note", "not merged: the review was launched with --no-merge")
		}
		if again {
			run.SetAll(record, "state", "running", "finished_at", nil, "own_pr_wait", p.sha)
			record.Delete("recovery_pending")
		}
		for _, key := range []string{"own_pr_round_pending", "landing_fix", "waiting_on"} {
			record.Delete(key)
		}
	}); err != nil {
		return err
	}
	if !again && !posted {
		return &overtaken{record.Str("review_error")}
	}
	return nil
}

// fixOwn is the fixer turn a FAIL on a seat's own pull request gets while rounds are left, Python's
// fix_own_pr: the findings go to the seat's orchestrator on the run's checkout of the reviewed head,
// and what it commits is pushed to the PR branch over that head for the next round to review.  A
// fixer that commits nothing leaves the head where it is, reviewed again with what it handed in.  A
// head the seat pushed before the fix started is what the next round reviews; one pushed while the
// fix was made, or a closed pull request, ends the run: a changed fact means a new review, never a
// fix pushed over somebody's commit.
func (l *loop) fixOwn(record *run.Object) error {
	reviewed, spent := record.Str("head_sha"), len(record.List("round_summaries"))
	rnd, turn := ownFix(record)
	l.rnd = rnd
	current, err := l.openPull()
	if err != nil {
		return err
	}
	place := l.place.(*ownPull)
	if err := place.offTheLine(record); err != nil {
		return err
	}
	if remote := current.Dict("head").Str("sha"); remote != reviewed {
		// the seat pushed since the review: that head is what the next round judges, if it has one
		_, why, err := run.PullLeft(record, l.dir, spent, time.Now())
		if err != nil {
			return err
		}
		if why != "" {
			return &overtaken{why}
		}
		l.say(fmt.Sprintf("the PR head moved to %s since the review; reviewing it", remote[:min(12, len(remote))]))
		return nil
	}
	// a fix to the orchestrator's PR is its work
	l.executor = record.Str("own_orchestrator")
	if err := l.save(func(record *run.Object) { record.Set("executor", l.executor) }); err != nil {
		return err
	}
	number := gh.PullURL.FindStringSubmatch(l.pull)[3]
	fixer := fmt.Sprintf("round %d/%d: fixer", l.rnd, l.budget)
	if record.Truthy("landing_fix") {
		fixer = "landing fixer"
	}
	l.say(fmt.Sprintf("--- %s %s (findings on PR #%s)", fixer, l.executor, number))
	_, named, _ := strings.Cut(record.Str("title"), ": ")
	said := current.Str("body")
	if said == "" {
		said = "(no description)"
	}
	fix := place.context(number, fmt.Sprintf("# Fix PR #%s: %s\n\n## Goal\nThe pull request passes its review: "+
		"fix each finding below with the least change, on this branch, and keep its checks passing.\n\n## The PR says\n%s\n\n%s%s\n\n## Reviewer findings to fix\n%s",
		number, named, strings.TrimFunc(said, config.Space), doneWhenBlock(l.cmds), place.rules(), withoutAsides(l.findings)))
	if err := os.MkdirAll(l.roundDir(), 0o777); err != nil {
		return err
	}
	// a landing's findings are no reviewer's hand-in
	handed := filepath.Join(filepath.Dir(l.findingsFile), "findings.json")
	if !exists(handed) {
		handed = ""
	}
	if _, err := l.execute("fixer", turn, fix, handed); err != nil {
		return err
	}
	if err := place.pin(l); err != nil { // what the next round judges
		return err
	}
	head, err := place.git().Must("rev-parse", "HEAD")
	if err != nil {
		return err
	}
	// the PR as it stands after the fix: a closed PR or a head pushed meanwhile ends the run, never
	// a review of what the fixer did not see
	if current, err = l.openPull(); err != nil {
		return err
	}
	remote := current.Dict("head")
	if remote.Str("sha") != reviewed {
		return &overtaken{"the PR head moved while the fix was made; review it with a new run"}
	}
	if head == reviewed {
		l.say("the fixer committed nothing; the next round reviews this head with what it handed in")
		return nil
	}
	// the push is written down before it is tried, so a resume pushes again instead of fixing twice
	if err := l.save(func(record *run.Object) { record.Set("delivery_sha", head) }); err != nil {
		return err
	}
	if err := place.pushPull(l, remote, reviewed); err != nil {
		return err
	}
	l.say(fmt.Sprintf("--- pushed the fix %s to %s", head[:12], remote.Str("ref")))
	return nil
}

// context is what a worker on the review's checkout is told first, Python's pr_context: where it
// is and on what branch.
func (p *ownPull) context(number, body string) string {
	return fmt.Sprintf("Repo checkout: %s\nBranch: %s (PR #%s head, based on origin/%s)\n\n%s", p.wt, p.branch, number, p.target, body)
}

// openPull is the pull request as GitHub has it now, its head as git has it, while it is open.
func (l *loop) openPull() (*run.Object, error) {
	current, err := prHead(l.dir, l.pull)
	if err != nil {
		return nil, err
	}
	if state := current.Str("state"); state != "open" {
		return nil, &overtaken{fmt.Sprintf("%s is %s, not open", l.pull, cmp.Or(state, "?"))}
	}
	return current, nil
}

// planContext is the seat's open plan lines, for the review of its own pull request, Python's
// plan_context: the outcomes the user agreed to, each with the check that proves it.
func planContext(seat string) (string, error) {
	if seat == "" {
		return "", nil
	}
	lines, err := plan.Open(seat)
	if err != nil || len(lines) == 0 {
		return "", err
	}
	return "## The plan this PR serves\nThe session's open plan lines, the outcomes the user agreed to, each naming the project it is on:\n" +
		strings.Join(lines, "\n") + "\nAn outcome on this repository that this PR claims to deliver but misses is a finding whose proof is that line's check, run with `--run`.\n\n", nil
}

// fixerWords is what the round's fixer turn of that name said, for the record of the head it left,
// Python's fixer_words: its answer, and the reason of a not-needed it handed in; "" without a turn.
func fixerWords(round, fixer string) string {
	name := newest(round, roleDirs(round, func(entry fs.DirEntry) bool {
		return strings.HasPrefix(entry.Name(), fixer) && workerName.MatchString(entry.Name())
	}))
	if name == "" {
		return ""
	}
	turn := latestTurn(round, name)
	words := handin.Answer(filepath.Join(turn, "final.md"))
	if submitted, _ := handin.Read(filepath.Join(turn, handin.File)); submitted != nil && submitted.Closing() != nil &&
		submitted.Closing().Str("kind") == "not-needed" {
		words += "\n\nNot needed: " + submitted.Closing().Str("why")
	}
	return strings.TrimFunc(words, config.Space)
}

// doneWhenBlock is the `## Done when` section a pull request review's task and its fixer's share,
// Python's done_when_block: the checks it runs, a stand-in where the repository declares none.
func doneWhenBlock(cmds []string) string {
	check := noTestsCheck
	if len(cmds) > 0 {
		check = cmds[0]
	}
	return "## Done when\n```bash\n" + check + "\n```\n"
}
