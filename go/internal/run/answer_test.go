//go:build unix

package run

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// Past the wait, the stop the deadline sets off has ended by the time the answer says so: one still
// going after would hold what it reads open in ak, and stop what the command left behind late.
func TestPastTheWaitTheStopHasEndedBeforeTheAnswer(t *testing.T) {
	var ended atomic.Bool
	before := group
	group = func(cmd *exec.Cmd) func() {
		stop := before(cmd)
		return func() { time.Sleep(500 * time.Millisecond); stop(); ended.Store(true) }
	}
	t.Cleanup(func() { group = before })
	// what it started holds the output open past the wait, until the stop ends it
	_, why := ProjectOutput(context.Background(), "sleep 5 & echo '[]'", t.TempDir(), nil, 100*time.Millisecond, "list")
	if !strings.HasPrefix(why, "list: no answer in ") {
		t.Errorf("said %q", why)
	}
	if !ended.Load() {
		t.Error("answered while the deadline's stop still went on")
	}
}

// recorded has group and reap note each stop as it begins and each reap of a shell found ended,
// in order: what the run saw, as seen() gives it.
func recorded(t *testing.T) (seen func() []string) {
	var lock sync.Mutex
	var notes []string
	note := func(what string) { lock.Lock(); notes = append(notes, what); lock.Unlock() }
	stopping, reaping := group, reap
	group = func(cmd *exec.Cmd) func() {
		stop := stopping(cmd)
		return func() { note("stop"); stop() }
	}
	reap = func(cmd *exec.Cmd, wait bool) (bool, int, error) {
		ended, code, err := reaping(cmd, wait)
		if ended {
			note("reap")
		}
		return ended, code, err
	}
	t.Cleanup(func() { group, reap = stopping, reaping })
	return func() []string { lock.Lock(); defer lock.Unlock(); return slices.Clone(notes) }
}

// unfired is a deadline passed whose timer has not fired yet, as on a loaded host.
type unfired struct {
	context.Context
	deadline time.Time
}

func (u unfired) Deadline() (time.Time, bool) { return u.deadline, true }

// Past the wait, read by the clock before ctx's timer says so, the session goes before the shell
// is reaped, never after: from the reap on, the session's number is a stranger's to take.
func TestPastTheWaitTheSessionGoesBeforeTheShellIsReaped(t *testing.T) {
	for _, command := range []string{
		"exec >/dev/null 2>&1; sleep 5", // the shell outlives its output
		"sleep 5 & echo '[]'",           // the shell ends while what it started holds the output
	} {
		t.Run(command, func(t *testing.T) {
			seen := recorded(t)
			wait := 100 * time.Millisecond
			ctx := unfired{context.Background(), time.Now().Add(wait)}
			if _, why := ProjectOutput(ctx, command, t.TempDir(), nil, wait, "list"); !strings.HasPrefix(why, "list: no answer in ") {
				t.Errorf("said %q", why)
			}
			if went := seen(); !slices.Equal(went, []string{"stop", "reap"}) {
				t.Errorf("went %v", went)
			}
		})
	}
}

// A shell a look finds ended has answered, the look coming once the deadline has passed as well:
// what the look finds decides, never the instant it comes.
func TestAShellFoundEndedPastTheDeadlineHasAnswered(t *testing.T) {
	seen := recorded(t)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	looking, looked := reap, false
	reap = func(cmd *exec.Cmd, _ bool) (bool, int, error) {
		if !looked {
			// the first look finds the shell still running, then the deadline passes
			looked = true
			cancel()
			return false, 0, nil
		}
		// the next finds it ended, as the end of its output says it is or soon will be
		return looking(cmd, true)
	}
	out, why := ProjectOutput(ctx, "echo '[]'", t.TempDir(), nil, time.Minute, "list")
	if why != "" || strings.TrimSpace(string(out)) != "[]" {
		t.Errorf("answered %q, said %q", out, why)
	}
	if went := seen(); !slices.Equal(went, []string{"reap"}) {
		t.Errorf("went %v", went)
	}
}

// A deadline already passed starts nothing, even before its timer has said so: the command would
// make its change after its time was up.
func TestPastItsDeadlineBeforeItsTimerFiresTheCommandNeverStarts(t *testing.T) {
	dir := t.TempDir()
	ctx := unfired{context.Background(), time.Now().Add(-time.Second)}
	if _, why := ProjectOutput(ctx, "printf started > ran", dir, nil, time.Second, "list"); !strings.HasPrefix(why, "list: no answer in ") {
		t.Errorf("said %q", why)
	}
	if _, err := os.Stat(filepath.Join(dir, "ran")); !os.IsNotExist(err) {
		t.Errorf("the command ran past its deadline: %v", err)
	}
}
