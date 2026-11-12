package cli

import (
	"path/filepath"
	"testing"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/sqlite"
)

// An older history.db, made by statements, beside the lock Python's writers leave there.
func olderHistory(t *testing.T, home, statements string) {
	t.Helper()
	write(t, filepath.Join(home, ".agentkit", "history.lock"), "")
	db, err := sqlite.Open(filepath.Join(home, ".agentkit", "history.db"), sqlite3.OPEN_READWRITE|sqlite3.OPEN_CREATE)
	if err == nil {
		err = db.Exec(statements)
	}
	if err != nil || db.Close() != nil {
		t.Fatal(err)
	}
}

// The machine form gives a run its row as an older table holds it, not as today's would, the
// record over it, a key both hold where the row put it; and HOME, history.db among it, stays as
// it was.
func TestTheMachineFormReadsHistoryWithoutWriting(t *testing.T) {
	home := sandbox(t)
	dir := filepath.Join(home, ".agentkit", "runs", "20261020-0900-fix-api")
	write(t, filepath.Join(dir, "run.json"), `{"run_id":"20261020-0900-fix-api","state":"pass","executor":"acme","finished_at":1e10}`)
	olderHistory(t, home, "CREATE TABLE runs (run_id TEXT PRIMARY KEY, executor TEXT, repo TEXT, executor_tokens INTEGER, "+
		"started_at REAL); INSERT INTO runs VALUES ('20261020-0900-fix-api', 'beta', '/src/acme', 600, 1.5)")
	assertCall(t, []string{"run", "status", "--json"}, 0, `[
  {
    "run_id": "20261020-0900-fix-api",
    "executor": "acme",
    "repo": "/src/acme",
    "executor_tokens": 600,
    "started_at": 1.5,
    "state": "pass",
    "finished_at": 10000000000.0,
    "tree_stopped": [
      null,
      null
    ],
    "paths": {
      "result": "`+dir+`/result.md",
      "record": "`+dir+`/run.json",
      "logs": "`+dir+`",
      "workspace": null,
      "workspace_present": false
    }
  }
]
`, "")
}

// Where Python's read would recount the tokens first, the command is Python's before the look
// that names the run marks it.
func TestTheMachineFormLeavesAnOwedRecountToPython(t *testing.T) {
	home := sandbox(t)
	dir := filepath.Join(home, ".agentkit", "runs", "20261020-0900-fix-api")
	write(t, filepath.Join(dir, "run.json"), `{"run_id":"20261020-0900-fix-api","state":"pass","finished_at":1e10}`)
	write(t, filepath.Join(dir, "round-1", "executor", "events.jsonl"), "")
	olderHistory(t, home, "CREATE TABLE runs (run_id TEXT PRIMARY KEY, executor_tokens INTEGER, reviewer_tokens INTEGER); "+
		"INSERT INTO runs VALUES ('20261020-0900-fix-api', 1, 0)")
	assertCall(t, []string{"run", "status", "20261020-0900-fix-api", "--json"}, 3, "", "ak run status: not implemented in Go yet\n")
}
