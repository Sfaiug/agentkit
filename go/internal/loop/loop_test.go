//go:build linux

package loop

import (
	"context"
	"errors"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"

	"agentkit/internal/box"
	"agentkit/internal/handin"
	"agentkit/internal/run"
)

// TestMain is the box's first process where a check starts this test program as one.
func TestMain(m *testing.M) {
	if code, first := box.First(); first {
		os.Exit(code)
	}
	// the processes Start spawns, this program being what is running
	if len(os.Args) == 4 && os.Args[1] == "run" && os.Args[2] == DriveFlag {
		time.Sleep(time.Minute)
		os.Exit(0)
	}
	// a wake's `ak run resume`, which says where AK_TEST_WAKE_ENDED names that it ended, a moment on
	if len(os.Args) == 4 && os.Args[1] == "run" && os.Args[2] == "resume" {
		time.Sleep(200 * time.Millisecond)
		os.WriteFile(os.Getenv("AK_TEST_WAKE_ENDED"), nil, 0o644)
		os.Exit(0)
	}
	os.Exit(m.Run())
}

// rig is a loop on a run of its own under a fresh HOME, its workspace made and no Python near it.
func rig(t *testing.T, silence time.Duration) *loop {
	t.Helper()
	if err := box.Check(); err != nil {
		t.Skip(err)
	}
	home := t.TempDir()
	for key, value := range map[string]string{"HOME": home, "USERPROFILE": home, "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": ""} {
		t.Setenv(key, value)
	}
	dir := filepath.Join(home, ".agentkit", "runs", "20260101-0000-acme")
	workspace := filepath.Join(home, ".agentkit", "work", "20260101-0000-acme")
	for _, each := range []string{dir, workspace} {
		if err := os.MkdirAll(each, 0o777); err != nil {
			t.Fatal(err)
		}
	}
	if err := run.Create(dir, run.Fields("run_id", "acme", "state", "running")); err != nil {
		t.Fatal(err)
	}
	t.Setenv("AGENTKIT_RUN", dir)
	return &loop{ctx: context.Background(), dir: dir, id: "acme", workspace: workspace, place: scratch{}, silence: silence, ceiling: time.Hour, rnd: 1}
}

func (l *loop) checked(t *testing.T, cmds ...string) (bool, string) {
	t.Helper()
	ok, text, err := l.checks(cmds, filepath.Join(l.roundDir(), "donewhen.log"))
	if err != nil {
		t.Fatal(err)
	}
	written, _ := os.ReadFile(filepath.Join(l.roundDir(), "donewhen.log"))
	if string(written) != text {
		t.Fatalf("the log holds %q, the checks said %q", written, text)
	}
	return ok, text
}

func TestChecksWriteEachCommandsRecordAsPythonDoes(t *testing.T) {
	l := rig(t, time.Minute)
	ok, text := l.checked(t, "echo said; true", "exit 3", "true")
	if want := "$ echo said; true\n[exit 0]\nsaid\n\n$ exit 3\n[exit 3]\n\n$ true\n[exit 0]"; ok || text != want {
		t.Fatalf("ok=%v text=%q, want %q", ok, text, want)
	}
}

func TestACheckThatFailsRunsOnceMoreAndItsReRunDecides(t *testing.T) {
	l := rig(t, time.Minute)
	ok, text := l.checked(t, "test -f flag || { touch flag; echo bad; exit 1; }")
	if !ok || !strings.Contains(text, "[exit 0]\n\nflaky: ") || !strings.Contains(text, " failed, then passed on its re-run\nfailed output: ") || !strings.HasSuffix(text, "\nbad") {
		t.Fatalf("ok=%v text=%q", ok, text)
	}
	if found, _ := filepath.Glob(filepath.Join(l.dir, "donewhen-failed-*.log")); len(found) != 1 {
		t.Fatalf("the failed run's whole output: %v", found)
	}
}

func TestASilentCheckIsStoppedSayingWhatStillRan(t *testing.T) {
	l := rig(t, 3*time.Second)
	ok, text := l.checked(t, "echo begun; sleep 30", "touch never")
	if ok || !strings.Contains(text, "[killed at the limit]\nbegun") || !strings.Contains(text, "(last output: begun); still running: sleep 30, and the commands after it") {
		t.Fatalf("ok=%v text=%q", ok, text)
	}
	if _, err := os.Stat(filepath.Join(l.workspace, "never")); err == nil {
		t.Fatal("a command ran after the stop")
	}
}

