package loop

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

const sameFailure = "the same checks fail the same way after a fix round: the task or its checks are wrong"

var (
	// checkRecord opens a command's record in a done-when log; a marker counts only there.
	checkRecord = regexp.MustCompile(`^\$ ([^\n]*)\n\[([^\]\n]*)\]`)
	// loopNote is what the loop itself adds to a done-when log, none of it a command's output, and
	// reading one as such would make a failure that never moved look new every round.
	loopNote = regexp.MustCompile(`^(?:Checkout changed during |done-when: stopped after |outside files: |AGENTS\.md (?:is|could not be read|must not|front matter has) )`)
)

// roundDir is the directory of the round under way.
func (l *loop) roundDir() string {
	return filepath.Join(l.dir, fmt.Sprintf("round-%d", l.rnd))
}

// rounds is executor, checks and reviewer until a PASS or the budget is spent, Python's rounds:
// whether the last review passed.
func (l *loop) rounds() (bool, error) {
	if record, _ := run.Read(l.dir); record != nil {
		if landingLine(record) != "" || l.prior && run.ReviewPass(record, run.Models()) && savedIntegrationPass(record) {
			return true, nil // a saved PASS resumes delivery, never a task round
		}
		if r, landing := l.place.(*repoPlace); landing && l.prior && landingReview(record) {
			return l.landAgain(r)
		}
	}
	if l.prior {
		if passed, err := l.resumeReview(); err != nil || passed {
			return passed, err
		}
	}
	for l.rnd < l.budget {
		if err := l.allowed(); err != nil {
			return false, err
		}
		l.rnd++
		if passed, err := l.round(); err != nil || passed {
			return passed, err
		}
	}
	return false, nil
}

// allowed ends the run blocked once its change has no round left across its runs, Python's
// round_allowed: the task is what changes then, split or redesigned, and nothing a resume could spend.
func (l *loop) allowed() error {
	record, err := run.Read(l.dir)
	if record == nil {
		return err
	}
	left, why, err := run.ChangeLeft(record, l.dir, l.budget, l.rnd, time.Now())
	if err != nil {
		return err
	}
	if left < 1 {
		return &blocked{why, "## Blocked\n\n" + why}
	}
	return nil
}

// round is one round from its turn to its verdict: round 1 builds, a later one fixes what the last
// review found, in the executor's own conversation.
func (l *loop) round() (bool, error) {
	summary, err := l.firstTurn()
	if err != nil {
		return false, err
	}
	ok, text, err := l.verify()
	if err != nil {
		return false, err
	}
	if ok {
		l.say("done-when: all passed")
	} else {
		l.say("done-when: FAILED")
		l.say(fmt.Sprintf("--- round %d: fixer %s (done-when failed)", l.rnd, l.executor))
		fixed, err := l.execute("fixer", "fixer", l.checksFailed(text), "")
		if err != nil {
			return false, err
		}
		summary += "\n\n### After done-when fix\n" + fixed
		if ok, text, err = l.verify(); err != nil {
			return false, err
		}
		if ok {
			l.say("done-when after fix: all passed")
		} else {
			l.say("done-when after fix: still FAILING")
		}
	}
	if err := l.sameFailure(ok, text, true); err != nil {
		return false, err
	}
	if err := l.place.beforeReview(l); err != nil {
		return false, err
	}
	preface := ""
	if l.rnd > 1 {
		preface = "Re-review after fixes."
	}
	return l.review(summary, ok, text, preface)
}

// checksFailed is what a fixer is told of the checks' output.
func (l *loop) checksFailed(text string) string {
	return l.prompt + "\n\n## The done-when commands failed. Fix the root cause.\n```\n" + text + "\n```"
}

// firstTurn is the round's opening turn: a fixer a host cut off goes on first, on what it was told,
// and a turn that answered already is not taken again.
func (l *loop) firstTurn() (string, error) {
	if name, _, _ := openWorker(l.roundDir()); name != "" && name != "executor" {
		l.say(fmt.Sprintf("--- round %d/%d: continuing %s", l.rnd, l.budget, name))
		checked, _ := os.ReadFile(filepath.Join(l.roundDir(), "donewhen.log"))
		return l.execute("fixer", name, l.checksFailed(string(checked)), "")
	}
	if out := answered(l.roundDir()); out != "" {
		return l.goOnAnswered(out)
	}
	l.say(fmt.Sprintf("--- round %d/%d: executor %s", l.rnd, l.budget, l.executor))
	if l.rnd > 1 {
		return l.execute("fixer", "executor", l.prompt+"\n\n## Reviewer findings to fix\n"+withoutAsides(l.findings),
			filepath.Join(filepath.Dir(l.findingsFile), "findings.json"))
	}
	summary, err := l.execute("executor", "executor", l.prompt, "")
	if err != nil {
		return "", err
	}
	// a change past the ceiling is refused now, before its checks and their fixer
	return summary, l.place.worked(l)
}

