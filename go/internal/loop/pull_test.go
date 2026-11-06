//go:build linux

package loop

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/gh"
	"agentkit/internal/run"
)

// fakeGH puts a gh first on PATH answering each call whose words hold a key with its text, and
// keeping every call's words in the file it returns.
func fakeGH(t *testing.T, answers map[string]string) string {
	t.Helper()
	bin := t.TempDir()
	calls := filepath.Join(bin, "calls")
	script := "#!/bin/sh\necho \"$*\" >> " + calls + "\ncase \"$*\" in\n"
	index := 0
	for key, text := range answers {
		index++
		answer := filepath.Join(bin, fmt.Sprintf("answer-%d", index))
		if err := os.WriteFile(answer, []byte(text), 0o600); err != nil {
			t.Fatal(err)
		}
		script += "*'" + key + "'*) cat " + answer + ";;\n"
	}
	script += "*) echo \"no answer for $*\" >&2; exit 1;;\nesac\n"
	if err := os.WriteFile(filepath.Join(bin, "gh"), []byte(script), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	return calls
}

// pullRig is a review's place on the rig's checkout, the commit it has out being the PR's head, as
// its record says, and what GitHub says of that PR, in the given state.
func pullRig(t *testing.T, state string) (*loop, *pullPlace, map[string]string) {
	t.Helper()
	l, r := repoRig(t)
	head := strings.TrimSpace(shell(t, r.wt, "git rev-parse HEAD"))
	p := &pullPlace{repoPlace: r, url: "https://github.com/acme/widget/pull/1", sha: head}
	l.place, l.pull, l.reviewer = p, p.url, "opus"
	if err := run.Change(l.dir, func(record *run.Object) error { record.Set("head_sha", head); return nil }); err != nil {
		t.Fatal(err)
	}
	answers := map[string]string{
		"pr view": `{"title":"Add contrib","body":"adds","author":{"login":"other-dev"}}`,
		"api repos/acme/widget/pulls/1": fmt.Sprintf(`{"state":%q,"base":{"ref":"main"},"head":{"sha":%q,"ref":"ak/acme","repo":{"clone_url":%q}}}`,
			state, head, r.repo),
	}
	return l, p, answers
}

func recorded(t *testing.T, l *loop) *run.Object {
	t.Helper()
	record, err := run.Read(l.dir)
	if record == nil {
		t.Fatal(err)
	}
	return record
}

func TestAPullThatIsNotOpenIsRefusedByItsState(t *testing.T) {
	l, _, answers := pullRig(t, "closed")
	fakeGH(t, answers)
	err := l.reviewPull()
	if err == nil || err.Error() != l.pull+" is CLOSED, not open" {
		t.Fatalf("err = %v", err)
	}
}

func TestAMovedHeadOrCheckoutKeepsTheWorkForInspection(t *testing.T) {
	const kept = "the PR head or review checkout changed; existing work is kept for inspection"
	l, p, answers := pullRig(t, "open")
	fakeGH(t, answers)
	if err := run.Change(l.dir, func(record *run.Object) error {
		run.SetAll(record, "worktree", p.wt, "head_sha", "0000000000000000000000000000000000000000")
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	if err := l.reviewPull(); err == nil || err.Error() != kept {
		t.Fatalf("err = %v", err)
	}
}

// A review judges what its own landing made of the PR's head once that is pinned, as Python's
// pinned_head: a checkout moved past the head before then is refused.
func TestAReviewJudgesWhatItsOwnLandingMadeOnceItIsPinned(t *testing.T) {
	l, p, _ := pullRig(t, "open")
	if err := run.Change(l.dir, func(record *run.Object) error { record.Set("review_pr", p.url); return nil }); err != nil {
		t.Fatal(err)
	}
	shell(t, p.wt, "git commit -q --allow-empty -m 'the landing rebased it'")
	if err := p.restore(l, "tests"); err == nil {
		t.Fatal("a checkout moved past the PR head was judged before it was pinned")
	}
	if err := p.pin(l); err != nil {
		t.Fatal(err)
	}
	if err := p.restore(l, "tests"); err != nil {
		t.Fatal(err)
	}
}

func TestNoTestsLineRunsNothingAndItsDoneWhenIsNull(t *testing.T) {
	l, p, _ := pullRig(t, "open")
	path := filepath.Join(l.roundDir(), "donewhen.log")
	ok, text, err := p.verify(l, path)
	if err != nil || !ok || text != noTestsRun {
		t.Fatalf("ok=%v text=%q err=%v", ok, text, err)
	}
	if _, err := os.Stat(path); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("nothing ran, yet its log: %v", err)
	}
	if log, _ := os.ReadFile(filepath.Join(l.dir, "log.txt")); !strings.Contains(string(log), noTestsRun+"\n") {
		t.Fatalf("log = %s", log)
	}
	if _, _, _, err := p.view(l, &judging{}, 0, 0); err != nil {
		t.Fatal(err)
	}
	verdict, evidence, err := p.judged(l, "PASS")
	if err != nil || verdict != "PASS" {
		t.Fatalf("verdict=%s err=%v", verdict, err)
	}
	if held := run.SetAll(run.Fields("done_when", true), evidence...); held.Get("done_when") != nil {
		t.Fatalf("done_when = %v", held.Get("done_when"))
	}
}

func TestTheTestsLineSaysHowItEndedOnTheHeadAndCommitsNothing(t *testing.T) {
	for _, each := range []struct {
		command string
		ok      bool
		said    string
	}{{"true", true, "passed"}, {"touch made.txt; false", false, "FAILED"}} {
		l, p, _ := pullRig(t, "open")
		l.cmds = []string{each.command}
		l.every = l.cmds
		path := filepath.Join(l.roundDir(), "donewhen.log")
		ok, text, err := p.verify(l, path)
		if err != nil || ok != each.ok {
			t.Fatalf("%s: ok=%v err=%v", each.command, ok, err)
		}
		if !strings.HasPrefix(text, "Commit: "+p.sha+"\n") {
			t.Fatalf("%s: text = %q", each.command, text)
		}
		log, _ := os.ReadFile(filepath.Join(l.dir, "log.txt"))
		if want := fmt.Sprintf("tests (%s): %s\n", each.command, each.said); !strings.Contains(string(log), want) {
			t.Fatalf("log = %s, want %s", log, want)
		}
		if _, _, _, err := p.view(l, &judging{}, 0, 1); err != nil {
			t.Fatal(err)
		}
		if at := strings.TrimSpace(shell(t, p.wt, "git rev-parse HEAD")); at != p.sha {
			t.Fatalf("%s: the author's head moved to %s", each.command, at)
		}
	}
}

func TestWhatATestRewroteIsSavedAndUndoneBeforeTheReview(t *testing.T) {
	l, p, _ := pullRig(t, "open")
	shell(t, p.wt, "printf 'x = 2\\n' > widget.txt")
	if _, _, _, err := p.view(l, &judging{}, 0, 0); err != nil {
		t.Fatal(err)
	}
	if said := shell(t, p.wt, "cat widget.txt"); said != "x = 1\n" {
		t.Fatalf("widget.txt = %q", said)
	}
	if patch, _ := os.ReadFile(filepath.Join(l.dir, "tests-changes.patch")); !strings.Contains(string(patch), "+x = 2") {
		t.Fatalf("patch = %q", patch)
	}
}

func TestAHeadThatMovedDiscardsTheReviewAndNothingIsPosted(t *testing.T) {
	l, p, answers := pullRig(t, "open")
	// the author pushed after the review: the PR's branch has moved past the commit judged
	shell(t, p.wt, `git branch pushed "$(git commit-tree HEAD^{tree} -p HEAD -m pushed)"`)
	key := "api repos/acme/widget/pulls/1"
	answers[key] = strings.Replace(answers[key], `"ref":"ak/acme"`, `"ref":"pushed"`, 1)
	calls := fakeGH(t, answers)
	pull := &gh.Pull{Owner: "acme", Name: "widget", Number: "1", Author: "other-dev", Title: "Add contrib"}
	err := p.settleVerdict(l, pull)
	want := "the review was not posted to " + p.url + ": PR head changed or closed; discarded review; watcher will re-queue"
	if err == nil || err.Error() != want {
		t.Fatalf("err = %v", err)
	}
	record := recorded(t, l)
	if !record.Truthy("review_stale") || record.Truthy("review_posted") {
		t.Fatalf("stale=%v posted=%v", record.Get("review_stale"), record.Get("review_posted"))
	}
	if said, _ := os.ReadFile(calls); strings.Contains(string(said), "--method POST") {
		t.Fatalf("posted: %s", said)
	}
}

func TestAPassIsOfferedOnlyWithItsRequiredChecksGreen(t *testing.T) {
	rules := `[{"type":"required_status_checks","parameters":{"required_status_checks":[{"context":"ci"}]}}]`
	classic := `{"data":{"repository":{"ref":{"branchProtectionRule":null}}}}`
	for _, each := range []struct {
		name, runs, statuses, note string
		offered                    bool
	}{
		{"green", `{"check_runs":[{"id":1,"name":"ci","status":"completed","conclusion":"success","app":{"id":1,"slug":"x"}}]}`, `[]`, "merge question requires retry", true},
		{"red", `{"check_runs":[{"id":1,"name":"ci","status":"completed","conclusion":"failure","app":{"id":1,"slug":"x"}}]}`, `[]`, "not offered for merge: required checks failed: ci", false},
		{"a newer run decides", `{"check_runs":[{"id":2,"name":"ci","status":"completed","conclusion":"failure","app":{"id":1,"slug":"x"}},{"id":1,"name":"ci","status":"completed","conclusion":"success","app":{"id":1,"slug":"x"}}]}`, `[]`, "not offered for merge: required checks failed: ci", false},
		{"a failed status", `{"check_runs":[]}`, `[{"id":1,"context":"ci","state":"failure"}]`, "not offered for merge: required checks failed: ci", false},
		{"a green status", `{"check_runs":[]}`, `[{"id":1,"context":"ci","state":"success"}]`, "merge question requires retry", true},
	} {
		t.Run(each.name, func(t *testing.T) {
			l, p, answers := pullRig(t, "open")
			answers["rules/branches/main"], answers["api graphql"] = rules, classic
			answers["/check-runs"], answers["/statuses"] = each.runs, each.statuses
			fakeGH(t, answers)
			pull, err := gh.View(p.url)
			if err != nil {
				t.Fatal(err)
			}
			if err := p.offer(l, pull); err != nil {
				t.Fatal(err)
			}
			record := recorded(t, l)
			if record.Str("merge_note") != each.note || record.Truthy("pending_inbox") != each.offered {
				t.Fatalf("note=%q pending=%v", record.Str("merge_note"), record.Get("pending_inbox"))
			}
			if each.offered {
				asked := record.Dict("pending_inbox")
				if asked.Str("question") != "PR #1 by other-dev: Add contrib. Merge? yes/no" || asked.Str("sha") != p.sha || asked.Get("asked") != false || asked.Str("url") != p.url {
					t.Fatalf("pending = %v", asked)
				}
			}
		})
	}
}

func TestACheckStillOwedIsPendingAndACancelledJobIsAskedAgain(t *testing.T) {
	l, p, answers := pullRig(t, "open")
	answers["/check-runs"] = `{"check_runs":[{"id":7,"name":"ci","status":"completed","conclusion":"cancelled","app":{"id":1,"slug":"github-actions"}},{"id":8,"name":"lint","status":"in_progress","conclusion":null,"app":{"id":1,"slug":"x"}},{"id":9,"name":"other","status":"completed","conclusion":"success","app":{"id":2,"slug":"y"}}]}`
	answers["/rerun"] = `{}`
	calls := fakeGH(t, answers)
	pull, err := gh.View(p.url)
	if err != nil {
		t.Fatal(err)
	}
	need := wanted{"ci": {"1": true}, "lint": {"1": true}, "other": {"1": true}}
	rerun := map[string]int{}
	read, why, err := checkStates(l, pull, p.sha, need, rerun)
	if err != nil || why != "" {
		t.Fatalf("why=%s err=%v", why, err)
	}
	states := read.states
	if strings.Join(states["ci"], ",") != "pending" || strings.Join(states["lint"], ",") != "pending" || len(states["other"]) != 0 {
		t.Fatalf("states = %v", states)
	}
	said, _ := os.ReadFile(calls)
	if !strings.Contains(string(said), "actions/jobs/7/rerun") {
		t.Fatalf("calls = %s", said)
	}
}
