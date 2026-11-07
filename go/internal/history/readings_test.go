package history

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

// A history whose tokens wait for Python's repair owes it, as one SQLite cannot read may: a reading
// Go took there would never be kept.  None standing, or Go's own, owes nothing.
func TestAHistoryOwedPythonsRepairIsOwed(t *testing.T) {
	home(t)
	if Owed() {
		t.Fatal("no database, yet owed")
	}
	Start(record(t, `{"run_id": "20261105-1200-fix-api", "state": "queued"}`), nil)
	if Owed() {
		t.Fatal("Go's own history owed")
	}
	write(t, "PRAGMA user_version=1")
	put(t, filepath.Join(run.Runs(), "20261105-1200-fix-api", "round-1", "executor-opus", "events.jsonl"), "")
	if !Owed() {
		t.Fatal("tokens waiting for Python's repair not owed")
	}
	os.WriteFile(Path(), []byte("not a database"), 0o600)
	if !Owed() {
		t.Fatal("an unreadable database not owed")
	}
}
