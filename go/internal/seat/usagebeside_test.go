package seat

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// A finished seat's wait on its usage that news its screen shows would keep standing goes to
// Python before its look writes anything, where what the seat said since its plan finished is a
// conversation Go does not read: whether the wait stands is decided only once the screen is read.
func TestAWaitNewsWouldKeepIsPythonsBeforeTheLookWrites(t *testing.T) {
	for _, news := range []string{"a run's ending", "a wait over"} {
		t.Run(news, func(t *testing.T) {
			home := sandbox(t)
			write(t, filepath.Join(home, ".agentkit", "config.toml"), grokConfig)
			record(t, home, "acme", map[string]any{"orchestrator": "nova", "workers": []string{"nova"}})
			pane, err := os.ReadFile(filepath.Join("..", "..", "..", "tests", "fixtures", "grok-prompt-pane.txt"))
			if err != nil {
				t.Fatal(err)
			}
			rows := strings.Split(strings.TrimRight(string(pane), "\n"), "\n")
			drawn(t, home, "acme", strings.Join(rows[len(rows)-6:], "\n")+"\n")
			write(t, stateFile(home, "plan-acme.md"), "- [x] The parser is shipped\n")
			now := seconds(time.Now())
			marks := map[string]any{"usage_wait": map[string]any{"reason": "test out of usage", "until": now + 3600, "since": now - 60}}
			if news == "a run's ending" {
				runRecord(t, home, "fix-api", map[string]any{"state": "fail", "handback_pending": true, "finished_at": now - 60})
			} else {
				marks["wait"] = map[string]any{"kind": "pr", "on": "https://github.com/acme/widget/pull/1", "over": true, "at": now - 60}
			}
			file := stateFile(home, "seat-acme.json")
			write(t, file, encoded(t, marks))
			before, _ := os.ReadFile(file)
			if _, err := LookedLive(stateFile(home, ""), "acme"); !errors.Is(err, ErrUnread) {
				t.Fatalf("Go took it: %v", err)
			}
			if after, _ := os.ReadFile(file); string(after) != string(before) {
				t.Fatalf("the seat's file became %s", after)
			}
		})
	}
}
