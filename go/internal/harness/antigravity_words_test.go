package harness

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

func TestAntigravityScreenLeavesConversationEvidenceToPython(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	path := filepath.Join(home, ".gemini", "antigravity-cli", "conversations", "conv-acme.db")
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("Python reads SQLite"), 0o600); err != nil {
		t.Fatal(err)
	}
	for _, each := range []struct {
		name, json string
		ready      bool
	}{
		{"no evidence", `{}`, true},
		{"unowned legacy id", `{"conversation":"conv-acme"}`, true},
		{"launcher store Go cannot read", `{"conversation":"conv-acme","id_source":"launcher"}`, false},
		{"no launcher store", `{"conversation":"conv-other","id_source":"launcher"}`, true},
		{"invalid store id", `{"conversation":"../conv-acme","id_source":"launcher"}`, true},
		{"pending launch", `{"antigravity_launch":"token"}`, false},
		{"learned store", `{"antigravity_launch":"token","antigravity_open":{"launch":"token","conversation":"conv-acme"}}`, false},
		{"learned id without a store", `{"antigravity_launch":"token","antigravity_open":{"launch":"token","conversation":"conv-other"}}`, false},
		{"stale launch", `{"antigravity_launch":"new","antigravity_open":{"launch":"old","conversation":"conv-acme"}}`, false},
	} {
		t.Run(each.name, func(t *testing.T) {
			value, err := run.Decode([]byte(each.json))
			if err != nil {
				t.Fatal(err)
			}
			record := value.(*run.Object)
			before := run.Encode(record)
			if _, known := For("antigravity").Reconciled("acme", record); known != each.ready || run.Encode(record) != before {
				t.Fatalf("readiness differs or record changed: %s, ready=%v", run.Encode(record), known)
			}
		})
	}
}
