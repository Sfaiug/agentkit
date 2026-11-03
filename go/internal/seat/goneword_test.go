package seat

import (
	"reflect"
	"testing"

	"agentkit/internal/run"
)

func TestGoneSeatIgnoresItsOldScreenAndUsesItsPlan(t *testing.T) {
	for _, each := range []struct {
		plan, file, word, reason string
	}{
		{"", `{"state":"asking","evidence":"old question","unsent":"old draft"}`, "idle", closedOne},
		{"- [x] First\n- [ ] Last\n", `{"state":"working"}`, "needs you", closedOne},
		{"- [x] First\n- [x] Last\n", `{"state":"working"}`, "done", "Last"},
		{"- [ ] Last\n", `{"stopped_at":1,"closed_by_owner":true}`, "idle", "session closed by the owner: reopen it from past sessions"},
	} {
		t.Run(each.word+each.plan, func(t *testing.T) {
			home := sandbox(t)
			record(t, home, "acme", nil)
			write(t, stateFile(home, "seat-acme.json"), each.file)
			if each.plan != "" {
				write(t, stateFile(home, "plan-acme.md"), each.plan)
			}
			found, known := Looking(moment)
			if !known {
				t.Fatal("gone seat not read")
			}
			lines, listed, err := found.Explain("acme", moment)
			if err != nil || !listed || !reflect.DeepEqual(lines, []string{"acme  " + each.word, "  reason:    " + each.reason,
				"  authority: -     the process is gone; nothing here read its screen"}) {
				t.Fatalf("%v, listed=%v: %v", lines, listed, err)
			}
			file, _ := run.ReadJSON(stateFile(home, "seat-acme.json"))
			if file.Str("unsent") != "" || !run.Equal(file.Get("word_from"), []any{nil, nil, ""}) {
				t.Fatal(run.Line(file))
			}
		})
	}
}

func TestGoneSeatKeepsTheRunRungAboveTheOwnerClose(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	write(t, stateFile(home, "seat-acme.json"), `{"stopped_at":1,"closed_by_owner":true}`)
	runRecord(t, home, "r-build", map[string]any{"state": "running", "started_at": 1})
	found, known := Looking(moment)
	if !known || len(found.Seats) != 1 || found.Seats[0].Word != "working" {
		t.Fatalf("known=%v: %+v", known, found.Seats)
	}
}

func TestGoneSeatOwnershipStaysTheSameAfterListing(t *testing.T) {
	for _, closed := range []bool{false, true} {
		t.Run(run.Line(closed), func(t *testing.T) {
			home := sandbox(t)
			record(t, home, "acme", map[string]any{"id_source": nil, "resumable": false})
			if closed {
				write(t, stateFile(home, "seat-acme.json"), `{"stopped_at":1,"closed_by_owner":true}`)
			}
			want := 0
			if closed {
				want = 1
			}
			for range 2 {
				found, known := Looking(moment)
				if !known || len(found.Seats) != want {
					t.Fatalf("closed=%v known=%v: %+v", closed, known, found.Seats)
				}
				if err := found.Announce(moment); err != nil {
					t.Fatal(err)
				}
			}
			record, _ := run.ReadJSON(stateFile(home, "session-acme.json"))
			if record.Truthy("conversation") || record.Truthy("resumable") {
				t.Fatal(run.Line(record))
			}
		})
	}
}
