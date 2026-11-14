package loop

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/history"
	"agentkit/internal/run"
	"agentkit/internal/sqlite"
)

// A run waiting for its slot stops, its row finished, in an older ak's history.db, which has no
// phases table; where that history's tokens wait for Python's repair, which only Python's write of
// the row makes, the stop is Python's, nothing written.
func TestAWaitingRunStopsOnAnOlderHistoryUnlessItsRepairIsOwed(t *testing.T) {
	for _, owed := range []bool{false, true} {
		l := rig(t, time.Minute)
		id := filepath.Base(l.dir)
		if err := run.Change(l.dir, func(record *run.Object) error {
			run.SetAll(record, "run_id", id, "state", "queued", "slot_waiting", true)
			return nil
		}); err != nil {
			t.Fatal(err)
		}
		older := "CREATE TABLE runs (run_id TEXT PRIMARY KEY, repo TEXT, executor TEXT, reviewer TEXT, " +
			"rounds_used INTEGER, final_state TEXT, verdict TEXT, started_at REAL, finished_at REAL, " +
			"executor_seconds REAL, done_when_seconds REAL, reviewer_seconds REAL, merge_seconds REAL, " +
			"total_seconds REAL, executor_tokens INTEGER, reviewer_tokens INTEGER, peak_rss_mb REAL, session TEXT); " +
			"INSERT INTO runs (run_id, final_state) VALUES ('" + id + "', 'running'), ('20251001-0000-old', 'pass')"
		if final := query(t, older, "SELECT final_state FROM runs WHERE run_id='"+id+"'"); final != "running" {
			t.Fatalf("made %q", final)
		}
		if owed {
			events := filepath.Join(run.Runs(), "20251001-0000-old", "round-1", "executor-opus", "events.jsonl")
			if os.MkdirAll(filepath.Dir(events), 0o777) != nil || os.WriteFile(events, []byte("{}\n"), 0o666) != nil {
				t.Fatal("no events")
			}
		}
		err := StopRun(id, true, io.Discard)
		record, _ := run.Read(l.dir)
		final := query(t, "", "SELECT final_state FROM runs WHERE run_id='"+id+"'")
		if owed && (!errors.Is(err, ErrPython) || record.Str("state") != "queued" || final != "running") ||
			!owed && (err != nil || record.Str("state") != "stopped" || final != "stopped") {
			log, _ := os.ReadFile(filepath.Join(l.dir, "log.txt"))
			t.Fatalf("owed %v: %v, record %s, row %s: %s", owed, err, record.Str("state"), final, log)
		}
	}
}

// query runs the statements on history.db, made where none stands, then the one text its select reads.
func query(t *testing.T, statements, selected string) string {
	t.Helper()
	db, err := sqlite.Open(history.Path(), sqlite3.OPEN_READWRITE|sqlite3.OPEN_CREATE)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	if statements != "" {
		if err := db.Exec(statements); err != nil {
			t.Fatal(err)
		}
	}
	stmt, _, err := db.Prepare(selected)
	if err != nil {
		t.Fatal(err)
	}
	defer stmt.Close()
	stmt.Step()
	return stmt.ColumnText(0)
}
