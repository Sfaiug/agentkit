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
