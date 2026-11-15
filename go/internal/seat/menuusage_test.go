//go:build unix

package seat

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/run"
)

// frames are the readings of the ak screen: its first frame, one whose look announces each seat's
// word, and one taking the words as recorded.
var frames = map[string]func(t *testing.T, now time.Time) (Home, bool){
	"the first frame": func(_ *testing.T, now time.Time) (Home, bool) { return Menu(now) },
	"an announced frame": func(t *testing.T, now time.Time) (Home, bool) {
		return framedBy(t, now, Home.Announce)
	},
	"a recorded frame": func(t *testing.T, now time.Time) (Home, bool) {
		return framedBy(t, now, Home.Recorded)
	},
}

func framedBy(t *testing.T, now time.Time, take func(Home, time.Time) error) (Home, bool) {
	home, known := MenuRead(now)
	if !known {
		return Home{}, false
	}
	if err := take(home, now); err != nil {
		if !errors.Is(err, ErrUnread) {
			t.Fatal(err)
		}
		return Home{}, false
	}
	return home, true
}

func TestASeatOutOfUsageIsDrawnWithWhenItComesBack(t *testing.T) {
	for name, frame := range frames {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			framed(t, home, "acme")
			record(t, home, "acme", nil)
			now := time.Now()
			until := seconds(now) + 3600
			write(t, stateFile(home, "seat-acme.json"), encoded(t, map[string]any{
				"usage_wait": map[string]any{"reason": "out of usage", "until": until, "since": seconds(now) - 60, "continue": true},
			}))
			if name == "a recorded frame" { // as the tick's look wrote it down
				write(t, stateFile(home, "seat-acme.json"), encoded(t, map[string]any{"word": "out of usage",
					"usage_wait": map[string]any{"reason": "out of usage", "until": until, "since": seconds(now) - 60, "continue": true}}))
			}
			found, known := frame(t, now)
			if !known || len(found.Seats) != 1 {
				t.Fatalf("Go did not draw the seat: %v", found.Seats)
			}
			if seat := found.Seats[0]; seat.Word != "out of usage" || seat.Back(now) != backAt(run.Float(until), now) {
				t.Fatalf("%q, back %q", seat.Word, seat.Back(now))
			}
		})
	}
}

// Its squares are Python's to draw in out of usage's colour.
func TestAFrameWithARunWaitingForItsWindowIsLeftBeforeFilingWrites(t *testing.T) {
	for name, frame := range frames {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			framed(t, home, "acme")
			record(t, home, "acme", nil)
			project := filepath.Join(home, "code", "widget")
			if err := os.MkdirAll(project, 0o700); err != nil {
				t.Fatal(err)
			}
			runRecord(t, home, "fix-api", map[string]any{"state": "exhausted", "quota_dry": true, "repo": project,
				"error": "every pick out of usage"})
			before := stateFiles(t, home)
			if _, known := frame(t, time.Now()); known {
				t.Fatal("Go drew a run waiting for its window")
			}
			if after := stateFiles(t, home); after["session-acme.json"] != before["session-acme.json"] {
				t.Fatalf("filing wrote before the frame was left: %s, then %s", before["session-acme.json"], after["session-acme.json"])
			}
		})
	}
}
