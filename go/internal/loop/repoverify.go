package loop

import (
	"fmt"
	"maps"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/gitcall"
	"agentkit/internal/run"
	"agentkit/internal/uncommitted"
)

const (
	// baseOwed is what a run's record says while one of its checks has yet to fail on base.
	baseOwed = "owed"
	// diffCap is the most of a diff a reviewer is handed.
	diffCap = 300 * 1024
)

// verify is Python's verify_work on a repository's run: the checks are pinned to a commit, the
// executor's leftovers in it, and a checkout that moved under them verifies nothing.
func (r *repoPlace) verify(l *loop, path string) (bool, string, error) {
	if err := r.commitLeftovers(l); err != nil {
		return false, "", err
	}
	if err := r.meetTarget(l); err != nil {
		return false, "", err
	}
	head, tree, err := r.identity()
	if err != nil {
		return false, "", err
	}
	r.checked = [2]string{head, tree}
	scope, err := r.filesScope()
	if err != nil {
		return false, "", err
	}
	rules, err := r.rulesCheck()
	if err != nil {
		return false, "", err
	}
	code, _, err := r.git().Out("diff", "--quiet", "HEAD")
	if err != nil {
		return false, "", err
	}
	clean := code == 0
	ok, text, err := r.roundChecks(l, l.every, path)
	if err != nil {
		return false, "", err
	}
	moved, err := r.changedSince(head, tree)
	if err != nil {
		return false, "", err
	}
	if !clean || moved {
		ok = false
		text += "\n\nCheckout changed during done-when; these commands do not verify the pinned commit."
	}
	for _, failure := range []string{scope, rules} {
		if failure != "" {
			ok = false
			text += "\n\n" + failure
		}
	}
	text = fmt.Sprintf("Commit: %s\nTree: %s\n\n%s", head, tree, text)
	return ok, text, os.WriteFile(path, []byte(text), 0o666)
}

// checks runs the commands in the checkout, keeping on the record what they newly dirty: the
// loop's own droppings, never the executor's work, which a later commit of leftovers leaves out.
func (r *repoPlace) checks(l *loop, cmds []string, path string) (bool, string, error) {
	before, err := uncommitted.Paths(r.git())
	if err != nil {
		return false, "", err
	}
	ok, text, _, err := l.checksIn(r.wt, cmds, path)
	if err != nil {
		return false, "", err
	}
	after, err := uncommitted.Paths(r.git())
	if err != nil {
		return false, "", err
	}
	for _, each := range after {
		if !slices.Contains(before, each) {
			r.artifacts[each] = true
		}
	}
	return ok, text, l.save(func(record *run.Object) { record.Set("artifacts", r.artifactList()) })
}

func (r *repoPlace) artifactList() []any {
	found := []any{}
	for _, name := range slices.Sorted(maps.Keys(r.artifacts)) {
		found = append(found, name)
	}
	return found
}

// identity is the commit the checkout has out, and its tree.
func (r *repoPlace) identity() (string, string, error) {
	head, err := r.git().Must("rev-parse", "HEAD")
	if err != nil {
		return "", "", err
	}
	tree, err := r.git().Must("rev-parse", "HEAD^{tree}")
	return head, tree, err
}

// changedSince is whether the checkout is off that commit, or has tracked edits.
func (r *repoPlace) changedSince(head, tree string) (bool, error) {
	nowHead, nowTree, err := r.identity()
	if err != nil {
		return false, err
	}
	code, _, err := r.git().Out("diff", "--quiet", "HEAD")
	return nowHead != head || nowTree != tree || code != 0, err
}

// followTarget moves the run's base to the newest target commit its branch took in, before any
// check reads the work: a worker that rebased onto a newer tip would otherwise hand in the
// target's moves as its own lines.
func (r *repoPlace) followTarget(l *loop) error {
	fork, err := gitcall.IntegratedBase(r.git(), r.baseSHA, r.upstream())
	if err != nil || fork == r.baseSHA {
		return err
	}
	l.say(fmt.Sprintf("base: the branch took in %s up to %s", r.upstream(), fork[:min(len(fork), 12)]))
	return r.setBase(l, fork)
}

