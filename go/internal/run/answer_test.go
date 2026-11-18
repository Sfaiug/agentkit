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
	"syscall"
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

// Past ctx's deadline, read by the clock before ctx's timer says so and well inside the project's
// own wait, the session goes before the shell is reaped, never after: from the reap on, the
// session's number is a stranger's to take.
func TestPastTheWaitTheSessionGoesBeforeTheShellIsReaped(t *testing.T) {
	for _, command := range []string{
		"exec >/dev/null 2>&1; sleep 5", // the shell outlives its output
		"sleep 5 & echo '[]'",           // the shell ends while what it started holds the output
	} {
		t.Run(command, func(t *testing.T) {
			seen := recorded(t)
			checkout := t.TempDir()
			ctx := unfired{context.Background(), time.Now().Add(100 * time.Millisecond)}
			if _, why := ProjectOutput(ctx, command, checkout, nil, time.Minute, "list"); !strings.HasPrefix(why, "list: no answer in ") {
				t.Errorf("said %q", why)
			}
			if went := seen(); !slices.Equal(went, []string{"stop", "reap"}) {
				t.Errorf("went %v", went)
			}
		})
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

// A deadline passed by the time the shell has started runs nothing, even before its timer has said
// so: the command would make its change after its time was up.
func TestPastItsDeadlineOnceStartedBeforeItsTimerFiresTheCommandNeverRuns(t *testing.T) {
	dir := t.TempDir()
	ctx := unfired{context.Background(), time.Now().Add(100 * time.Millisecond)}
	syscall.ForkLock.Lock() // the fork waits for it, as on a loaded host, until past the deadline
	time.AfterFunc(time.Until(ctx.deadline), syscall.ForkLock.Unlock)
	if _, why := ProjectOutput(ctx, "printf started > ran", dir, nil, time.Second, "list"); !strings.HasPrefix(why, "list: no answer in ") {
		t.Errorf("said %q", why)
	}
	if _, err := os.Stat(filepath.Join(dir, "ran")); !os.IsNotExist(err) {
		t.Errorf("the command ran past its deadline: %v", err)
	}
}

// A command is what the shell runs, never options to it: -n or +x would answer nothing as if it had
// run, and -i would read the shell's startup file.
func TestACommandIsNeverTheShellsOptions(t *testing.T) {
	for _, command := range []string{"-n", "+x", "-i"} {
		if _, why := ProjectOutput(context.Background(), command, t.TempDir(), nil, time.Minute, "list"); why == "" {
			t.Errorf("%s answered as if it had run", command)
		}
	}
}

// Given no environment, the command runs in ak's own, at its checkout, still without the seat's
// name: an ssh in it would otherwise be that seat reaching the live host.
func TestGivenNoEnvironmentTheCommandCarriesAksOwnButNoSeatsName(t *testing.T) {
	t.Setenv("AGENTKIT_SESSION", "acme")
	t.Setenv("ACME_TOKEN", "kept")
	// The PWD ak gives the shell is read, in a checkout no TMPDIR names, not the one the shell
	// prints: for a PWD that does not reach its directory a shell prints the directory's own
	// name, so $PWD would tell the checkout's from ak's own only under a link in a temp
	// directory, and whether that link's name reaches it from inside is TMPDIR's to decide
	t.Setenv("PWD", "/acme") // ak's own, so never the checkout's by chance
	var env []string
	before := group
	group = func(cmd *exec.Cmd) func() { env = cmd.Env; return before(cmd) }
	t.Cleanup(func() { group = before })
	out, why := ProjectOutput(context.Background(), `printf '%s %s\n' "${AGENTKIT_SESSION-absent}" "$ACME_TOKEN"`, "/", nil, time.Second, "list")
	if why != "" || string(out) != "absent kept\n" {
		t.Errorf("answered %q, said %q", out, why)
	}
	if !slices.Contains(env, "PWD=/") {
		t.Error("its PWD is not its checkout")
	}
}

// An environment exec refuses starts nothing: the command would run without what it was given.
func TestAMalformedEnvironmentStartsNothing(t *testing.T) {
	dir := t.TempDir()
	if _, why := ProjectOutput(context.Background(), "printf started > ran", dir, []string{"ACME_MODE=preview\x00"}, time.Second, "set"); why == "" {
		t.Error("answered as if it ran")
	}
	if _, err := os.Stat(filepath.Join(dir, "ran")); !os.IsNotExist(err) {
		t.Errorf("the command ran: %v", err)
	}
}
