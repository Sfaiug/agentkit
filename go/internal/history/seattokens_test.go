package history

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/run"
)

func seatRecord(t *testing.T, name, text string) {
	t.Helper()
	path := filepath.Join(filepath.Dir(Path()), "state", "session-"+name+".json")
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil || os.WriteFile(path, []byte(text), 0o600) != nil {
		t.Fatal(path)
	}
}

// A home with no seat, and no sources a seat once named, gets no tables for them; one with a seat
// gets them, its seat's harness reading nothing or not.
func TestSeatTokensMakeTablesOnlyForSeats(t *testing.T) {
	home(t)
	if !SeatTokens() || !run.Historyless() {
		t.Fatal("a home with no seat got a history")
	}
	older(t, "PRAGMA user_version=2")
	seatRecord(t, "acme", `{"renamed": "beta"}`)
	if !SeatTokens() || keepsSources() {
		t.Fatal("a home with no seat got seat tables")
	}
	seatRecord(t, "beta", `{"orchestrator": "none"}`)
	if !SeatTokens() || !keepsSources() {
		t.Fatal("a seat's home got no seat tables")
	}
}

// A source is read on after no seat names it any more, each event once, its cursor in the same
// commit.
func TestSeatTokensReadASourceNoSeatNames(t *testing.T) {
	home(t)
	conversation := filepath.Join(t.TempDir(), "conversation.jsonl")
	said := `{"type": "assistant", "timestamp": "2026-11-05T09:00:05.250Z", "message": {"id": "msg_01acme", "usage": {"output_tokens": 40}}}` + "\n"
	if err := os.WriteFile(conversation, []byte(said+said), 0o600); err != nil {
		t.Fatal(err)
	}
	older(t, "PRAGMA user_version=2", "CREATE TABLE seat_sources (path TEXT PRIMARY KEY, harness TEXT, repo TEXT, cursor TEXT)",
		"INSERT INTO seat_sources VALUES ('"+conversation+"', 'claude', 'acme', '{}')")
	for range 2 {
		if !SeatTokens() {
			t.Fatal("left to Python")
		}
	}
	db, err := connect(Path(), sqlite3.OPEN_READONLY)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	usage := query(t, db, "SELECT * FROM seat_usage")
	if len(usage) != 1 || usage[0]["event"] != "claude:msg_01acme" || usage[0]["repo"] != "acme" || usage[0]["tokens"] != int64(40) ||
		usage[0]["output"] != int64(40) || usage[0]["account"] != nil || usage[0]["at"] != 1793869205.25 {
		t.Fatalf("%v", usage)
	}
	sources := query(t, db, "SELECT * FROM seat_sources")
	saved, _ := run.Decode([]byte(sources[0].Text("cursor")))
	if cursor, _ := saved.(*run.Object); len(sources) != 1 || cursor == nil || cursor.Str("source") != conversation || sources[0]["account"] != nil {
		t.Fatalf("%v", sources)
	} else if offset, _ := cursor.Int("offset"); offset != 2*len(said) {
		t.Fatalf("cursor %s", sources[0].Text("cursor"))
	}
}

// What Python's read writes more of than Go's is left to it, history.db as it was: a record Go
// cannot read as Python does, and tokens waiting for Python's one-time repair.
func TestSeatTokensLeaveToPythonWhatTheyCannotWrite(t *testing.T) {
	home(t)
	older(t)
	events := filepath.Join(filepath.Dir(Path()), "runs", "20261001-1200-fix-api", "round-1", "executor", "events.jsonl")
	if err := os.MkdirAll(filepath.Dir(events), 0o700); err != nil || os.WriteFile(events, []byte("{}\n"), 0o600) != nil {
		t.Fatal(events)
	}
	seatRecord(t, "acme", `{"orchestrator": "none"}`)
	data := read(Path())
	if SeatTokens() || !bytes.Equal(read(Path()), data) {
		t.Fatal("wrote before Python's repair")
	}
	home(t)
	seatRecord(t, "acme", `{"orchestrator": "none", "session_title": "\ud800"}`)
	if SeatTokens() || !run.Historyless() {
		t.Fatal("read a record Python reads otherwise")
	}
}
