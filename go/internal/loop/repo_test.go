//go:build linux

package loop

import (
	"bytes"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/run"
)

// repoRig is a run's checkout under a fresh HOME: a clone with one commit, the record naming it.
func repoRig(t *testing.T) (*loop, *repoPlace) {
	t.Helper()
	l := rig(t, 0)
	l.silence, l.ceiling = 60e9, 3600e9
	home := os.Getenv("HOME")
	t.Setenv("GIT_AUTHOR_NAME", "acme")
	t.Setenv("GIT_AUTHOR_EMAIL", "acme@example.com")
	t.Setenv("GIT_COMMITTER_NAME", "acme")
	t.Setenv("GIT_COMMITTER_EMAIL", "acme@example.com")
	repo := filepath.Join(home, "acme")
	shell(t, home, "git init -q -b main acme && cd acme && git commit -q --allow-empty -m init")
	shell(t, repo, "printf 'x = 1\\n' > widget.txt && git add -A && git commit -q -m widget")
	r := &repoPlace{repo: repo, wt: filepath.Join(home, ".agentkit", "wt", l.id), branch: "ak/acme", base: "main", target: "main", title: "Add acme", artifacts: map[string]bool{}}
	shell(t, repo, "git worktree add -q -b ak/acme "+r.wt)
	r.baseSHA = strings.TrimSpace(shell(t, r.wt, "git rev-parse HEAD"))
	l.workspace, l.place, l.reviewLines = r.wt, r, config.AtMost(300)
	if err := run.Change(l.dir, func(record *run.Object) error {
		run.SetAll(record, "run_id", l.id, "repo", repo, "worktree", r.wt, "branch", r.branch, "title", r.title, "scratch", false, "state", "fail")
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	return l, r
}

func shell(t *testing.T, dir, script string) string {
	t.Helper()
	command := exec.Command("bash", "-c", script)
	command.Dir = dir
	said, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("%s: %v: %s", script, err, said)
	}
	return string(said)
}

func TestLeftoversAreCommittedAndJunkAndWhatTheChecksMadeStayOut(t *testing.T) {
	l, r := repoRig(t)
	shell(t, r.wt, "echo work > kept.txt; mkdir -p node_modules .ak-test-x; echo a > node_modules/a; echo b > .ak-test-x/b; echo c > made.txt")
	r.artifacts["made.txt"] = true
	if err := r.commitLeftovers(l); err != nil {
		t.Fatal(err)
	}
	tree := shell(t, r.wt, "git ls-tree -r --name-only HEAD")
	if !strings.Contains(tree, "kept.txt") || strings.Contains(tree, "node_modules") || strings.Contains(tree, ".ak-test-x") || strings.Contains(tree, "made.txt") {
		t.Fatalf("tree %q", tree)
	}
	if subject := strings.TrimSpace(shell(t, r.wt, "git log -1 --format=%s")); subject != "Add acme" {
		t.Fatalf("subject %q", subject)
	}
}

func TestTheExcludeTakesOnlyWhatItIsMissingAndItsFailureSaysWhatBreaks(t *testing.T) {
	l, r := repoRig(t)
	if err := r.excludeJunk(l); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(r.repo, ".git", "info", "exclude")
	first, _ := os.ReadFile(path)
	if err := r.excludeJunk(l); err != nil {
		t.Fatal(err)
	}
	if again, _ := os.ReadFile(path); !bytes.Equal(first, again) || !strings.Contains(string(first), "__pycache__/\n") {
		t.Fatalf("was %q, now %q", first, again)
	}
	os.RemoveAll(filepath.Dir(path))
	os.WriteFile(filepath.Dir(path), []byte("no folder\n"), 0o666)
	err := r.excludeJunk(l)
	if err == nil || !strings.HasPrefix(err.Error(), "cannot exclude build junk in "+r.wt+": ") ||
		!strings.HasSuffix(err.Error(), "; without that git would hand the executor's own __pycache__ to the leftover sweep") {
		t.Fatalf("err %v", err)
	}
}

func TestAChangePastTheCeilingEndsBlockedAndAMovedBlockIsNotCounted(t *testing.T) {
	l, r := repoRig(t)
	l.reviewLines = config.AtMost(10)
	shell(t, r.wt, "seq 1 8 | sed 's/^/the moved row of the retry table number /' > table.txt; git add -A; git commit -qm table")
	r.baseSHA = strings.TrimSpace(shell(t, r.wt, "git rev-parse HEAD"))
	shell(t, r.wt, "mkdir sub; git mv table.txt sub/other.txt; printf 'x\\n' >> sub/other.txt; git add -A; git -c diff.renames=false commit -qm move")
	if err := r.firstReviewCeiling(l); err != nil {
		t.Fatalf("a moved block counted: %v", err)
	}
	shell(t, r.wt, "seq 1 11 > new.txt; git add -A; git commit -qm new")
	err := r.firstReviewCeiling(l)
	var cannot *blocked
	if err == nil || !strings.Contains(err.Error(), "The change on ak/acme adds ") || !strings.HasSuffix(err.Error(), "a first review takes at most 10; split it") || !asBlocked(err, &cannot) {
		t.Fatalf("err %v", err)
	}
	if l.reviewLines = config.NoLimit; r.firstReviewCeiling(l) != nil {
		t.Fatal("no limit refused a change")
	}
}

func asBlocked(err error, into **blocked) bool {
	found, ok := err.(*blocked)
	*into = found
	return ok
}

func TestAGeneratedFileCountsForNothingAndItsMarkIsReadAtBase(t *testing.T) {
	l, r := repoRig(t)
	l.reviewLines = config.AtMost(3)
	shell(t, r.wt, "echo 'gen/** linguist-generated' > .gitattributes; git add -A; git commit -qm mark")
	r.baseSHA = strings.TrimSpace(shell(t, r.wt, "git rev-parse HEAD"))
	shell(t, r.wt, "mkdir gen; seq 1 50 > gen/out.txt; git add -A; git commit -qm generated")
	if err := r.firstReviewCeiling(l); err != nil {
		t.Fatal(err)
	}
	shell(t, r.wt, "echo 'other/** linguist-generated' > .gitattributes; mkdir other; seq 1 50 > other/out.txt; git add -A; git commit -qm mine")
	if err := r.firstReviewCeiling(l); err == nil {
		t.Fatal("a change left its own lines out by marking them generated")
	}
}

func TestARulesRefusalNamesAPythonChangeAndAGrownProseFile(t *testing.T) {
	_, r := repoRig(t)
	shell(t, r.wt, "mkdir tests; echo '# key' > tests/test_key_a.py; printf 'one two\\n' > notes.md; git add -A; git commit -qm base")
	r.baseSHA = strings.TrimSpace(shell(t, r.wt, "git rev-parse HEAD"))
	shell(t, r.wt, "printf 'one two three\\n' > notes.md; git add -A; git commit -qm grow")
	if failure, err := r.rulesCheck(); err != nil || !strings.HasPrefix(failure, "notes.md grows from 2 to 3 words;") {
		t.Fatalf("%q %v", failure, err)
	}
	shell(t, r.wt, "git reset -q --hard HEAD^; echo x > tool.py; git add -A; git commit -qm python")
	if failure, err := r.rulesCheck(); err != nil || !strings.HasPrefix(failure, "Python changed with no answer key: tool.py.") {
		t.Fatalf("%q %v", failure, err)
	}
	shell(t, r.wt, "echo '# k' > tests/test_key_b.py; git add -A; git commit -qm key")
	if failure, err := r.rulesCheck(); err != nil || failure != "" {
		t.Fatalf("%q %v", failure, err)
	}
}

func TestAProofRunsOnItsRevisionAndTheCheckoutComesBack(t *testing.T) {
	l, r := repoRig(t)
	if err := os.MkdirAll(filepath.Join(l.roundDir()), 0o777); err != nil {
		t.Fatal(err)
	}
	shell(t, r.wt, "echo new > added.txt; git add -A; git commit -qm added; echo left > dirty.txt")
	head := strings.TrimSpace(shell(t, r.wt, "git rev-parse HEAD"))
	proof, err := r.proofOn(l, "test -f added.txt", filepath.Join(l.roundDir(), "proof.log"), r.baseSHA, head)
	if err != nil {
		t.Skip(err) // no box here
	}
	if code, _ := proof.Int("returncode"); code != 1 {
		t.Fatalf("proof %s", run.Line(proof))
	}
	if now := strings.TrimSpace(shell(t, r.wt, "git rev-parse HEAD")); now != head {
		t.Fatalf("left on %s", now)
	}
	if branch := strings.TrimSpace(shell(t, r.wt, "git symbolic-ref --short HEAD")); branch != "ak/acme" {
		t.Fatalf("left on %s", branch)
	}
	if _, err := os.Stat(filepath.Join(r.wt, "dirty.txt")); err != nil {
		t.Fatal("the probe took what was there before it")
	}
	if record, _ := run.Read(l.dir); record.Has("probe_checkout") {
		t.Fatalf("recovery still pending: %s", run.Line(record))
	}
}

func TestAFindingOutsideTheChangeThatFailsOnBaseIsAFollowUp(t *testing.T) {
	l, r := repoRig(t)
	if err := os.MkdirAll(filepath.Join(l.roundDir()), 0o777); err != nil {
		t.Fatal(err)
	}
	shell(t, r.wt, "echo new > added.txt; git add -A; git commit -qm added")
	row := run.Fields("kind", "finding", "path", "widget.txt", "line", 1, "what", "w", "why", "y",
		"evidence", run.Fields("run", "false", "returncode", 1, "output", ""))
	weighed, err := r.weigh(l, row, 0, &judging{})
	if err != nil {
		t.Skip(err)
	}
	if weighed.Str("kind") != "follow-up" || !strings.HasPrefix(weighed.Str("before"), "base "+r.baseSHA) {
		t.Fatalf("weighed %s", run.Line(weighed))
	}
	inside := run.Fields("kind", "finding", "path", "added.txt", "line", 1, "what", "w", "why", "y",
		"evidence", run.Fields("run", "test ! -f added.txt", "returncode", 1, "output", ""))
	if weighed, err = r.weigh(l, inside, 1, &judging{}); err != nil || weighed.Str("kind") != "finding" {
		t.Fatalf("%v %s", err, run.Line(weighed))
	}
}

func TestAReviewersEditsLandInThePatchAndNowhereElse(t *testing.T) {
	l, r := repoRig(t)
	out := filepath.Join(l.roundDir(), "reviewer")
	if err := os.MkdirAll(out, 0o777); err != nil {
		t.Fatal(err)
	}
	branch := strings.TrimSpace(shell(t, r.wt, "git rev-parse ak/acme"))
	err := r.inCopy(l, out, func(cwd string) error {
		shell(t, cwd, "echo edited > widget.txt; git add -A; git commit -qm sneaky; echo more > extra.txt")
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if now := strings.TrimSpace(shell(t, r.wt, "git rev-parse ak/acme")); now != branch {
		t.Fatalf("the branch moved to %s", now)
	}
	if said := shell(t, r.wt, "cat widget.txt"); said != "x = 1\n" {
		t.Fatalf("the checkout holds %q", said)
	}
	patch, _ := os.ReadFile(filepath.Join(l.roundDir(), "reviewer-changes.patch"))
	if !strings.Contains(string(patch), "edited") || !strings.Contains(string(patch), "extra.txt") {
		t.Fatalf("patch %q", patch)
	}
	if _, err := os.Stat(filepath.Join(l.roundDir(), "review-checkout")); err == nil {
		t.Fatal("the copy stayed")
	}
	log, _ := os.ReadFile(filepath.Join(l.dir, "log.txt"))
	if !strings.Contains(string(log), "WARN undid reviewer changes: ") {
		t.Fatalf("log %q", log)
	}
}

func TestCleanSavesTheWorkTakesTheCheckoutAndARepeatIsNothing(t *testing.T) {
	l, r := repoRig(t)
	shell(t, r.wt, "echo left > left.txt")
	id := filepath.Base(l.dir)
	var out bytes.Buffer
	if err := Clean(id, &out); err != nil {
		t.Fatal(err)
	}
	if want := id + ": removed worktree " + r.wt + "; branch ak/acme kept\n"; out.String() != want {
		t.Fatalf("said %q, want %q", out.String(), want)
	}
	if said := shell(t, r.repo, "git show ak/acme:left.txt"); said != "left\n" {
		t.Fatalf("branch holds %q", said)
	}
	out.Reset()
	if err := Clean(id, &out); err != nil {
		t.Fatalf("again: %v, %q", err, out.String())
	}
}

func TestCleanLeavesACheckoutItCannotSave(t *testing.T) {
	for name, script := range map[string]string{
		"detached": "echo x >> widget.txt; git add -A; git commit -qm one; git checkout -q --detach; echo y > off.txt",
		// the first pick resolved and committed by hand leaves the second queued, with no CHERRY_PICK_HEAD
		"queued pick": "git checkout -q -b side && echo theirs > widget.txt && git commit -qam theirs && " +
			"echo two > two.txt && git add two.txt && git commit -qm two && git checkout -q ak/acme && " +
			"echo ours > widget.txt && git commit -qam ours && ! git cherry-pick side~1 side 2>/dev/null && " +
			"git add widget.txt && git commit -q --no-edit && test -f \"$(git rev-parse --git-path sequencer/todo)\"",
	} {
		t.Run(name, func(t *testing.T) {
			l, r := repoRig(t)
			shell(t, r.wt, script)
			err := Clean(filepath.Base(l.dir), &bytes.Buffer{})
			if err == nil || !strings.Contains(err.Error(), "left worktree "+r.wt+": could not save its work on ak/acme") {
				t.Fatalf("err %v", err)
			}
			if _, statErr := os.Stat(r.wt); statErr != nil {
				t.Fatal("the checkout went with its work")
			}
			if record, _ := run.Read(l.dir); !record.Truthy("checkout_kept") {
				t.Fatalf("record %s", run.Line(record))
			}
		})
	}
}

func TestFollowSaysWhyOnlyForANoMergeLaunch(t *testing.T) {
	for flag, want := range map[bool]string{true: "ak run: cannot exclude\n", false: ""} {
		l := rig(t, 0)
		if err := run.Change(l.dir, func(record *run.Object) error {
			run.SetAll(record, "state", "error", "error", "cannot exclude", "launch_opts", run.Fields("--no-merge", flag))
			return nil
		}); err != nil {
			t.Fatal(err)
		}
		appendLog(l.dir, "")
		var errOut bytes.Buffer
		if code := Follow(l.dir, 0, &bytes.Buffer{}, &errOut); code != 2 || errOut.String() != want {
			t.Fatalf("--no-merge %v: exit %d, stderr %q", flag, code, errOut.String())
		}
	}
}

func TestStopCheckoutNeverTakesWhatIsUnderCode(t *testing.T) {
	l, _ := repoRig(t)
	var told []string
	record := run.Fields("repo", filepath.Join(os.Getenv("HOME"), "acme"), "worktree", filepath.Join(os.Getenv("HOME"), "code", "acme"), "branch", "ak/acme")
	if stopCheckout(l.dir, record, func(line string) { told = append(told, line) }, false) || len(told) != 1 || !strings.Contains(told[0], "it is under") {
		t.Fatalf("told %v", told)
	}
}

func TestADeliveryWithNoReviewBehindItWaitsForOneItsVerdictStanding(t *testing.T) {
	l, r := repoRig(t)
	if r.noMerge = true; r.finished(l) != nil {
		t.Fatal("a --no-merge run has nothing to land")
	}
	if err := run.Change(l.dir, func(record *run.Object) error { run.SetAll(record, "state", "running", "verdict", "PASS"); return nil }); err != nil {
		t.Fatal(err)
	}
	r.noMerge = false
	if code := l.finish(r.finished(l)); code != 1 {
		t.Fatalf("exit %d", code)
	}
	record, _ := run.Read(l.dir)
	if record.Str("state") != "exhausted" || record.Str("verdict") != "PASS" || record.Str("error") != "delivery requires a successful reviewer allowed by the model policy; resume the run to obtain review" {
		t.Fatalf("record %s", run.Line(record))
	}
}

func TestAGitThatStoppedParksTheRunExhausted(t *testing.T) {
	l, _ := repoRig(t)
	if err := run.Change(l.dir, func(record *run.Object) error { record.Set("state", "running"); return nil }); err != nil {
		t.Fatal(err)
	}
	if code := l.finish(&gitcall.Stopped{Why: "git fetch stopped"}); code != 1 {
		t.Fatalf("exit %d", code)
	}
	record, _ := run.Read(l.dir)
	if record.Str("state") != "exhausted" || record.Str("error") != "git fetch stopped" || record.Has("quota_dry") {
		t.Fatalf("record %s", run.Line(record))
	}
}

func TestALineStandsWhereTheFixLeftIt(t *testing.T) {
	_, r := repoRig(t)
	shell(t, r.wt, `printf 'l1\nl2 old text here\nl3\nl4\nl5\n' > a.txt; git add -A; git commit -qm a`)
	since := strings.TrimSpace(shell(t, r.wt, "git rev-parse HEAD"))
	shell(t, r.wt, `printf 'l0 new\nl1\nother\nl2 new text here\nl4\nl5\n' > a.txt; git add -A; git commit -qm fix`)
	row := func(line int) *run.Object { return run.Fields("path", "a.txt", "line", line) }
	for _, each := range []struct {
		line, at int
		touched  bool
		lines    int
	}{
		{1, 2, false, 1}, // a line above it was added: it moved
		{2, 4, true, 2},  // rewritten: it stands at the line that reads most like it
		{3, 4, true, 2},  // both removed lines fall in one hunk
		{5, 6, false, 1},
	} {
		at, touched, lines, err := r.placed(row(each.line), since)
		if err != nil || at != each.at || touched != each.touched || len(lines) != each.lines {
			t.Errorf("line %d: at %d, touched %v, lines %v (%v)", each.line, at, touched, lines, err)
		}
	}
	if lines, touched, err := r.moved("a.txt", 2, ""); err != nil || touched || !slices.Equal(lines, []int{2}) {
		t.Errorf("no delta: %v %v %v", lines, touched, err)
	}
	head := strings.TrimSpace(shell(t, r.wt, "git rev-parse HEAD"))
	for line, want := range map[int]bool{1: true, 2: false, 3: true, 4: true, 5: false} {
		if changed, err := r.changedLine(row(line), head, since); err != nil || changed != want {
			t.Errorf("line %d changed: %v (%v)", line, changed, err)
		}
	}
}

func TestANewFindingBlocksOnlyInsideTheFixDeltaOrWithABreak(t *testing.T) {
	l, r := repoRig(t)
	if err := os.MkdirAll(l.roundDir(), 0o777); err != nil {
		t.Fatal(err)
	}
	shell(t, r.wt, `printf 'l1\nl2\nl3\n' > a.txt; git add -A; git commit -qm a`)
	since := strings.TrimSpace(shell(t, r.wt, "git rev-parse HEAD"))
	shell(t, r.wt, `printf 'new\nl2\nl3\n' > a.txt; touch fixed.txt; git add -A; git commit -qm fix`)
	j := &judging{since: since, sites: map[string]bool{"a.txt:3": true}}
	weigh := func(line int, command string) *run.Object {
		t.Helper()
		row := run.Fields("kind", "finding", "path", "a.txt", "line", line, "what", "w", "why", "y", "evidence", run.Fields("run", command, "returncode", 1, "output", ""))
		weighed, err := r.weigh(l, row, line, j)
		if err != nil {
			t.Skip(err) // no box here
		}
		return weighed
	}
	for _, each := range []struct {
		line    int
		command string
		kind    string
		outside bool
	}{
		{1, "false", "finding", false},               // the fix changed that line
		{2, "false", "note", true},                   // it fails on the commit judged too
		{2, "test ! -f fixed.txt", "finding", false}, // it passes there: the fix broke it
		{3, "false", "finding", false},               // an earlier finding's site upholds it
	} {
		if got := weigh(each.line, each.command); got.Str("kind") != each.kind || got.Truthy("outside") != each.outside {
			t.Errorf("line %d, %q: %s", each.line, each.command, run.Line(got))
		}
	}
}

func TestAReplayOnlyAddsWhatTheReviewerDidNotHandIn(t *testing.T) {
	l, _ := repoRig(t)
	failed := run.Fields("run", "false", "returncode", 1, "output", "")
	passes := run.Fields("run", "true", "returncode", 0, "output", "")
	at := func(kind string, line int, evidence *run.Object) *run.Object {
		return run.Fields("kind", kind, "path", "a.txt", "line", line, "what", "w", "why", "y", "evidence", evidence)
	}
	j := &judging{replayed: []replay{
		{at("finding", 1, failed), failed, true, false, []int{1}},
		{at("finding", 2, failed), failed, true, true, []int{2, 3}},
		{at("finding", 4, passes), passes, false, false, []int{4}},
	}}
	got := l.withReplays([]*run.Object{at("finding", 3, failed), run.Fields("kind", "done")}, j)
	var said []string
	for _, row := range got {
		said = append(said, row.Str("kind")+":"+row.Str("replayed"))
	}
	want := []string{"finding:", "finding:still failing; it blocks until its proof passes", "note:fixed; its proof passes now", "done:"}
	if !slices.Equal(said, want) {
		t.Fatalf("got %q", said)
	}
}
