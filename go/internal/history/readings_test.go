package history

import (
	"path/filepath"
	"testing"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/run"
)

// Meter readings touch no tokens, so they go in where Python's repair of the tokens is owed, the
// database left owing it, while a write that may touch them is still refused.
func TestReadingsGoInBesideAnOwedRepair(t *testing.T) {
	home(t)
	Start(record(t, `{"run_id": "20261105-1200-fix-api", "state": "queued"}`), nil)
	write(t, "PRAGMA user_version=1")
	put(t, filepath.Join(run.Runs(), "20261105-1200-fix-api", "round-1", "executor-opus", "events.jsonl"), "")
	KeepReadings([][]any{{"anthropic", "default", "weekly_all", 30.0, nil, 604800.0, now(), "probe", nil}})
	if commit(func(*DB) error { return nil }) == nil {
		t.Fatal("a write that may touch tokens went in before the repair")
	}
	db, err := connect(Path(), sqlite3.OPEN_READONLY)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	if kept := query(t, db, "SELECT meter, used FROM meter_readings"); len(kept) != 1 || kept[0]["meter"] != "weekly_all" || kept[0]["used"] != 30.0 {
		t.Fatalf("kept %v", kept)
	}
	if version := query(t, db, "PRAGMA user_version"); version[0]["user_version"] != int64(1) {
		t.Fatalf("marked past the repair: %v", version)
	}
}
