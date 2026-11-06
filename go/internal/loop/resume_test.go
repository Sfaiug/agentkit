//go:build linux

package loop

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/handin"
	"agentkit/internal/run"
)

// turnIn writes the files of one role's turn in the round, by name.
func turnIn(t *testing.T, round, name string, files map[string]string) {
	t.Helper()
	out := filepath.Join(round, name)
	if err := os.MkdirAll(out, 0o777); err != nil {
		t.Fatal(err)
	}
	for file, text := range files {
		if err := os.WriteFile(filepath.Join(out, file), []byte(text), 0o666); err != nil {
			t.Fatal(err)
		}
	}
}

const closed = `{"kind":"turn","role":"executor","workspace":"/w","findings":[]}` + "\n" + `{"kind":"done"}` + "\n"

func TestATurnGoesOnWhereItWasCutOff(t *testing.T) {
	round := t.TempDir()
	turnIn(t, round, "reviewer", map[string]string{"session_id": "sid-a\n"})
	if kind, session := openTurn(round, "reviewer"); kind != "resume" || session != "sid-a" {
		t.Fatalf("no answer yet: %q %q", kind, session)
	}
	turnIn(t, round, "reviewer", map[string]string{"final.md": "done\n"})
	if kind, _ := openTurn(round, "reviewer"); kind != "" {
		t.Fatalf("a reviewer's answer finished it: %q", kind)
	}
	if out := filepath.Base(freeDir(round, "reviewer")); out != "reviewer-attempt2" {
		t.Fatalf("the next attempt: %s", out)
	}
	turnIn(t, round, "reviewer-attempt2", nil)
	if kind, session := openTurn(round, "reviewer"); kind != "fresh" || session != "" {
		t.Fatalf("no conversation recorded: %q %q", kind, session)
	}
	turnIn(t, round, "executor", map[string]string{"final.md": "answer\n", handin.File: closed})
	if kind, _ := openTurn(round, "executor"); kind != "" {
		t.Fatalf("a closing finished it: %q", kind)
	}
	turnIn(t, round, "fixer", map[string]string{"session_id": "sid-b"})
	if name, kind, session := openWorker(round); name != "fixer" || kind != "resume" || session != "sid-b" {
		t.Fatalf("the fixer cut off: %q %q %q", name, kind, session)
	}
	if name, _, _ := openReview(round); name != "reviewer" {
		t.Fatalf("the open review: %q", name)
	}
}

func TestAResumedConversationIsToldTheHostEndedIt(t *testing.T) {
	at := time.Date(2026, 11, 3, 1, 2, 3, 0, time.Local)
	for name, record := range map[string]*run.Object{
		"its death":        run.Fields("deaths", []any{run.Fields("at", run.Float(float64(at.Unix())))}, "interrupted_at", run.Float(1)),
		"its interruption": run.Fields("interrupted_at", run.Float(float64(at.Unix()))),
	} {
		if got := hostEnded(record); !strings.HasPrefix(got, "Your process was ended by the host at 2026-11-03 01:02:03, not by you; ") {
			t.Errorf("%s: %q", name, got)
		}
	}
}

func TestAPointGoCannotPickUpFromIsPythons(t *testing.T) {
	summary := []any{}
	base := func(more ...any) *run.Object {
		return run.SetAll(run.Fields("rounds", 3, "round_summaries", summary, "findings_file", ""), more...)
	}
	for name, setup := range map[string]struct {
		record *run.Object
		turns  map[string]map[string]string
		want   bool
	}{
		"the next round's start":    {base(), nil, true},
		"an executor cut off":       {base(), map[string]map[string]string{"executor": {"session_id": "s"}}, true},
		"a fixer cut off":           {base(), map[string]map[string]string{"executor": {"final.md": "a", handin.File: closed}, "fixer": {"session_id": "s"}}, true},
		"an answer with no closing": {base(), map[string]map[string]string{"executor": {"final.md": "a"}}, false},
		"a refusal waited out":      {base("state", "exhausted", "quota_dry", true), map[string]map[string]string{"executor": {"final.md": "a", "session_id": "s"}}, true},
		"the checks cut off":        {base(), map[string]map[string]string{"executor": {"final.md": "a", handin.File: closed}}, true},
		"a review with no pending":  {base(), map[string]map[string]string{"reviewer": {"session_id": "s"}}, false},
		"a retry of Python's":       {base(), map[string]map[string]string{"executor": {"session_id": "s"}, "executor-retry-1": {}}, false},
		"a review pending":          {base("review_pending", run.Fields("round", 1, "summary", "s", "failed", []any{})), nil, true},
		"an integration's review":   {base("review_pending", run.Fields("round", 1, "summary", "s", "reason", "why")), nil, false},
		"a landing's review":        {base("review_pending", run.Fields("round", 1, "summary", "s", "reason", "why", "record", false)), nil, true},
		"a landing's review handed": {base("review_pending", run.Fields("round", 1, "summary", "s", "record", false, "handed", true)), nil, false},
		"a review past the budget":  {base("review_pending", run.Fields("round", 4, "summary", "s")), nil, false},
		"a budget spent":            {run.Fields("rounds", 0, "round_summaries", summary), nil, false},
	} {
		t.Run(name, func(t *testing.T) {
			l := rig(t, time.Minute)
			setup.record.Set("run_id", l.id)
			for turn, files := range setup.turns {
				turnIn(t, filepath.Join(l.dir, "round-1"), turn, files)
			}
			if got := point(l.dir, setup.record); got != setup.want {
				t.Fatalf("got %v", got)
			}
		})
	}
}

