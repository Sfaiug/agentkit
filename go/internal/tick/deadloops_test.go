//go:build unix

package tick

import (
	"bytes"
	"errors"
	"io"
	"maps"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/host"
	"agentkit/internal/run"
)

// deadRun is a run record whose loop is a process that ran and was reaped: certainly gone.
func deadRun(t *testing.T, ak, id string, pairs ...any) {
	t.Helper()
	done := exec.Command("true")
	if err := done.Run(); err != nil {
		t.Fatal(err)
	}
	record := run.Fields("state", "running", "pid", done.Process.Pid,
		"process_identity", run.Fields("boot", "acme-boot", "ticks", 0, "started_at", 0), "worktree", t.TempDir())
	put(t, filepath.Join(ak, "runs", id, "run.json"), run.Line(run.SetAll(record, pairs...)))
}

func TestDeadLoopsLeaveAloneWhatPythonsPassLeavesAlone(t *testing.T) {
	ak, _ := idleHome(t, answers)
	now := epoch(time.Now())
	born, _ := host.ReadIdentity(os.Getpid())
	deadRun(t, ak, "stopped", "state", "stopped")
	deadRun(t, ak, "launching", "state", "queued", "launch_pending", true, "queued_at", now)
	deadRun(t, ak, "ordered", "stall_resume_at", now)
	deadRun(t, ak, "live", "pid", os.Getpid(), "process_identity", run.Fields("boot", born.Boot, "ticks", int(born.Ticks), "started_at", born.StartedAt))
	deadRun(t, ak, "workspaceless", "worktree", nil)
	deadRun(t, ak, "parked", "state", "interrupted", "deaths", []any{run.Fields("at", now, "parked", true)})
	deadRun(t, ak, "interrupted", "state", "interrupted")
	before := files(t, filepath.Join(ak, "runs"))
	var said bytes.Buffer
	tick := &ticking{log: newLog(&said, io.Discard), clock: time.Now}
	if err := tick.deadLoops(); err != nil || said.Len() > 0 || !maps.Equal(before, files(t, filepath.Join(ak, "runs"))) {
		t.Fatalf("%v: %s", err, &said)
	}
}

func TestDeadLoopsLeaveToPythonUnwrittenWhatGoDoesNotCarry(t *testing.T) {
	for name, pairs := range map[string][]any{
		"a unit's loop": {"scope", "agentkit-run-fix-api.scope", "memory_cap_mb", 1024},
		// no task and no pair to go on with: Python's resume, its order unwritten
		"a resume Go does not carry": {},
	} {
		t.Run(name, func(t *testing.T) {
			ak, _ := idleHome(t, answers)
			deadRun(t, ak, "fix-api", pairs...)
			before := files(t, filepath.Join(ak, "runs"))
			tick := &ticking{log: newLog(io.Discard, io.Discard), clock: time.Now}
			if err := tick.deadLoops(); !errors.Is(err, errLeft) || !maps.Equal(before, files(t, filepath.Join(ak, "runs"))) {
				t.Fatal(err)
			}
		})
	}
}

func TestDeadLoopsWarnOnceOfAGoneWorktree(t *testing.T) {
	ak, _ := idleHome(t, answers)
	gone := filepath.Join(t.TempDir(), "gone")
	deadRun(t, ak, "fix-api", "worktree", gone)
	var said bytes.Buffer
	tick := &ticking{log: newLog(&said, io.Discard), clock: time.Now}
	for range 2 {
		if err := tick.deadLoops(); err != nil {
			t.Fatal(err)
		}
	}
	record, _ := run.Read(filepath.Join(ak, "runs", "fix-api"))
	if said.String() != "WARN fix-api: worktree "+gone+" is gone; leaving it for an explicit resume\n" ||
		!record.Truthy("dead_worktree_warned") || strings.Contains(read(t, filepath.Join(ak, "runs", "fix-api", "run.json")), `"deaths"`) {
		t.Fatalf("%s\n%s", &said, run.Line(record))
	}
}
