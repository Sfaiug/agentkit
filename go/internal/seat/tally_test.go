package seat

import "testing"

func TestRunningSeatsCountEndingsWithoutInventingMerges(t *testing.T) {
	for _, each := range []struct {
		name, state, want string
		fields            map[string]any
	}{
		{"blocked", "blocked", "1 running · 1 needs you", nil},
		{"failed", "fail", "1 running · 1 needs you", nil},
		{"undelivered", "pass", "1 running · 1 needs you", nil},
		{"not needed", "not_needed", "1 running · 0 merged", nil},
		{"stopped", "stopped", "1 running · 0 merged", nil},
		{"merged", "pass", "1 running · 1 merged", map[string]any{"merged": true}},
		{"aged out", "fail", "1 running · 0 merged", map[string]any{"finished_at": seconds(moment) - 8*86400}},
		{"acknowledged", "fail", "1 running · 0 merged", map[string]any{"recovery_acknowledged_at": 1}},
		{"handed back", "blocked", "1 running · 0 merged", map[string]any{"handed_back": true}},
		{"no merge", "pass", "1 running · 0 merged", map[string]any{"no_merge": true}},
		{"queued", "queued", "2 running · 0 merged", nil},
	} {
		t.Run(each.name, func(t *testing.T) {
			home := sandbox(t)
			record(t, home, "acme", nil)
			runRecord(t, home, "going", map[string]any{"state": "running"})
			fields := map[string]any{"state": each.state, "repo": "/code/acme", "finished_at": seconds(moment) - 60}
			for key, value := range each.fields {
				fields[key] = value
			}
			runRecord(t, home, "ended", fields)
			found, known := Looking(moment)
			if !known || len(found.Seats) != 1 {
				t.Fatalf("known %v; %d seats", known, len(found.Seats))
			}
			if got := found.Seats[0]; got.Word != "working" || got.Tally != each.want {
				t.Fatalf("%s: %s; want working: %s", got.Word, got.Tally, each.want)
			}
		})
	}
}

func TestSeatTalliesReadReplacementsAcrossSeats(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	record(t, home, "beta", nil)
	runRecord(t, home, "going", map[string]any{"state": "running"})
	runRecord(t, home, "failed", map[string]any{"state": "fail", "title": "Fix api", "finished_at": seconds(moment) - 120})
	runRecord(t, home, "merged", map[string]any{"state": "pass", "title": "Fix api", "finished_at": seconds(moment) - 60,
		"launched_session": "beta", "merged": true, "handed_back": true})
	found, known := Looking(moment)
	if !known || len(found.Seats) != 2 {
		t.Fatalf("known %v; %d seats", known, len(found.Seats))
	}
	if a, b := found.Seats[0].Tally, found.Seats[1].Tally; a != "1 running · 0 merged" || b != "0 running · 1 merged" {
		t.Fatalf("acme: %s; beta: %s", a, b)
	}
}