func TestReopenRecordsTheDeathAndHandsTheRecordToANewDriver(t *testing.T) {
	l := rig(t, time.Minute)
	if err := run.Change(l.dir, func(record *run.Object) error {
		run.SetAll(record, "state", "running", "pid", 999999, "handed_back", true, "error", "old", "reported", true)
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	read, _ := run.Read(l.dir)
	moved := read.Copy()
	moved.Set("pid", 1)
	if err := Reopen(l.dir, moved, nil); !errors.Is(err, ErrChanged) {
		t.Fatalf("a record that moved: %v", err)
	}
	if err := Reopen(l.dir, read, nil); err != nil {
		t.Fatal(err)
	}
	record, _ := run.Read(l.dir)
	if record.Str("state") != "queued" || record.Str("resume_from") != "interrupted" || !record.Truthy("recovery_pending") ||
		record.Truthy("error") || record.Truthy("reported") || record.Has("handed_back") || !record.Truthy("interrupted_at") {
		t.Fatalf("record %s", run.Line(record))
	}
	if deaths := record.List("deaths"); len(deaths) != 1 {
		t.Fatalf("deaths %v", deaths)
	}
}

func TestAStopSaysWhatBecameOfTheBranchAndARepeatSaysTheSame(t *testing.T) {
	l, r := repoRig(t)
	id := filepath.Base(l.dir)
	if err := run.Change(l.dir, func(record *run.Object) error {
		run.SetAll(record, "state", "running", "launched_session", "acme")
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	var first, again bytes.Buffer
	if err := StopRun(id, true, &first); err != nil {
		t.Fatal(err)
	}
	if want := "stopped " + id + ": branch ak/acme kept; relaunch with from: ak/acme\n"; first.String() != want {
		t.Fatalf("said %q", first.String())
	}
	if err := StopRun(id, false, &again); err != nil || again.String() != first.String() {
		t.Fatalf("again %q: %v", again.String(), err)
	}
	if _, err := os.Stat(r.wt); err != nil {
		t.Fatalf("the kept checkout: %v", err)
	}
	record, _ := run.Read(l.dir)
	if record.Str("state") != "stopped" || record.Str("verdict") != "STOPPED" || record.Str("error") != run.Why || !record.Truthy("stop_kept") || !record.Truthy("reported") {
		t.Fatalf("record %s", run.Line(record))
	}
	log, _ := os.ReadFile(filepath.Join(l.dir, "log.txt"))
	if !strings.Contains(string(log), "stopped "+id+"\n") {
		t.Fatalf("log %q", log)
	}
}

func TestAStopRefusesAnEndingAndLeavesToPythonWhatIsNotGos(t *testing.T) {
	for name, setup := range map[string]struct {
		fields []any
		file   string
		want   string
	}{
		"an ending":        {[]any{"state", "pass"}, "", "is already pass; only unfinished work can be stopped"},
		"a job's":          {[]any{"state", "running", "job_id", "batch"}, "", "python"},
		"a review's":       {[]any{"state", "running", "review_pr", "https://github.com/acme/api/pull/1"}, "", "python"},
		"under a unit":     {[]any{"state", "running", "scope", "agentkit-run-x.scope"}, "", "python"},
		"a history unread": {[]any{"state", "running"}, "history.db", "python"},
		"a live program":   {[]any{"state", "running", "pid", os.Getpid(), "process_identity", Identity(os.Getpid())}, "", "python"},
		"parked":           {[]any{"state", "stopped", "lease_wait", run.Fields("on", "x")}, "", "python"},
	} {
		t.Run(name, func(t *testing.T) {
			l := rig(t, time.Minute)
			if err := run.Change(l.dir, func(record *run.Object) error {
				run.SetAll(record, setup.fields...)
				return nil
			}); err != nil {
				t.Fatal(err)
			}
			if setup.file != "" {
				if err := os.WriteFile(filepath.Join(os.Getenv("HOME"), ".agentkit", setup.file), nil, 0o666); err != nil {
					t.Fatal(err)
				}
			}
			before, _ := os.ReadFile(filepath.Join(l.dir, "run.json"))
			var out bytes.Buffer
			err := StopRun(filepath.Base(l.dir), false, &out)
			switch {
			case setup.want == "python" && !errors.Is(err, ErrPython), setup.want != "python" && (err == nil || !strings.HasSuffix(err.Error(), setup.want)):
				t.Fatalf("got %v", err)
			}
			after, _ := os.ReadFile(filepath.Join(l.dir, "run.json"))
			if out.Len() != 0 || !bytes.Equal(before, after) {
				t.Fatalf("said %q, record now %s", out.String(), after)
			}
		})
	}
}

// fromRig is a checkout cut from a branch that holds wip.txt, with main moved on.
func fromRig(t *testing.T, onMain string) (*loop, *repoPlace) {
	t.Helper()
	l, r := repoRig(t)
	shell(t, r.wt, "printf 'wip\\n' > wip.txt && git add -A && git commit -q -m wip")
	shell(t, r.repo, onMain+" && git add -A && git commit -q -m moved")
	return l, r
}

func TestABranchTakesInItsTargetBeforeRoundOne(t *testing.T) {
	l, r := fromRig(t, "printf 'notes\\n' > notes.txt")
	before := r.baseSHA
	if err := r.takeInTarget(l); err != nil {
		t.Fatal(err)
	}
	if r.baseSHA == before {
		t.Fatal("the base stayed")
	}
	record, _ := run.Read(l.dir)
	if record.Str("base_sha") != r.baseSHA {
		t.Fatalf("record %s", run.Line(record))
	}
	for _, name := range []string{"wip.txt", "notes.txt"} {
		if _, err := os.Stat(filepath.Join(r.wt, name)); err != nil {
			t.Fatal(err)
		}
	}
	log, _ := os.ReadFile(filepath.Join(l.dir, "log.txt"))
	for _, line := range []string{"from: merging local main (" + r.baseSHA[:12] + ") into ak/acme before round 1", "from: merged local main into ak/acme before round 1"} {
		if !strings.Contains(string(log), line) {
			t.Fatalf("log %q", log)
		}
	}
}

func TestAConflictLeavesTheBranchAsItWasForLanding(t *testing.T) {
	l, r := fromRig(t, "printf 'other\\n' > wip.txt")
	head := shell(t, r.wt, "git rev-parse HEAD")
	if err := r.takeInTarget(l); err != nil {
		t.Fatal(err)
	}
	if now := shell(t, r.wt, "git rev-parse HEAD"); now != head || shell(t, r.wt, "git status --porcelain") != "" {
		t.Fatalf("the branch moved to %s", now)
	}
	log, _ := os.ReadFile(filepath.Join(l.dir, "log.txt"))
	if !strings.Contains(string(log), "from: local main conflicts; merge aborted, branch unchanged; origin/main will be taken in at landing") {
		t.Fatalf("log %q", log)
	}
}

func TestARunFromABranchContinuesItsChangeAndItsBudget(t *testing.T) {
	first, r := repoRig(t)
	second := filepath.Join(filepath.Dir(first.dir), "20260102-0000-acme")
	if err := os.MkdirAll(second, 0o777); err != nil {
		t.Fatal(err)
	}
	if err := run.Create(second, run.Fields("run_id", "20260102-0000-acme", "policy", run.Fields("rounds", 3))); err != nil {
		t.Fatal(err)
	}
	if change := run.ChangeOn("no-such", r.repo, second); change != nil {
		t.Fatalf("a free name: %v", change)
	}
	if err := run.Change(first.dir, func(record *run.Object) error {
		record.Set("run_id", filepath.Base(first.dir))
		record.Set("round_summaries", []any{run.Fields("round", 1), run.Fields("round", 2)})
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	change := run.ChangeOn("ak/acme", r.repo, second)
	if change != filepath.Base(first.dir) {
		t.Fatalf("change %v", change)
	}
	record, _ := run.Read(second)
	if left, why, err := run.BranchLeft(record, second, change, "ak/acme", 3, time.Now()); err != nil || left != 1 || why != "" {
		t.Fatalf("left %d, %q: %v", left, why, err)
	}
	if err := run.Change(first.dir, func(record *run.Object) error {
		record.Set("round_summaries", []any{run.Fields("round", 1), run.Fields("round", 2), run.Fields("round", 3)})
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	if left, why, _ := run.BranchLeft(record, second, change, "ak/acme", 3, time.Now()); left != 0 || !strings.Contains(why, "3 review rounds spent on branch ak/acme across 1 run: 3 per pull request") {
		t.Fatalf("left %d, %q", left, why)
	}
	record.Set("change", change)
	if !run.ChangeReviewed(record) {
		t.Fatal("its first review is behind it")
	}
}