// filesScope is the failure for paths outside the task's `files:` pathspecs, "" for none.
func (r *repoPlace) filesScope() (string, error) {
	if len(r.files) == 0 {
		return "", nil
	}
	diff := []string{"diff", "--name-only", "--no-renames", "-z", r.baseSHA + "...HEAD"}
	changed, err := r.git().Must(diff...)
	if err != nil {
		return "", fmt.Errorf("files: %w", err)
	}
	inside, err := r.git().Must(append(append([]string{}, diff...), append([]string{"--"}, r.files...)...)...)
	if err != nil {
		return "", fmt.Errorf("files: %w", err)
	}
	var outside []string
	for _, each := range paths(changed) {
		if !slices.Contains(paths(inside), each) {
			outside = append(outside, each)
		}
	}
	slices.Sort(outside)
	if len(outside) == 0 {
		return "", nil
	}
	return "outside files: " + strings.Join(outside, ", "), nil
}

// changedTests is the branch's changed tests: test-shaped paths, and with named every file a
// done-when command names, removed paths too, as renaming a test out of discovery must show.
func (r *repoPlace) changedTests(l *loop, head string, named bool) ([]string, error) {
	listed, err := l.git(r.wt).Must("diff", "--name-only", "-z", "--no-renames", r.baseSHA+"..."+head)
	if err != nil {
		return nil, err
	}
	var found []string
	for _, each := range paths(listed) {
		if testShaped(each) || named && slices.ContainsFunc(l.cmds, func(cmd string) bool { return strings.Contains(cmd, each) }) {
			found = append(found, each)
		}
	}
	return found, nil
}

// testShaped is where tests live and what they are called, in the common languages' conventions.
func testShaped(path string) bool {
	parts := strings.Split(path, "/")
	for _, part := range parts[:len(parts)-1] {
		if slices.Contains([]string{"tests", "test", "spec", "specs", "__tests__"}, part) {
			return true
		}
	}
	name := parts[len(parts)-1]
	if strings.HasPrefix(name, "test_") {
		return true
	}
	for _, shape := range []string{"*_test.*", "*_spec.*", "*.test.*", "*.spec.*"} {
		if matched, _ := filepath.Match(shape, name); matched {
			return true
		}
	}
	return false
}

// baseProof is Python's fails_on_base beside the review, where the checks passed and the record
// owes a proof, nil otherwise: a check that finishes failing on base with the branch's tests laid
// over, and passes with every file it changed laid over, proves the change.
func (r *repoPlace) baseProof(l *loop, ok bool) (*besideReview, error) {
	var owed bool
	if err := l.save(func(record *run.Object) { owed = record.Str("base_proof") == baseOwed }); err != nil || !ok || !owed {
		return nil, err
	}
	return l.besideReview("base-proof", r.failsOnBase), nil
}

// proven joins the base proof and records what it found, before any verdict is, so a death while
// waiting resumes the proof too.  It never fails a round, by the owner's rule (7 Oct): why none
// could be shown is recorded instead.
func (l *loop) proven(proof *besideReview) error {
	if proof == nil {
		return nil
	}
	why, err := proof.join()
	if err != nil {
		return err
	}
	return l.save(func(record *run.Object) {
		var note any
		if why != "" {
			note = why
		} else {
			record.Set("base_proof", "proven")
		}
		record.Set("base_proof_note", note)
	})
}

// baseProofLine is what a run's result says of its proof, "" for a run that owes none.
func baseProofLine(record *run.Object) string {
	switch record.Str("base_proof") {
	case "proven":
		return "base proof: a check fails on the old code and passes with this change"
	case baseOwed:
		note := "not tried yet"
		if record.Truthy("base_proof_note") {
			note = record.Str("base_proof_note")
		}
		return "base proof: none shown (" + note + ")"
	}
	return ""
}

