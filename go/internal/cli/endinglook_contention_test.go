package cli

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/lock"
	"agentkit/internal/run"
)

type unlockingLookOutput struct {
	bytes.Buffer
	held *os.File
}

func (out *unlockingLookOutput) WriteString(text string) (int, error) {
	if out.held != nil {
		out.held.Close()
		out.held = nil
	}
	return out.Buffer.WriteString(text)
}

func TestAContendedLookLeavesItsDeliveryAfterTheLockIsReleasedDuringOutput(t *testing.T) {
	for size, reason := range map[string]string{
		"short":   "The parser already keeps the last row.",
		"compact": strings.Repeat("The parser already keeps the last row. ", 100),
	} {
		for _, verb := range []string{"status", "wait"} {
			t.Run(size+"/"+verb, func(t *testing.T) {
				home := sandbox(t)
				t.Setenv("AGENTKIT_SESSION", "acme")
				t.Setenv("AK_HOST_READINGS", `{"free_mb":4096,"mem_total_mb":16384,"load":1,"cpus":8}`)
				dir := filepath.Join(home, ".agentkit", "runs", "r")
				record := run.Fields("state", "not_needed", "not_needed", reason,
					"launched_session", "acme", "handback_pending", true)
				write(t, filepath.Join(dir, "run.json"), run.Encode(record))
				held, err := lock.Try(filepath.Join(dir, "delivery.lock"))
				if err != nil {
					t.Fatal(err)
				}
				defer held.Close()
				shown := &unlockingLookOutput{held: held}
				var other bytes.Buffer
				code, want := 0, 0
				if verb == "status" {
					code = Main([]string{"run", "status", "r"}, shown, &other)
				} else {
					code, want = Main([]string{"wait", "r"}, &other, shown), 1
				}
				if code != want || shown.held != nil || !strings.Contains(shown.String(), "  run r finished DONE") {
					t.Fatalf("exit=%d output=%s stderr=%s", code, shown.String(), other.String())
				}
				after, _ := run.Read(dir)
				if !run.Waits(after) || after.Truthy("handed_back") {
					t.Fatal("the look took over the contended delivery", run.Line(after))
				}
				if _, err := os.Stat(filepath.Join(dir, "result.md")); !os.IsNotExist(err) {
					t.Fatal("the look saved a notice for the contended delivery", err)
				}
			})
		}
	}
}