func TestAChildHoldingACheckOutputStillCounts(t *testing.T) {
	l := rig(t, time.Minute)
	if ok, text := l.checked(t, "(sleep 1; echo late) & echo early"); !ok || !strings.HasSuffix(text, "early\nlate") {
		t.Fatalf("ok=%v text=%q", ok, text)
	}
}

func TestACheckWritesItsWorkspaceAndOnlyAThrowawayHome(t *testing.T) {
	l := rig(t, time.Minute)
	if ok, text := l.checked(t, "touch ~/leak here && test -f ~/leak"); !ok {
		t.Fatalf("text=%q", text)
	}
	home, _ := os.UserHomeDir()
	if _, err := os.Stat(filepath.Join(home, "leak")); err == nil {
		t.Fatal("a check wrote the account's home")
	}
	if _, err := os.Stat(filepath.Join(l.workspace, "here")); err != nil {
		t.Fatal(err)
	}
}

func TestOutputPastTheCapIsItsEndUnderALineNamingAllOfIt(t *testing.T) {
	l := rig(t, time.Minute)
	ok, text := l.checked(t, "yes acme | head -c 50000")
	if !ok || !strings.Contains(text, "[only part of this output is shown; all of it is in "+l.dir+"/donewhen-whole-") || len(text) > outCap+500 {
		t.Fatalf("ok=%v, %d bytes: %.200q", ok, len(text), text)
	}
}

func TestChecksPastTheCeilingAreNotRun(t *testing.T) {
	l := rig(t, time.Minute)
	l.ceiling = 0
	ok, text := l.checked(t, "true")
	if ok || !strings.Contains(text, "$ true\n[not run: the done-when limit was already spent]") || !strings.Contains(text, "(the limit was spent before it could start), and the commands") {
		t.Fatalf("ok=%v text=%q", ok, text)
	}
}

func TestAStopOnTheRecordEndsTheChecksAndEveryWrite(t *testing.T) {
	l := rig(t, time.Minute)
	if err := run.Change(l.dir, func(record *run.Object) error { record.Set("state", "stopped"); return nil }); err != nil {
		t.Fatal(err)
	}
	if _, _, err := l.checks([]string{"touch never"}, filepath.Join(l.roundDir(), "donewhen.log")); err != errStop {
		t.Fatalf("got %v", err)
	}
	if code := l.finish(l.save(func(record *run.Object) { record.Set("title", "acme") })); code != 1 {
		t.Fatalf("exit %d", code)
	}
	if record, _ := run.Read(l.dir); record.Str("state") != "stopped" || record.Has("title") || record.Has("error") {
		t.Fatalf("record %s", run.Line(record))
	}
}

func TestASignalWithNoStopLeavesAnOrdinaryDeadLoop(t *testing.T) {
	l := rig(t, time.Minute)
	ctx, cancel := context.WithCancelCause(context.Background())
	cancel(errors.New("the driver got SIGTERM"))
	l.ctx = ctx
	if code := l.finish(l.stopCheck()); code != 1 {
		t.Fatalf("exit %d", code)
	}
	if record, _ := run.Read(l.dir); record.Str("state") != "running" || record.Truthy("error") {
		t.Fatalf("record %s", run.Line(record))
	}
	if _, err := os.Stat(filepath.Join(l.dir, "result.md")); !errors.Is(err, fs.ErrNotExist) {
		t.Fatalf("a result: %v", err)
	}
}

func TestEndLeavesAStopAndAnEndingAsTheyStand(t *testing.T) {
	for state, want := range map[string]int{"stopped": 1, "pass": 1, "error": 2} {
		l := rig(t, time.Minute)
		if err := run.Change(l.dir, func(record *run.Object) error { record.Set("state", state); return nil }); err != nil {
			t.Fatal(err)
		}
		if code := End(l.dir, "too late"); code != want {
			t.Fatalf("%s: exit %d", state, code)
		}
		if record, _ := run.Read(l.dir); record.Str("state") != state || record.Has("error") || record.Has("tree_stopped") {
			t.Fatalf("record %s", run.Line(record))
		}
		if _, err := os.Stat(filepath.Join(l.dir, "result.md")); err == nil {
			t.Fatalf("%s: a result written over it", state)
		}
	}
}