func (r *repoPlace) failsOnBase(l *loop) (string, error) {
	var cmds []string
	for _, cmd := range l.every {
		if !namesShard.MatchString(cmd) {
			cmds = append(cmds, cmd)
		}
	}
	if len(cmds) == 0 {
		return "the task has no check of its own that runs each round", nil
	}
	head, err := l.git(r.wt).Must("rev-parse", "HEAD")
	if err != nil {
		return "", err
	}
	listed, err := l.git(r.wt).Must("diff", "--name-only", "-z", "--no-renames", r.baseSHA+"..."+head)
	if err != nil {
		return "", err
	}
	changed := paths(listed)
	tests, err := r.changedTests(l, head, false)
	if err != nil {
		return "", err
	}
	if len(tests) == len(changed) {
		return "the branch changes nothing but tests", nil
	}
	short := r.baseSHA[:12]
	l.say("--- base proof: the task's own checks on " + short)
	onBase, err := r.replay(l, cmds, head, tests, "base.log")
	if err != nil {
		return "", err
	}
	if !slices.ContainsFunc(onBase, func(code *int) bool { return code == nil || *code != 0 }) {
		return fmt.Sprintf("every check passes on base %s with the branch's tests laid over: none shows the change, or its test lives where ak does not look for one", short), nil
	}
	// the control: the same replay with the branch's changes, so only they turn a check
	l.say(fmt.Sprintf("--- base proof: the same checks with %s's changes", head[:12]))
	onHead, err := r.replay(l, cmds, head, changed, "head.log")
	if err != nil {
		return "", err
	}
	for i, after := range onHead {
		// a check finishes failing as a reviewer's proof does
		if after != nil && *after == 0 && onBase[i] != nil && *onBase[i] > 0 && *onBase[i] != 126 && *onBase[i] != 127 {
			return "", nil
		}
	}
	if slices.ContainsFunc(onHead, func(code *int) bool { return code == nil || *code != 0 }) {
		return "a check fails in a checkout made from git alone even with the branch's changes: it needs what git does not hold, such as an installed dependency", nil
	}
	for i, code := range onBase {
		if code == nil || *code != 0 {
			return fmt.Sprintf("`%s` did not finish on base %s", cmds[i], short), nil
		}
	}
	return "", nil
}

// replay is each check's exit in a checkout of its own made from git alone, at base with paths of
// head laid over, committed the same way for every replay, so only the branch's files between two
// replays can turn a check; nil for one killed or never run.
func (r *repoPlace) replay(l *loop, cmds []string, head string, laid []string, name string) ([]*int, error) {
	tmp, err := os.MkdirTemp(l.dir, "")
	if err != nil {
		return nil, err
	}
	defer os.RemoveAll(tmp)
	checkout := filepath.Join(tmp, "checkout")
	if _, err := l.git(r.wt).Must("clone", "--quiet", "--shared", "--no-checkout", r.wt, checkout); err != nil {
		return nil, err
	}
	c := l.git(checkout)
	if _, err := c.Must("checkout", "--quiet", "--detach", r.baseSHA); err != nil {
		return nil, err
	}
	// what the branch deleted goes first, so a file it put where a folder was takes that place;
	// the paths come from a file, as a branch can change more than one command line holds
	listed, err := l.git(r.wt).Must("diff", "--name-only", "-z", "--no-renames", "--diff-filter=D", r.baseSHA+"..."+head)
	if err != nil {
		return nil, err
	}
	deleted := paths(listed)
	var gone, kept []string
	for _, each := range laid {
		if slices.Contains(deleted, each) {
			gone = append(gone, each)
		} else {
			kept = append(kept, each)
		}
	}
	literal := l.git(checkout, "GIT_LITERAL_PATHSPECS=1")
	for _, part := range []struct {
		names   []string
		command []string
	}{
		{gone, []string{"rm", "--quiet", "-r", "--ignore-unmatch"}},
		{kept, []string{"restore", "--source=" + head, "--staged", "--worktree"}},
	} {
		if len(part.names) == 0 {
			continue
		}
		file := filepath.Join(tmp, "paths")
		if err := os.WriteFile(file, []byte(strings.Join(part.names, "\x00")), 0o666); err != nil {
			return nil, err
		}
		if _, err := literal.Must(append(part.command, "--pathspec-from-file="+file, "--pathspec-file-nul")...); err != nil {
			return nil, err
		}
	}
	when, err := c.Must("show", "-s", "--format=%cI", "HEAD")
	if err != nil {
		return nil, err
	}
	var who []string
	for _, role := range []string{"AUTHOR", "COMMITTER"} {
		who = append(who, "GIT_"+role+"_NAME=agentkit", "GIT_"+role+"_EMAIL=agentkit@localhost", "GIT_"+role+"_DATE="+when)
	}
	if _, err := l.git(checkout, who...).Must("-c", "core.hooksPath="+os.DevNull, "commit", "--quiet", "--no-gpg-sign", "--allow-empty", "-m", "files of "+head+" over "+r.baseSHA); err != nil {
		return nil, err
	}
	path := filepath.Join(l.dir, name)
	_, text, marks, err := l.checksIn(checkout, cmds, path)
	if err != nil {
		return nil, err
	}
	over := ""
	if len(laid) > 0 {
		over = fmt.Sprintf(", with %d files of %s laid over", len(laid), head)
	}
	if err := os.WriteFile(path, []byte("Commit: "+r.baseSHA+over+"\n\n"+text), 0o666); err != nil {
		return nil, err
	}
	for len(marks) < len(cmds) {
		marks = append(marks, nil) // none past a kill ran
	}
	return marks, nil
}

