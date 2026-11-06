package loop

import (
	"errors"
	"fmt"
	"os"
	"strings"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// fixLanding is a woken run taking its lander's red, Python's land_from_line past green: the work
// already passed review, and what fails this late is as often the world as the work, so the run
// does not end FAIL.  It takes the target's tip in, its executor gets one fixer turn on the failing
// output, spending no round, a fresh review judges the fixed work, and the run rejoins its line,
// whose lander checks the fixed tree. A red after that turn, helper work and a PR's red are Python's;
// a stack red wakes once the runs ahead have left the line (wakes.go).
func (r *repoPlace) fixLanding(l *loop, upstream string, record, wait *run.Object) error {
	fix := wait.Dict("fix")
	failed := fmt.Sprintf("its landing failed: %s; see %s", fix.Str("line"), fix.Str("log"))
	if road := landingFixHandoff(record); road != "" {
		return notYet(failed, road)
	}
	// a conflict with the target is the world moving: it never spends the budget of the work's own reds
	count := "landing_reds"
	if fix.Truthy("conflict") {
		count = "landing_conflicts"
	}
	spent, _ := record.Int(count)
	if !wait.Truthy("fixing") {
		spent++
	}
	if spent > 1 {
		return notYet(failed, "a landing red after its fixer turn")
	}
	if !wait.Truthy("fixing") {
		patch, red, err := r.redPatch(record, fix)
		if err != nil {
			return err
		}
		if err := l.save(func(record *run.Object) {
			record.Set(count, spent)
			if red {
				record.Set("landing_red_patches", append(record.List("landing_red_patches"), patch))
			}
			record.Dict("waiting_on").Set("fixing", true)
		}); err != nil {
			return err
		}
	}
	if integrated, err := r.integrate(l, upstream); err != nil || !integrated {
		if err != nil {
			return err
		}
		if current, _ := run.Read(l.dir); current != nil && current.Truthy("merge_failed") {
			return errors.New(current.Str("merge_note"))
		}
		return l.save(func(record *run.Object) { record.Set("state", "running"); record.Delete("waiting_on") })
	}
	// a fixer that already ran leaves the rest to the line, as one that crashed after it does
	if !wait.Truthy("fixed") {
		output, err := os.ReadFile(fix.Str("log"))
		if err != nil {
			return err
		}
		if passed, err := r.fixFinalCheck(l, decoded(output)); err != nil {
			return err
		} else if !passed {
			return l.save(func(record *run.Object) { record.Delete("waiting_on") })
		}
	}
	return r.rejoinLine(l, wait, "landing fixes passed review")
}

// fixFinalCheck is one fixer turn on the failing landing output and a review of what it made,
// Python's fix_final_check and landing_fixer: neither records a task round.  Whether that review
// passed; a run in its line has no fixer round after a failed one.
func (r *repoPlace) fixFinalCheck(l *loop, text string) (bool, error) {
	shown, err := failingBlocks(text, l.dir)
	if err != nil {
		return false, err
	}
	const again = "Re-review after the final check."
	if err := l.save(func(record *run.Object) {
		record.Set("review_pending", run.Fields("round", l.rnd, "summary", "", "reason", again,
			"passed_head_sha", none(passedReviewHead(record)), "record", false))
	}); err != nil {
		return false, err
	}
	l.say(fmt.Sprintf("--- round %d: fixer %s (the final check failed)", l.rnd, l.executor))
	summary, err := l.execute("fixer", "final-fixer", l.prompt+"\n\n## The final check failed. Fix the root cause.\n```\n"+shown+"\n```", "")
	if err != nil {
		return false, err
	}
	// the fixer that ran, with its summary, is on the record before a check or review can stop
	if err := l.save(func(record *run.Object) {
		record.Dict("waiting_on").Set("fixed", true)
		record.Dict("review_pending").Set("summary", summary)
	}); err != nil {
		return false, err
	}
	ok, checked, err := l.verify()
	if err != nil {
		return false, err
	}
	if ok {
		l.say("done-when after the final check: all passed")
	} else {
		l.say("done-when after the final check: FAILED")
	}
	passed, err := l.review(summary, ok, checked, again)
	if err != nil || passed {
		return passed, err
	}
	return false, r.note(l, "done-when or review after the final check did not pass", false)
}

// failingBlocks is what a fixer reads of a failed check, Python's prompts.failing_blocks: its last
// outCap characters, and ahead of them every block that begins above that end and says what failed,
// as a suite run in pieces prints each piece's failures where that piece ends.  A block is a line
// failureLine matches and the blank or indented lines under it, whole even where the end begins
// inside it; the whole output is kept under where and named first.
func failingBlocks(text, where string) (string, error) {
	length := utf8.RuneCountInString(text)
	if length <= outCap {
		return text, nil
	}
	above, at := length-outCap, 0
	var blocks [][]string
	open := false
	for _, line := range linesKept(text) {
		began := at
		at += utf8.RuneCountInString(line)
		line = strings.TrimRight(line, "\r\n")
		first, _ := utf8.DecodeRuneInString(line)
		if failureLine.MatchString(line) {
			if began >= above {
				break // this block and every later one lie whole in the end
			}
			blocks, open = append(blocks, []string{line}), true
		} else if open && (line == "" || config.Space(first)) {
			blocks[len(blocks)-1] = append(blocks[len(blocks)-1], line)
		} else if began >= above {
			break
		} else {
			open = false
		}
	}
	end := string([]rune(text)[above:])
	var named []string
	for _, block := range blocks {
		named = append(named, strings.TrimRightFunc(strings.Join(block, "\n"), config.Space))
	}
	if len(named) > 0 {
		end = strings.Join(named, "\n") + "\n\n... the end of the output:\n" + end
	}
	line, err := kept(strings.NewReader(text), where, "failed-check")
	return line + end, err
}

// linesKept is text's lines with their breaks, as Python's str.splitlines(keepends=True) reads them.
func linesKept(text string) []string {
	var lines []string
	start := 0
	for at := 0; at < len(text); {
		r, size := utf8.DecodeRuneInString(text[at:])
		at += size
		if r == '\r' && strings.HasPrefix(text[at:], "\n") {
			at++
		}
		if strings.ContainsRune("\n\r\v\f\x1c\x1d\x1e\u0085  ", r) {
			lines, start = append(lines, text[start:at]), at
		}
	}
	if start < len(text) {
		lines = append(lines, text[start:])
	}
	return lines
}
