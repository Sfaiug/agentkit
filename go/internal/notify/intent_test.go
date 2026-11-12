//go:build unix

package notify

import (
	"crypto/sha256"
	"encoding/hex"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/history"
	"agentkit/internal/run"
)

// A done card writes its dones row as Python's _intent does: the done, the owner's first message
// since the conversation's previous done, the runs the seat started since, and the seat's finished
// work.
func TestADoneCardWritesItsDonesRow(t *testing.T) {
	home, write := questionHome(t)
	const start = 1793422800 // 2026-10-31T05:00:00Z
	write(seatFile("session", "acme", "json"), `{"orchestrator":"opus","cwd":"/code/acme","conversation":"conv-acme","created":1}`)
	write(seatFile("seat", "acme", "json"), `{"word":"done","reason":"API ships"}`)
	said := func(at string) string {
		return `{"type": "user", "timestamp": "2026-10-31T05:00:0` + at + `Z", "message": {"role": "user", "content": "ship it"}}`
	}
	write(filepath.Join(home, ".claude", "projects", "-code-acme", "conv-acme.jsonl"),
		strings.Join([]string{said("1"), said("3"), said("4")}, "\n")+"\n")
	for id, record := range map[string]string{
		"20261031-0500-early":    `{"launched_session": "acme", "started_at": 1793422802, "merged": true}`,
		"20261031-0501-fix-api":  `{"launched_session": "acme", "started_at": 1793422805}`,
		"20261031-0502-fix-docs": `{"launched_session": "beta", "started_at": 1793422805, "merged": true}`,
		"20261031-0503-nightly":  `{"launched_session": "acme", "started_at": 1793422805, "merged": true, "unattended": true}`,
	} {
		write(filepath.Join(home, ".agentkit", "runs", id, "run.json"), record)
	}
	// as Python leaves it in a home with seats: its seat tokens' table beside its own, the
	// conversation's previous done after the owner's first message
	conn, err := sqlite3.Open(history.Path())
	if err != nil {
		t.Fatal(err)
	}
	for _, statement := range []string{"CREATE TABLE kept (since REAL)", "INSERT INTO kept VALUES (0)",
		"CREATE TABLE dones (conversation TEXT, at REAL, began REAL, work TEXT)",
		"CREATE TABLE done_runs (conversation TEXT, at REAL, run_id TEXT)",
		"CREATE TABLE seat_sources (path TEXT PRIMARY KEY, harness TEXT, repo TEXT, cursor TEXT, account TEXT)",
		"INSERT INTO dones VALUES ('claude:conv-acme', 1793422802, NULL, 'what it did before')",
		"PRAGMA user_version=2"} {
		if err := conn.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	conn.Close()
	before := clock()
	if carried, err := TurnedPlan("acme", func(string) (string, any) { return "done", run.Float(clock()) },
		func(string) ([]any, error) {
			return []any{[]any{"acme/api", "API ships"}, []any{"acme/docs", "docs ship"}}, nil
		}); !carried || err != nil {
		t.Fatalf("carried=%v: %v", carried, err)
	}
	after := clock()
	if events, _ := filepath.Glob(filepath.Join(outbox(), "*.json")); len(events) != 1 {
		t.Fatalf("queued %d pages", len(events))
	}

	conn, err = sqlite3.Open(history.Path())
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	read := func(query string) (rows [][]any) {
		t.Helper()
		stmt, _, err := conn.Prepare(query)
		if err != nil {
			t.Fatal(err)
		}
		defer stmt.Close()
		for stmt.Step() {
			row := make([]any, stmt.ColumnCount())
			if err := stmt.Columns(row...); err != nil {
				t.Fatal(err)
			}
			rows = append(rows, row)
		}
		return rows
	}
	// the ticked lines and the runs the seat launched that merged, as json.dumps writes them
	sum := sha256.Sum256([]byte(`[[["acme/api", "API ships"], ["acme/docs", "docs ship"]], ["20261031-0500-early"]]`))
	dones := read("SELECT conversation, at, began, work FROM dones ORDER BY at")
	if len(dones) != 2 || len(dones[1]) != 4 {
		t.Fatalf("dones %v", dones)
	}
	at, _ := dones[1][1].(float64)
	if dones[1][0] != "claude:conv-acme" || at < before || at > after || dones[1][2] != float64(start+3) ||
		dones[1][3] != hex.EncodeToString(sum[:]) {
		t.Fatalf("done %v, at %v to %v", dones[1], before, after)
	}
	if runs := read("SELECT conversation, at, run_id FROM done_runs"); !slices.EqualFunc(runs,
		[][]any{{"claude:conv-acme", at, "20261031-0501-fix-api"}}, slices.Equal) {
		t.Fatalf("done_runs %v", runs)
	}
}