// capped is a diff cut at diffCap, saying where the rest is.
func (r *repoPlace) capped(diff string) string {
	if len(diff) > diffCap {
		return diff[:diffCap] + fmt.Sprintf("\n\n[diff truncated at %d bytes; use git in %s for the rest]", diffCap, r.wt)
	}
	return diff
}

// view is a repository's review input: the change's whole diff, or in a later round what changed
// since the last review with ak's proof of that review's findings, and the checks it changed.
func (r *repoPlace) view(l *loop, j *judging, passed, total int) (string, string, string, error) {
	if err := r.commitLeftovers(l); err != nil {
		return "", "", "", err
	}
	return r.viewOf(l, j, passed, total)
}

// viewOf is that view of the commit the checkout has out.
func (r *repoPlace) viewOf(l *loop, j *judging, passed, total int) (string, string, string, error) {
	diff, err := r.git().Try("diff", r.baseSHA+"...HEAD")
	if err != nil {
		return "", "", "", err
	}
	at, err := r.git().Must("rev-parse", "HEAD")
	if err != nil {
		return "", "", "", err
	}
	section, err := r.earlierWork(l, j, fmt.Sprintf("## Diff (%s...HEAD in %s)\n```diff\n%s\n```", r.base, r.wt, r.capped(diff)), at)
	if err != nil {
		return "", "", "", err
	}
	checks := ""
	tests, err := r.changedTests(l, "HEAD", true)
	if err != nil {
		return "", "", "", err
	}
	if len(tests) > 0 {
		width := 0
		args := []string{"--no-renames", r.baseSHA + "...HEAD", "--"}
		for _, each := range tests {
			width = max(width, len(each)*4+2) // room for full names, git's quoted ones too
			args = append(args, ":(literal)"+each)
		}
		stat, err := r.git().Must(append([]string{"diff", fmt.Sprintf("--stat=%d,%d", width+80, width)}, args...)...)
		if err != nil {
			return "", "", "", err
		}
		lines := strings.Split(stat, "\n")
		checks = "## Checks the executor changed\n```\n" + strings.Join(lines[:len(lines)-1], "\n") + "\n```\n\n"
	}
	head, tree, err := r.identity()
	if err != nil {
		return "", "", "", err
	}
	r.viewed = [2]string{head, tree}
	return section, checks, fmt.Sprintf("## Done-when output (run by the loop on commit %s; %d of %d commands exited 0)", head[:12], passed, total), nil
}

// judged holds a verdict to the commit its checks ran on: a checkout changed since verifies nothing.
func (r *repoPlace) judged(l *loop, verdict string) (string, []any, error) {
	head, tree := r.checked[0], r.checked[1]
	moved, err := r.changedSince(head, tree)
	if err != nil {
		return "", nil, err
	}
	evidence := []any{"head_sha", head, "tree_sha", tree}
	if moved || r.viewed != r.checked {
		verdict = "FAIL"
		l.say("WARN the checkout changed after verification; overriding to FAIL")
		evidence = append(evidence, "overridden", "the checkout changed after verification")
	}
	if verdict == "PASS" {
		evidence = append(evidence, "passed_head_sha", head)
	}
	return verdict, evidence, l.save(func(record *run.Object) { record.Set("delta_from", head) })
}