func TestFollowLeavesARunItsDriverLeftGoingAndSaysSo(t *testing.T) {
	l := rig(t, time.Minute)
	t.Setenv("AGENTKIT_RUN", "")
	if err := Start(l.dir, io.Discard, true); err != nil {
		t.Fatal(err)
	}
	before, _ := run.Read(l.dir)
	pid, _ := before.Int("pid")
	if before.Has("driver") || before.Has("deaths") || before.Has("thawed_at") {
		t.Fatalf("record %s", run.Line(before))
	}
	if err := syscall.Kill(pid, syscall.SIGKILL); err != nil {
		t.Fatal(err)
	}
	var out, errOut strings.Builder
	if code := Follow(l.dir, 0, &out, &errOut); code != 1 {
		t.Fatalf("exit %d", code)
	}
	if errOut.String() != "the run's driver died; ak's tick carries it on\n" {
		t.Fatalf("stderr %q", errOut.String())
	}
	if after, _ := run.Read(l.dir); run.Line(after) != run.Line(before) {
		t.Fatalf("record %s, was %s", run.Line(after), run.Line(before))
	}
}

func TestFollowExitsAsPythonsFollowRunForAnEnding(t *testing.T) {
	for state, want := range map[string]int{"error": 2, "not_needed": 0, "stopped": 1, "blocked": 1, "fail": 1, "interrupted": 1, "pass": 1} {
		l := rig(t, time.Minute)
		if err := run.Change(l.dir, func(record *run.Object) error { record.Set("state", state); return nil }); err != nil {
			t.Fatal(err)
		}
		appendLog(l.dir, "")
		var errOut strings.Builder
		if code := Follow(l.dir, 0, io.Discard, &errOut); code != want || errOut.Len() > 0 {
			t.Errorf("%s: exit %d, stderr %q", state, code, errOut.String())
		}
	}
}

func TestEndSaysItsReasonAndSweepsOnce(t *testing.T) {
	l := rig(t, time.Minute)
	t.Setenv("AGENTKIT_RUN", "")
	if code := End(l.dir, "acme"); code != 2 {
		t.Fatalf("exit %d", code)
	}
	record, _ := run.Read(l.dir)
	if !record.Has("tree_stopped") {
		t.Fatalf("record %s", run.Line(record))
	}
	log, _ := os.ReadFile(filepath.Join(l.dir, "log.txt"))
	if strings.Count(string(log), "ERROR acme") != 1 || strings.Count(string(log), "FAIL -> ") != 1 {
		t.Fatalf("log %q", log)
	}
}

// room is a read with room for every model.
type room struct{}

func (room) Spent(string) string             { return "" }
func (room) Budget(string) (float64, string) { return 1, "" }
func (room) OnCredits(string) bool           { return false }
func (room) Pace(string) (float64, bool)     { return 0, true }

func TestEveryPickStaysInTheListsTheRunWasLaunchedWith(t *testing.T) {
	l := rig(t, time.Minute)
	settings := `[defaults]
orchestrator = "astra"
workers = ["astra"]
reviewers = ["astra"]
[models.opus]
harness = "claude"
model = "opus"
effort = "high"
provider = "anthropic"
[models.astra]
harness = "codex"
model = "astra"
effort = "high"
provider = "openai"
[providers.anthropic]
mode = "subscription"
[providers.openai]
mode = "subscription"
`
	if err := os.WriteFile(filepath.Join(os.Getenv("HOME"), ".agentkit", "config.toml"), []byte(settings), 0o666); err != nil {
		t.Fatal(err)
	}
	rules, ok := l.rules()
	if executor, _, _ := rules.Pair(room{}); !ok || executor != "astra" {
		t.Fatalf("no list bound: %q", executor)
	}
	l.workers, l.reviewers = []string{"opus"}, []string{"opus"}
	rules, ok = l.rules()
	if !ok {
		t.Fatal("no rules")
	}
	if executor, reviewer, _ := rules.Pair(room{}); executor != "opus" || reviewer != "opus" {
		t.Fatalf("picked %q and %q", executor, reviewer)
	}
	if writers := []string{"opus"}; !rules.Wrote(rules.Beside(room{}, writers, nil)[0], writers) {
		t.Fatal("no other reviewer to take the review over, yet one is offered")
	}
}

