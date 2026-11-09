package loop

import (
	"cmp"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/gitcall"
)

// affectedSuite is Python's affected_suite: whether the round's suite passed and what it said, ""
// where there is none.  The target's `tests:` line opts in by naming AK_CHANGED, read off the
// target each round, as a sibling can change it mid-run; a run landing runs it whole instead.  It
// runs on HEAD merged onto the target as just fetched, in a clone borrowing the checkout's objects,
// AK_CHANGED naming a file of the paths the change edits relative to the target, so a sibling merged
// since meets the change here rather than in the landing line.  A red whose failing tests all fail
// again on that target alone (AK_ONLY) is the target's, not the change's: it passes, and says which.
// A sibling that arrived during the checks and conflicts is landing's to bring in, in conflict rounds
// outside the task budget: the round judges its own work merged onto the target it last integrated
// with.
func (r *repoPlace) affectedSuite(l *loop) (bool, string, error) {
	upstream := r.upstream()
	if upstream == "" || r.noMerge || !namesChanged.MatchString(gitcall.Suite(r.wt, upstream)) {
		return true, "", nil
	}
	record, err := read(l)
	if err != nil || record.Truthy("landing") {
		return true, "", err
	}
	g := l.git(r.wt)
	if code, _, err := g.Fetch("origin", strings.TrimPrefix(upstream, "origin/")); err != nil {
		return false, "", err
	} else if code != 0 {
		l.say("WARN cannot fetch " + upstream + ": the suite meets it as last fetched")
	}
	tip, err := g.Must("rev-parse", upstream+"^{commit}")
	if err != nil {
		return false, "", err
	}
	head, err := g.Must("rev-parse", "HEAD")
	if err != nil {
		return false, "", err
	}
	tmp, err := os.MkdirTemp(l.dir, "")
	if err != nil {
		return false, "", err
	}
	defer os.RemoveAll(tmp)
	checkout, changed := filepath.Join(tmp, "checkout"), filepath.Join(tmp, "changed")
	c := l.git(checkout)
	if _, err := g.Must("clone", "--quiet", "--shared", "--no-checkout", r.wt, checkout); err != nil {
		return false, "", err
	}
	if _, err := c.Must("config", "ak.repository", gitcall.RepositoryID(r.wt)); err != nil {
		return false, "", err
	}
	code, tree, err := c.Out("merge-tree", "--write-tree", "--name-only", tip, head)
	if err == nil && code != 0 {
		last := cmp.Or(record.Str("target_sha"), r.baseSHA)
		l.say(fmt.Sprintf("done-when: %s moved to %s with a change conflicting with this one, which landing brings in; the round meets %s", upstream, tip[:12], last[:12]))
		tip = last
		code, tree, err = c.Out("merge-tree", "--write-tree", "--name-only", tip, head)
	}
	if err != nil {
		return false, "", err
	}
	suite := gitcall.Suite(r.wt, tip)
	if !namesChanged.MatchString(suite) {
		return true, "", nil
	}
	where := fmt.Sprintf("%s merged onto %s at %s", head[:12], upstream, tip[:12])
	if code != 0 {
		return false, fmt.Sprintf("$ %s\n[not run: %s does not merge cleanly]\n%s", suite, where, tree), nil
	}
	tree, _, _ = strings.Cut(tree, "\n")
	merged, err := l.git(checkout, gitcall.Stamp...).Must("commit-tree", tree, "-p", tip, "-p", head, "-m", where)
	if err != nil {
		return false, "", err
	}
	if _, err := c.Must("checkout", "--quiet", "--detach", merged); err != nil {
		return false, "", err
	}
	// unstripped: a first name can start with a space
	code, listed, why, err := c.Run("diff", "--name-only", "-z", "--no-renames", tip, merged)
	if err == nil && code != 0 {
		err = fmt.Errorf("git diff failed in %s: %s", checkout, gitcall.Strip(why))
	}
	if err != nil {
		return false, "", err
	}
	edited := paths(listed)
	lines := ""
	for _, path := range edited {
		lines += path + "\n"
	}
	if err := os.WriteFile(changed, []byte(lines), 0o666); err != nil {
		return false, "", err
	}
	// moved is whether a run left the checkout off sha or edited what it tracks: then its verdict
	// is not that commit's
	moved := func(sha string) (bool, error) {
		now, err := c.Must("rev-parse", "HEAD")
		if err != nil {
			return false, err
		}
		dirty, _, err := c.Out("diff", "--quiet", "HEAD")
		return now != sha || dirty != 0, err
	}
	narrowed, seen := *l, &checkSelection{}
	narrowed.changed = changed
	ok, text, marks, err := narrowed.checksIn(checkout, []string{suite}, filepath.Join(l.roundDir(), "suite.log"), l.rows("done-when", merged), seen)
	if err != nil {
		return false, "", err
	}
	text = fmt.Sprintf("The `tests:` suite on %s, AK_CHANGED listing its %d paths:\n\n%s", where, len(edited), text)
	if gone, err := moved(merged); err != nil || gone {
		return false, text + "\n\nCheckout changed during the suite; it does not verify " + where + ".", err
	}
	// the target's red only where each red piece named tests of its own that fail there too
	failed := failedTests(seen)
	if ok || marks[0] == nil || seen.unnamed || len(failed) == 0 {
		return ok, text, nil
	}
	if _, err := c.Must("checkout", "--quiet", "--force", "--detach", tip); err != nil {
		return false, "", err
	}
	if _, err := c.Must("clean", "-fdqx"); err != nil {
		return false, "", err
	}
	again := &checkSelection{shard: "1/1", tests: failed}
	if _, _, _, err := l.checksIn(checkout, []string{suite}, filepath.Join(l.roundDir(), "suite-target.log"), l.rows("done-when", tip), again); err != nil {
		return false, "", err
	}
	if gone, err := moved(tip); err != nil || gone {
		return false, text, err
	}
	repeated := failedTests(again)
	theirs := slices.DeleteFunc(slices.Clone(failed), func(test string) bool { return !slices.Contains(repeated, test) })
	if len(theirs) == 0 {
		return false, text, nil
	}
	said := fmt.Sprintf("failing on %s at %s alone too, the target's own: %s", upstream, tip[:12], strings.Join(theirs, " "))
	l.say("done-when: the suite's tests " + said)
	return len(theirs) == len(failed), text + "\n\nTests " + said, nil
}

// failedTests is the tests a check of one command saw fail every go, sorted.
func failedTests(seen *checkSelection) []string {
	var failed []string
	for _, red := range seen.reds {
		for _, test := range names(red.List("tests")) {
			if !slices.Contains(failed, test) {
				failed = append(failed, test)
			}
		}
	}
	slices.Sort(failed)
	return failed
}
