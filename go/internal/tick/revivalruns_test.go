//go:build unix

package tick

import (
	"io"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/run"
	"agentkit/internal/seat"
)

func TestRevivalLeavesOtherGoingRunsToGoneSeatRecovery(t *testing.T) {
	for _, state := range []string{"waiting", "error"} {
		for _, work := range []string{`{}`, `{"state":"working"}`, `{"holds":["background work"]}`, `{"state":"asking"}`} {
			t.Run(state+"/"+work, func(t *testing.T) {
				ak := revivalHome(t)
				path := filepath.Join(ak, "state", "seat-acme.json")
				put(t, path, work)
				if work == `{"state":"asking"}` {
					put(t, filepath.Join(ak, "state", "notify-acme.json"), `{"kind":"needs","text":"Which database?","time":100}`)
				}
				record := run.Fields("state", state, "run_id", "r-build", "launched_session", "acme",
					"finished_at", run.Float(epoch(time.Now())), "waiting_on", run.Fields("line", "acme"),
					"error_retry_at", run.Float(epoch(time.Now())+60))
				runPath := filepath.Join(ak, "runs", "r-build", "run.json")
				put(t, runPath, run.Line(record))
				if home, known := seat.Looking(time.Now()); !known || len(home.Seats) != 1 || home.Seats[0].Word != "working" {
					t.Fatal("the seat's going run was not readable")
				}
				tick := &ticking{log: newLog(io.Discard, io.Discard), clock: time.Now}
				for _, row := range table(tick) {
					if row.name != "seat revival" {
						continue
					}
					after := false
					if tick.through([]pass{row, {"after", false, nil, func() error { after = true; return nil }}}) || after {
						t.Fatal("a run outside automatic revival skipped gone-seat recovery")
					}
					if read(t, path) != work || read(t, runPath) != run.Line(record) {
						t.Fatal("handover changed the seat or its run")
					}
					return
				}
				t.Fatal("revival row missing")
			})
		}
	}
}

func TestRunRevivalTakesOnlyTheRunNamedByItsSharedIndex(t *testing.T) {
	for _, state := range []string{"queued", "running"} {
		t.Run(state, func(t *testing.T) {
			ak := revivalHome(t)
			path := filepath.Join(ak, "state", "seat-acme.json")
			put(t, path, `{}`)
			put(t, filepath.Join(ak, "runs", "r-ahead", "run.json"), `{"state":"waiting","launched_session":"acme","waiting_on":{"line":"acme"}}`)
			put(t, filepath.Join(ak, "runs", "r-build", "run.json"), run.Line(run.Fields(
				"state", state, "launched_session", "acme", "unattended", true)))
			revivalAt(t, time.Now())
			file, _ := run.ReadJSON(path)
			notice, _ := run.ReadJSON(filepath.Join(ak, "state", "notify-acme.json"))
			if len(file.List("reopened_at")) != 1 || !strings.HasPrefix(notice.Str("source"), "revive:acme:r-build:") {
				t.Fatalf("the indexed run did not claim revival: seat=%s notice=%s", run.Line(file), run.Line(notice))
			}
		})
	}
}
