//go:build unix

package tick

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/run"
)

// A run parked on a login: while the login is out its earlier stamps come off; once the `auth`
// verb says yes, the login back goes on the record, a paced launch waits, a gone worktree is an
// interruption, and a resume Go does not carry is Python's, unwritten.  A dry tick writes nothing.
func TestALoginParkedRunGoesOnOnlyOnAYes(t *testing.T) {
	gone := "/acme/gone"
	for _, each := range []struct {
		name   string
		yes    bool
		dry    bool
		record string
		left   bool
		said   string
		after  func(*run.Object) bool // nil: the record is as the tick read it
	}{
		{"out, its stamps come off", false, false, `"login_back_at":1,"login_resume_at":1`, false, "fix-api: the claude login went out again",
			func(after *run.Object) bool {
				return !after.Has("login_back_at") && !after.Has("login_resume_at") && after.Has("waiting_for")
			}},
		{"out on a dry tick", false, true, `"login_back_at":1`, true, "", nil},
		{"back, paced", true, false, `"login_resume_at":NOW`, false, "",
			func(after *run.Object) bool {
				return after.Truthy("login_back_at") && after.Str("state") == "waiting_login"
			}},
		{"back, worktree gone", true, false, `"worktree":"` + gone + `","login_back_at":1`, false, "WARN fix-api: The claude login is back, but this run's worktree " + gone + " is gone; it cannot be resumed where it stopped.",
			func(after *run.Object) bool {
				return after.Str("state") == "interrupted" && after.Truthy("recovery_pending") && strings.Contains(after.Str("interruption_reason"), gone) &&
					!after.Has("waiting_for") && !after.Has("login_back_at")
			}},
		{"back, worktree gone, dry", true, true, `"worktree":"` + gone + `"`, false, "would interrupt fix-api: the claude login is back but its worktree " + gone + " is gone", nil},
		{"back, dry", true, true, `"worktree":"WORKTREE"`, false, "would resume fix-api: claude can authenticate again", nil},
		{"back, a resume Go does not carry", true, false, `"worktree":"WORKTREE"`, true, "", nil},
	} {
		t.Run(each.name, func(t *testing.T) {
			ak, _ := idleHome(t, answers)
			adapters := t.TempDir()
			t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
			answer := "printf 'Not logged in\\n'; exit 1"
			if each.yes {
				answer = "printf 'logged in\\n'"
			}
			put(t, filepath.Join(adapters, "claude.sh"), "#!/bin/sh\n"+answer+"\n")
			if err := os.Chmod(filepath.Join(adapters, "claude.sh"), 0o700); err != nil {
				t.Fatal(err)
			}
			now := time.Now()
			fields := strings.NewReplacer("NOW", fmt.Sprintf("%.3f", epoch(now)-1), "WORKTREE", t.TempDir()).Replace(each.record)
			path := filepath.Join(ak, "runs", "fix-api", "run.json")
			put(t, path, `{"state":"waiting_login","waiting_for":"claude",`+fields+`}`)
			before := read(t, path)
			var out bytes.Buffer
			err := (&ticking{log: newLog(&out, io.Discard), clock: func() time.Time { return now }, dry: each.dry}).loginResume()
			if errors.Is(err, errLeft) != each.left || err != nil && !each.left {
				t.Fatalf("handed over: %v", err)
			}
			if !strings.Contains(out.String(), each.said) || each.said == "" && out.Len() > 0 {
				t.Fatalf("said %q", &out)
			}
			after, _ := run.Read(filepath.Dir(path))
			if each.after == nil && read(t, path) != before || each.after != nil && !each.after(after) {
				t.Fatalf("left %s", read(t, path))
			}
		})
	}
}
