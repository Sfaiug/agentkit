//go:build unix

package tick

import (
	"io"
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/run"
)

func TestAQuestionLeavesAnUnknownLaunchAndBootRecoveryToPython(t *testing.T) {
	for _, boot := range []string{"", "previous-boot"} {
		t.Run("boot="+boot, func(t *testing.T) {
			ak, path := goneHome(t)
			record, _ := run.ReadJSON(path)
			cwd := filepath.Join(ak, "code", "acme")
			if err := os.MkdirAll(cwd, 0o700); err != nil {
				t.Fatal(err)
			}
			record.Set("cwd", cwd)
			put(t, path, run.Line(record))
			watch := filepath.Join(ak, "state", "watch.json")
			if boot != "" {
				put(t, watch, run.Line(run.Fields("boot_id", boot)))
			}
			asked := run.Float(epoch(time.Now()) - 300)
			put(t, filepath.Join(ak, "state", "notify-acme.json"), run.Line(run.Fields(
				"session", "acme", "kind", "needs", "text", "Which database?", "time", asked)))
			put(t, filepath.Join(ak, "state", "card-acme.json"), run.Line(run.Fields(
				"word", "needs you", "since", asked, "began", asked, "episode", "question", "sent", false)))
			if carries(io.Discard, io.Discard) {
				t.Fatal("a resumable seat's interrupted question skipped recovery")
			}
			if boot != "" {
				state, _ := run.ReadJSON(watch)
				if state.Str("boot_id") != boot {
					t.Fatal("the reboot was marked recovered before Python could reopen the seat")
				}
			}
		})
	}
}
