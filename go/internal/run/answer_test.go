//go:build unix

package run

import (
	"context"
	"os/exec"
	"strings"
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

// unfired is a deadline passed whose timer has not fired yet, as on a loaded host.
type unfired struct {
	context.Context
	deadline time.Time
}

func (u unfired) Deadline() (time.Time, bool) { return u.deadline, true }

// Past the wait, exec gives up on output what the command started holds open, the shell's answer
// or not, and its session goes even before the deadline's timer has said so.
func TestPastTheWaitBeforeItsTimerFiresWhatTheCommandStartedGoesToo(t *testing.T) {
	var stopped atomic.Bool
	before := group
	group = func(cmd *exec.Cmd) func() {
		stop := before(cmd)
		return func() { stop(); stopped.Store(true) }
	}
	t.Cleanup(func() { group = before })
	for _, command := range []string{"sleep 5 & echo '[]'", "sleep 5 & exit 3"} {
		stopped.Store(false)
		wait := 100 * time.Millisecond
		ctx := unfired{context.Background(), time.Now().Add(wait)}
		if _, why := ProjectOutput(ctx, command, t.TempDir(), nil, wait, "list"); !strings.HasPrefix(why, "list: no answer in ") {
			t.Errorf("%s: said %q", command, why)
		}
		if !stopped.Load() {
			t.Errorf("%s: what it started still runs past the wait", command)
		}
	}
}
