package history

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

// A running row whose ending Python's finish_run writes more of than Go's is left to Python, its
// database as it was: the tokens of turns a harness receipt names, a merge's landing breaks, a
// record Go cannot read as Python does, and tokens waiting for Python's one-time repair.
func TestAgreeLeavesToPythonWhatItsEndingWritesMore(t *testing.T) {
	const ended = `{"run_id": "fix-api", "state": "pass", "finished_at": 2.5}`
	for name, files := range map[string]map[string]string{
		"a harness receipt": {"run.json": ended, "round-1/executor/harness": "claude\n"},
		"landing breaks":    {"run.json": `{"state": "pass", "merged": true, "landing_red_patches": ["a1"]}`},
		"a lone surrogate":  {"run.json": `{"state": "pass", "title": "\ud800"}`},
		"a recount owed":    {"run.json": ended, "round-1/executor/events.jsonl": "{}\n"},
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

// Seats' tokens are read where history.db keeps their sources, and where SQLite cannot say.
func TestKeepsSeatsReadsTheirSources(t *testing.T) {
	home(t)
	if !KeepsSeats() {
		t.Fatal("no database said no seats")
	}
	older(t)
	if KeepsSeats() {
		t.Fatal("found seats in a history without them")
	}
	write(t, "CREATE TABLE seat_sources (path TEXT PRIMARY KEY)")
	if !KeepsSeats() {
		t.Fatal("missed the seats' sources")
	}
}
