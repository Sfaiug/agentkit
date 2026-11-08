package harness

import (
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"testing"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/sqlite"
)

// An OpenCode seat's owner words are its session's user rows, dated in seconds, and the answers
// they gave on its cards, read as opencode.py's `user_messages` and `answers` read them inside
// harness.strictly: a database that is not SQLite, or a receipt that cannot be read, is an error
// for the done check to hold the seat on, never an owner who said nothing.
func TestOpenCodeOwnerWordsAreReadStrictly(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	token := strings.Repeat("a", 32)
	receipt := filepath.Join(home, ".agentkit", "state", "opencode-launch-"+token)
	if err := os.MkdirAll(receipt, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(receipt, "session"), []byte("ses_Acme\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	database := filepath.Join(home, "opencode.db")
	t.Setenv("OPENCODE_DB", database)
	conn, err := sqlite.Open(database, sqlite3.OPEN_READWRITE|sqlite3.OPEN_CREATE)
	if err != nil {
		t.Fatal(err)
	}
	// as OpenCode 2.2.6 keeps them, a card answered by keyboard as one tool part of an answer
	card := `{"type": "tool", "name": "question", "state": {"status": "completed",` +
		` "input": {"questions": [{"question": "Which format?", "options": [{"label": "PDF", "description": "for print"}]}]},` +
		` "metadata": {"answers": [["PDF"]]}}, "time": {"completed": 1800000001500}}`
	for _, row := range [][]any{
		{"ses_Acme", "user", 0, 1_800_000_000_250, `{"text": "Build the acme report."}`},
		{"ses_Acme", "assistant", 1, 1_800_000_001_000, `{"content": [{"type": "text", "text": "Which format?"}, ` + card + `]}`},
		{"ses_Acme", "idle", 2, 1_800_000_001_250, `{"outcome": "completed"}`},
		{"ses_Acme", "user", 3, 1_800_000_002_000, `{"text": "Make it a PDF."}`},
		{"ses_Other", "user", 0, 1_800_000_000_000, `{"text": "Another seat's."}`},
	} {
		if conn.Exec("CREATE TABLE IF NOT EXISTS session_message (id text PRIMARY KEY, session_id text NOT NULL,"+
			" type text NOT NULL, seq integer NOT NULL, time_created integer NOT NULL, data text NOT NULL)") != nil {
			t.Fatal("no table")
		}
		stmt, _, err := conn.Prepare("INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?)")
		if err != nil {
			t.Fatal(err)
		}
		if stmt.BindText(1, row[0].(string)+row[1].(string)+string(rune('0'+row[2].(int)))) != nil || stmt.BindText(2, row[0].(string)) != nil ||
			stmt.BindText(3, row[1].(string)) != nil || stmt.BindInt(4, row[2].(int)) != nil || stmt.BindInt64(5, int64(row[3].(int))) != nil ||
			stmt.BindText(6, row[4].(string)) != nil || stmt.Exec() != nil || stmt.Close() != nil {
			t.Fatal("could not write a row")
		}
	}
	if err := conn.Close(); err != nil {
		t.Fatal(err)
	}
	record := map[string]any{"opencode_launch": token}
	conversation, typed, known, err := Typed("opencode", record, "")
	if want := []Prompt{{1_800_000_000.25, "Build the acme report."}, {1_800_000_002, "Make it a PDF."}}; conversation != "ses_Acme" ||
		!slices.Equal(typed, want) || !known || err != nil {
		t.Fatalf("typed %q %v %v %v", conversation, typed, known, err)
	}
	said, cards, err := Answered("opencode", record)
	if want := []Turn{{"user", "Build the acme report."}, {"model", "Which format?"}, {"user", "Make it a PDF."}}; !slices.Equal(said, want) || err != nil {
		t.Fatalf("said %v %v", said, err)
	}
	if want := []Card{{1_800_000_001.5, "Which format?", "PDF", []Choice{{"PDF", "for print"}}}}; !reflect.DeepEqual(cards, want) {
		t.Fatalf("cards %+v", cards)
	}
	if !Reads("opencode", true) {
		t.Fatal("Go hands an OpenCode seat's owner words to Python")
	}

	broken := func(why string) {
		t.Helper()
		if _, typed, _, err := Typed("opencode", record, ""); err == nil || typed != nil {
			t.Errorf("%s: typed %v, no error", why, typed)
		}
		if said, cards, err := Answered("opencode", record); err == nil || said != nil || cards != nil {
			t.Errorf("%s: said %v and cards %v, no error", why, said, cards)
		}
	}
	if err := os.Rename(database, database+".kept"); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(database, []byte("These are notes, not a database.\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	broken("a database that is not SQLite")
	if err := os.Rename(database+".kept", database); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(filepath.Join(receipt, "session")); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(filepath.Join(receipt, "session"), 0o700); err != nil {
		t.Fatal(err)
	}
	broken("a receipt that is a directory")
}
