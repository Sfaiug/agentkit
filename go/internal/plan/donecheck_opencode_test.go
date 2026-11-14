package plan

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/sqlite"
)

// An OpenCode seat's record names its conversation where its receipt names none, as Python's
// conversations_of reads it (a follow whose receipt write failed): a card answered there holds a
// finished plan, as the same card in a session the seat left does.
func TestAFinishedPlanOwesACheckForTheSessionItsRecordNames(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("AGENTKIT_ADAPTER_DIR", "")
	state, token := filepath.Join(home, ".agentkit", "state"), strings.Repeat("a", 32)
	write := func(path, text string) {
		t.Helper()
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil || os.WriteFile(path, []byte(text), 0o600) != nil {
			t.Fatal(path)
		}
	}
	write(filepath.Join(home, ".agentkit", "config.toml"),
		"[models.mid]\nharness = 'opencode'\nmodel = 'acme/m'\neffort = 'high'\nprovider = 'test'\n[providers.test]\nmode = 'subscription'\n")
	write(filepath.Join(state, "plan-acme.md"), "- [x] Build the acme report.\n")
	if err := os.Mkdir(filepath.Join(state, "opencode-launch-"+token), 0o700); err != nil {
		t.Fatal(err)
	}
	database := filepath.Join(home, "opencode.db")
	t.Setenv("OPENCODE_DB", database)
	conn, err := sqlite.Open(database, sqlite3.OPEN_READWRITE|sqlite3.OPEN_CREATE)
	if err != nil {
		t.Fatal(err)
	}
	if err := conn.Exec(`CREATE TABLE session_message (id text PRIMARY KEY, session_id text NOT NULL,` +
		` type text NOT NULL, seq integer NOT NULL, time_created integer NOT NULL, data text NOT NULL);` +
		` INSERT INTO session_message VALUES ('a1', 'ses_Previous', 'assistant', 0, 1800000001000,` +
		` '{"content": [{"type": "tool", "name": "question", "state": {"status": "completed",` +
		` "input": {"questions": [{"question": "Which format?", "options": [{"label": "PDF"}]}]},` +
		` "metadata": {"answers": [["PDF"]]}}, "time": {"completed": 1800000001500}}]}')`); err != nil {
		t.Fatal(err)
	}
	if err := conn.Close(); err != nil {
		t.Fatal(err)
	}
	launch := `"orchestrator": "mid", "opencode_launch": "` + token + `"`
	for _, record := range []string{
		`{` + launch + `, "conversation": "ses_Previous", "id_source": "opencode-hook"}`,
		`{` + launch + `, "left": [{"harness": "opencode", "conversation": "ses_Previous"}]}`,
	} {
		write(filepath.Join(state, "session-acme.json"), record)
		if finished, err := Finished("acme"); err != nil || finished {
			t.Errorf("%s: finished %v (%v)", record, finished, err)
		}
	}
}
