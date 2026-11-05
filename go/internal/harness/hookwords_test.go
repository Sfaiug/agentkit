package harness

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

func TestAListingKeepsTheHookFactItReconciled(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	path := filepath.Join(home, ".agentkit", "state", "hook-acme.json")
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	write := func(text string) {
		t.Helper()
		if err := os.WriteFile(path, []byte(text), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	write(`{"session":"acme","event":"UserPromptSubmit","at":1}`)
	record := run.Fields("conversation", "c", "id_source", "launcher")
	before := run.Encode(record)
	reader, known := For("claude").Reconciled("acme", record)
	if !known {
		t.Fatal("the hook's seat was unreadable")
	}
	// A hook landing while the listing waits to publish belongs to the next listing.
	write(`{"session":"acme","event":"Stop","at":2}`)
	if fact := reader.HookFact("acme"); fact.Event != "UserPromptSubmit" || fact.At != 1 {
		t.Fatal(fact)
	}
	next, known := For("claude").Reconciled("acme", record)
	if fact := next.HookFact("acme"); !known || fact.Event != "Stop" || fact.At != 2 {
		t.Fatal(known, fact)
	}
	if run.Encode(record) != before {
		t.Fatal("reading hook facts rewrote the session record")
	}
}
