//go:build unix

package seat

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestAFrameOutOfUsageIsLeftBeforeFilingWrites(t *testing.T) {
	for name, frame := range map[string]func(now time.Time) bool{
		"the first frame": func(now time.Time) bool {
			_, known := Menu(now)
			return known
		},
		"an announced frame": func(now time.Time) bool {
			home, known := MenuRead(now)
			if !known {
				return false
			}
			err := home.Announce(now)
			if err != nil && !errors.Is(err, ErrUnread) {
				t.Fatal(err)
			}
			return err == nil
		},
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			framed(t, home, "acme")
			record(t, home, "acme", nil)
			project := filepath.Join(home, "code", "widget")
			if err := os.MkdirAll(project, 0o700); err != nil {
				t.Fatal(err)
			}
			runRecord(t, home, "fix-api", map[string]any{"state": "running", "repo": project})
			now := time.Now()
			write(t, stateFile(home, "seat-acme.json"), encoded(t, map[string]any{
				"usage_wait": map[string]any{"reason": "out of usage", "until": seconds(now) + 3600, "since": seconds(now) - 60, "continue": true},
			}))
			before := stateFiles(t, home)
			if frame(now) {
				t.Fatal("Go drew a seat out of usage")
			}
			if after := stateFiles(t, home); after["session-acme.json"] != before["session-acme.json"] {
				t.Fatalf("filing wrote before the frame was left: %s, then %s", before["session-acme.json"], after["session-acme.json"])
			}
		})
	}
}