func TestANamedExecutorThatCannotRunIsRefusedBeforeAnyMeterIsRead(t *testing.T) {
	l := rig(t, time.Minute)
	t.Setenv("PATH", t.TempDir())
	settings := `[defaults]
orchestrator = "opus"
workers = ["opus"]
[models.opus]
harness = "claude"
model = "opus"
effort = "high"
provider = "anthropic"
[providers.anthropic]
mode = "subscription"
`
	if err := os.WriteFile(filepath.Join(os.Getenv("HOME"), ".agentkit", "config.toml"), []byte(settings), 0o666); err != nil {
		t.Fatal(err)
	}
	if err := run.Change(l.dir, func(record *run.Object) error {
		record.Set("launch_opts", run.Fields("--exec", "opus"))
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	if err := l.pick(); err == nil || err.Error() != "opus cannot run here: claude is not installed" {
		t.Fatalf("refused with %v", err)
	}
}

func TestReviewerRecordsAreWeighedAsPythonWeighsAScratchRun(t *testing.T) {
	l := rig(t, time.Minute)
	if err := os.MkdirAll(filepath.Join(l.roundDir()), 0o777); err != nil {
		t.Fatal(err)
	}
	finding := func(kind string, evidence *run.Object) *run.Object {
		return run.Fields("kind", kind, "path", "a", "line", 1, "what", "w", "why", "y", "evidence", evidence)
	}
	proof := func(command string) *run.Object { return run.Fields("run", command, "returncode", 1, "output", "") }
	weighed, err := l.weigh(&handin.Review{Records: []*run.Object{
		finding("finding", run.Fields("quote", "q")), finding("finding", proof("true")), finding("finding", proof("false")),
		finding("follow-up", proof("false")), run.Fields("kind", "done"),
	}}, &judging{})
	if err != nil {
		t.Fatal(err)
	}
	for i, want := range []string{
		`{"kind": "note", "path": "a", "line": 1, "what": "w", "why": "y", "evidence": {"quote": "q"}, "handed": "finding"}`,
		`{"kind": "note", "path": "a", "line": 1, "what": "w", "why": "y", "evidence": {"run": "true", "commit": "workspace", "returncode": 0, "output": "", "killed": false}, "handed": "finding"}`,
		`{"kind": "finding", "path": "a", "line": 1, "what": "w", "why": "y", "evidence": {"run": "false", "commit": "workspace", "returncode": 1, "output": "", "killed": false}}`,
		`{"kind": "note", "path": "a", "line": 1, "what": "w", "why": "y", "evidence": {"run": "false", "returncode": 1, "output": ""}, "dropped": "no base commit", "handed": "follow-up"}`,
		`{"kind": "done"}`,
	} {
		if got := run.Line(weighed.Records[i]); got != want {
			t.Errorf("record %d: got %s, want %s", i, got, want)
		}
	}
	if weighed.Verdict() != "FAIL" || len(weighed.Notes()) != 3 {
		t.Fatalf("verdict %s, notes %v", weighed.Verdict(), weighed.Notes())
	}
}

func TestDeliverablesAreLinksWhateverTheName(t *testing.T) {
	root := t.TempDir()
	for _, name := range []string{"b/c d.txt", "a[1]+.txt", "é\tx"} {
		path := filepath.Join(root, name)
		os.MkdirAll(filepath.Dir(path), 0o777)
		if err := os.WriteFile(path, []byte("x"), 0o666); err != nil {
			t.Fatal(err)
		}
	}
	want := "- [a\\[1\\]+.txt](" + root + "/a%5B1%5D%2B.txt)\n- [b/c d.txt](" + root + "/b/c%20d.txt)\n- [é%09x](" + root + "/%C3%A9%09x)"
	if got := links(root); got != want {
		t.Fatalf("got %q, want %q", got, want)
	}
	if got := listing(root); !strings.HasPrefix(got, "         1  a[1]+.txt\n         1  b/c d.txt\n") {
		t.Fatalf("listing %q", got)
	}
	if got := links(t.TempDir()); got != "(the workspace is empty)" {
		t.Fatalf("empty %q", got)
	}
}

func TestAFindingsSectionLeavesItsAsidesOut(t *testing.T) {
	got := withoutAsides("VERDICT: FAIL\n\n## Findings\n- one\n\n## Notes\n- two\n")
	if want := "VERDICT: FAIL\n\n## Findings\n- one\n\n"; got != want {
		t.Fatalf("got %q, want %q", got, want)
	}
}