// sameFailure records what the round's checks left failing, and ends the run blocked where a fix
// round changed neither which fail nor what they say, Python's same_failure: a third attempt would
// buy the same answer.  A first sight is only recorded, and a pass records no failure.  A resume
// only records, not knowing whether a fixer came before: compare is off.
func (l *loop) sameFailure(ok bool, text string, compare bool) error {
	failure := []any{}
	if !ok {
		failure = failingChecks(text)
	}
	var before []any
	var seen bool
	if err := l.save(func(record *run.Object) {
		history := record.Dict("done_when_failure")
		if history == nil {
			history = run.NewObject()
		}
		before, seen = history.List("every"), history.Has("every")
		history.Set("every", failure)
		record.Set("done_when_failure", history)
	}); err != nil {
		return err
	}
	if !compare || !seen || len(failure) == 0 || !run.Equal(before, failure) {
		return nil
	}
	listed := make([]string, len(failure))
	for i, each := range failure {
		listed[i] = checkLine(each)
	}
	return &blocked{sameFailure, "## Blocked\n\n" + sameFailure + "\n\nThe checks that failed identically twice:\n\n- " + strings.Join(listed, "\n- ")}
}

// checkLine is a failed check as a person reads it, Python's `cmd` — line.
func checkLine(check any) string {
	pair, _ := check.([]any)
	if len(pair) != 2 {
		return ""
	}
	if said := run.Text(pair[1]); said != "" {
		return "`" + run.Text(pair[0]) + "` — " + said
	}
	return "`" + run.Text(pair[0]) + "`"
}

// failingChecks is which commands failed and the last line each printed, Python's failing_checks:
// earlier lines carry run numbers, temporary paths and timings that differ every round, and the
// last is what stays still unless something about the failure moved.
func failingChecks(text string) []any {
	found := []any{}
	failing := -1
	for _, record := range strings.Split(text, "\n\n") {
		if strings.HasPrefix(record, "flaky: ") {
			continue
		}
		if mark := checkRecord.FindStringSubmatch(record); mark != nil {
			failing = -1
			if mark[2] != "exit 0" {
				failing = len(found)
				found = append(found, []any{mark[1], ""})
			}
			record = record[len(mark[0]):]
		}
		if failing < 0 || loopNote.MatchString(strings.TrimLeftFunc(record, config.Space)) {
			continue
		}
		// a blank line in a command's own output split it: the parts are all that command's
		for _, line := range config.SplitLines(record) {
			if line = strings.TrimFunc(line, config.Space); line != "" {
				found[failing].([]any)[1] = line
			}
		}
	}
	return found
}

// doneWhenCounts is how many commands exited 0 of how many ran, Python's done_when_counts: what a
// command printed never establishes provenance, so records of one command that disagree count it
// failed.
func doneWhenCounts(text string, cmds []string) (passed, total int) {
	hits := map[string][]bool{}
	for _, record := range strings.Split(text, "\n\n") {
		if mark := checkRecord.FindStringSubmatch(record); mark != nil {
			hits[mark[1]] = append(hits[mark[1]], mark[2] == "exit 0")
		}
	}
	totals := map[string]int{}
	for _, cmd := range cmds {
		totals[cmd]++
	}
	used := map[string]int{}
	for _, cmd := range cmds {
		outcomes, at := hits[cmd], used[cmd]
		used[cmd]++
		switch {
		case len(outcomes) == totals[cmd], len(outcomes) < totals[cmd] && at < len(outcomes):
			total++
			if outcomes[at] {
				passed++
			}
		case len(outcomes) > totals[cmd]:
			total++
			all := true
			for _, each := range outcomes {
				all = all && each
			}
			if all {
				passed++
			}
		}
	}
	return passed, total
}
