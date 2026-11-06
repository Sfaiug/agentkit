package seat

import (
	"fmt"
	"testing"
)

// A parked error is rung 3's on a seat someone is in, worded by its parked line; a seat nobody is
// in owes it at Python's rung 4.
func TestAParkedErrorNeedsYouOnASeatSomeoneIsIn(t *testing.T) {
	for _, each := range []struct {
		name   string
		fields map[string]any
		reason string
	}{
		{"unscheduled error", map[string]any{"state": "error", "finished_at": seconds(moment) - 10, "error": "git fetch failed"},
			"run going parked: git fetch failed"},
		{"recovery error", map[string]any{"state": "error", "recovery_pending": true}, "run going parked: no reason was recorded"},
	} {
		for _, live := range []bool{false, true} {
			t.Run(fmt.Sprintf("%s/live=%v", each.name, live), func(t *testing.T) {
				home := sandbox(t)
				record(t, home, "acme", nil)
				if live {
					drawn(t, home, "acme", prompting)
				}
				runRecord(t, home, "going", each.fields)
				found, known := Menu(moment)
				if known != live || live && (len(found.Seats) != 1 || found.Seats[0].Word != "needs you" || found.Seats[0].reason != each.reason) {
					t.Fatalf("known %v, want %v: %+v", known, live, found.Seats)
				}
			})
		}
	}
}
