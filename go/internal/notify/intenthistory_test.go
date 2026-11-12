//go:build unix

package notify

import (
	"path/filepath"
	"testing"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/history"
	"agentkit/internal/run"
)

// A done card in a home with no history.db makes one, as Python's history._write does, holding its
// dones row: a fresh history keeps dones from its start, so the owner's first message begins it.
func TestADoneCardMakesHistoryWhereNoneStands(t *testing.T) {
	home, write := questionHome(t)
	write(seatFile("session", "acme", "json"), `{"orchestrator":"opus","cwd":"/code/acme","conversation":"conv-acme","created":1}`)
	write(seatFile("seat", "acme", "json"), `{"word":"done","reason":"API ships"}`)
	write(filepath.Join(home, ".claude", "projects", "-code-acme", "conv-acme.jsonl"),
		`{"type": "user", "timestamp": "2026-10-31T05:00:01Z", "message": {"role": "user", "content": "ship it"}}`+"\n")
	if carried, err := TurnedPlan("acme", func(string) (string, any) { return "done", run.Float(clock()) },
		func(string) ([]any, error) { return []any{[]any{"acme/api", "API ships"}}, nil }); !carried || err != nil {
		t.Fatalf("carried=%v: %v", carried, err)
	}

	conn, err := sqlite3.OpenFlags(history.Path(), sqlite3.OPEN_READONLY)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	stmt, _, err := conn.Prepare("SELECT conversation, began FROM dones")
	if err != nil {
		t.Fatal(err)
	}
	defer stmt.Close()
	if !stmt.Step() || stmt.ColumnText(0) != "claude:conv-acme" || stmt.ColumnFloat(1) != 1793422801 || stmt.Step() {
		t.Fatalf("dones: %v", stmt.Err())
	}
}
