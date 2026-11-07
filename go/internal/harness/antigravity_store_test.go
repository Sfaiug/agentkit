package harness

import (
	"os"
	"path/filepath"
	"slices"
	"testing"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/run"
	"agentkit/internal/sqlite"
)

// agySteps writes a conversation's store at path, its steps table holding those rows
// (step_type, metadata, step_payload) as tests/test_key_only_owner_chat_replies.py writes them.
func agySteps(t *testing.T, path string, steps [][3]any) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	conn, err := sqlite.Open(path, sqlite3.OPEN_READWRITE|sqlite3.OPEN_CREATE)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	if err := conn.Exec("CREATE TABLE `steps` (`idx` integer,`step_type` integer NOT NULL DEFAULT 0,`status` integer NOT NULL DEFAULT 0," +
		"`metadata` blob,`step_payload` blob,PRIMARY KEY (`idx`))"); err != nil {
		t.Fatal(err)
	}
	for idx, step := range steps {
		stmt, _, err := conn.Prepare("INSERT INTO steps (idx, step_type, status, metadata, step_payload) VALUES (?, ?, 3, ?, ?)")
		if err != nil {
			t.Fatal(err)
		}
		if stmt.BindInt(1, idx) != nil || stmt.BindInt(2, step[0].(int)) != nil || stmt.BindBlob(3, step[1].([]byte)) != nil ||
			stmt.BindBlob(4, step[2].([]byte)) != nil || stmt.Exec() != nil || stmt.Close() != nil {
			t.Fatal("could not write a step")
		}
	}
}

func TestAntigravityReadsWhoTypedWhatWhenFromItsStore(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	number := func(field, value uint64) []byte { return append(agyVarintOf(field<<3), agyVarintOf(value)...) }
	user := func(text string) []byte {
		return slices.Concat(number(1, 14), agyNested(19, agyNested(2, []byte(text))))
	}
	model := func(text string) []byte {
		return slices.Concat(number(1, 15), agyNested(20, agyNested(1, []byte(text))))
	}
	agySteps(t, filepath.Join(home, ".gemini", "antigravity-cli", "conversations", "conv-acme.db"), [][3]any{
		{14, agyStamp(1, 1_800_000_000.75), user("Build the acme parser.")},
		{15, agyStamp(1, 1_800_000_001), model("Which schema should it write?")},
		{14, []byte(nil), user("The first one.")}, // no date: nobody's answer
		{14, agyNested(1, append(number(1, 1_800_000_002), 2<<3, 0x80)), user("Cut.")},
		{14, agyNested(1, slices.Concat(number(1, 1_800_000_002), number(2, 1_000_000_000))), user("Too many nanoseconds.")},
		{14, agyStamp(1, 1_800_000_000.5), user("The second one.")},
		{15, agyStamp(1, 1_800_000_003), slices.Concat(number(1, 15), agyNested(20, agyNested(3, []byte("thinking"))))},
		{16, agyStamp(1, 1_800_000_003), user("Another kind of step.")},
	})
	// the launcher's conversation, or the one its launch learned
	for _, record := range []map[string]any{{"conversation": "conv-acme", "id_source": "launcher"},
		{"antigravity_launch": "token", "antigravity_open": map[string]any{"launch": "token", "conversation": "conv-acme"}}} {
		conversation, typed, known := Typed("antigravity", record)
		if want := []Prompt{{1_800_000_000.5, "The second one."}, {1_800_000_000.75, "Build the acme parser."}}; conversation != "conv-acme" ||
			!slices.Equal(typed, want) || !known {
			t.Fatalf("typed %q %v %v", conversation, typed, known)
		}
	}
	// agy 1.2.13 keeps no generations: its store holds no answer, as Python's query fails there too
	if reader, ready := For("antigravity").Reconciled("acme", run.Fields("conversation", "conv-acme", "id_source", "launcher")); !ready {
		t.Fatal("Go handed over a store keeping no generations")
	} else if _, _, _, found := reader.LastAnswer(run.Fields("conversation", "conv-acme", "id_source", "launcher")); found {
		t.Fatal("a store keeping no generations held an answer")
	}
	said, known := Said("antigravity", "conv-acme")
	if want := []Turn{{"user", "Build the acme parser."}, {"model", "Which schema should it write?"}, {"user", "The first one."},
		{"user", "Cut."}, {"user", "Too many nanoseconds."}, {"user", "The second one."}}; !slices.Equal(said, want) || !known {
		t.Fatalf("said %v %v", said, known)
	}
}
