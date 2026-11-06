package seat

import (
	"fmt"
	"testing"
)

// A run only the owner moves is rung 3's on a seat someone is in, the oldest saying why; a seat
// nobody is in owes it at Python's rung 4.
func TestAParkedRunNeedsYouOnASeatSomeoneIsIn(t *testing.T) {
	for _, each := range []struct {
		name   string
		fields map[string]any
		reason string
	}{
		{"unscheduled error", map[string]any{"state": "error", "finished_at": seconds(moment) - 10, "error": "git fetch failed"},
			"run going parked: git fetch failed"},
		{"recovery error", map[string]any{"state": "error", "recovery_pending": true}, "run going parked: no reason was recorded"},
		{"stalled", map[string]any{"state": "stalled", "error": "stalled three times; parked: ak run resume going"},
			"run going stalled: resume it with `ak run resume going`"},
		{"expired merge wait", map[string]any{"state": "waiting", "finished_at": seconds(moment) - 172800, "error": "origin/main is red",
			"waiting_on": map[string]any{"ref": "origin/main", "sha": "abc123"}}, "run going waits to merge: origin/main is red"},
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

// A finished plan is not done while a run of its own sits undecided; a FAIL's reason, its rounds
// and findings, and a seat nobody is in are Python's.
func TestAnUndecidedRunKeepsAFinishedPlanTheOwners(t *testing.T) {
	for _, each := range []struct {
		name   string
		fields map[string]any
		reason string
	}{
		{"interruption", map[string]any{"state": "interrupted", "recovery_pending": true, "handed_back": seconds(moment) - 60,
			"interruption_reason": "the loop died mid-review."}, "run going parked: the loop died mid-review"},
		{"failed resume", map[string]any{"state": "fail", "recovery_pending": true, "handed_back": seconds(moment) - 60}, ""},
	} {
		for _, live := range []bool{false, true} {
			t.Run(fmt.Sprintf("%s/live=%v", each.name, live), func(t *testing.T) {
				home := sandbox(t)
				record(t, home, "acme", nil)
				write(t, stateFile(home, "plan-acme.md"), "- [x] The parser is shipped\n")
				if live {
					drawn(t, home, "acme", prompting)
				}
				runRecord(t, home, "going", each.fields)
				found, known := Menu(moment)
				want := live && each.reason != ""
				if known != want || want && (len(found.Seats) != 1 || found.Seats[0].Word != "needs you" || found.Seats[0].reason != each.reason) {
					t.Fatalf("known %v, want %v: %+v", known, want, found.Seats)
				}
			})
		}
	}
}
