package history

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

// A running row whose ending Python's finish_run writes more of than Go's is left to Python, its
// database as it was: a merge's landing breaks, a record Go cannot read as Python does, and tokens
// waiting for Python's one-time repair.
func TestAgreeLeavesToPythonWhatItsEndingWritesMore(t *testing.T) {
	const ended = `{"run_id": "fix-api", "state": "pass", "finished_at": 2.5}`
	for name, files := range map[string]map[string]string{
		"landing breaks":   {"run.json": `{"state": "pass", "merged": true, "landing_red_patches": ["a1"]}`},
		"a lone surrogate": {"run.json": `{"state": "pass", "title": "\ud800"}`},
		"a recount owed":   {"run.json": ended, "round-1/executor/events.jsonl": "{}\n"},
	} {
		t.Run(name, func(t *testing.T) {
			home(t)
			statements := []string{"INSERT INTO runs (run_id, final_state) VALUES ('fix-api', 'running')"}
			if name != "a recount owed" {
				statements = append(statements, "PRAGMA user_version=2")
			}
			older(t, statements...)
			for path, text := range files {
				path = filepath.Join(filepath.Dir(Path()), "runs", "fix-api", path)
				if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(path, []byte(text), 0o600); err != nil {
					t.Fatal(err)
				}
			}
			data, wal := read(Path()), read(Path()+"-wal")
			if Agree(nil) {
				t.Fatal("carried it")
			}
			if !bytes.Equal(read(Path()), data) || !bytes.Equal(read(Path()+"-wal"), wal) {
				t.Fatal("history.db changed")
			}
		})
	}
}

// A history whose tokens wait for Python's one-time repair, or that SQLite cannot read as it
// stands, is Python's to sync though no row of it runs: Python's connect brings it round first.
// One without runs runs none.
func TestAgreeLeavesToPythonAHistoryToBringRound(t *testing.T) {
	home(t)
	write(t, "CREATE TABLE notes (body TEXT)")
	if !Agree(nil) {
		t.Fatal("left a history without runs to Python")
	}
	older(t, "INSERT INTO runs (run_id, final_state) VALUES ('fix-api', 'pass')")
	put(t, filepath.Join(filepath.Dir(Path()), "runs", "fix-api", "round-1", "executor", "events.jsonl"), "{}\n")
	if Agree(nil) {
		t.Fatal("carried tokens owed their repair")
	}
	put(t, Path(), "not a database")
	if Agree(nil) {
		t.Fatal("carried a history SQLite cannot read")
	}
}
