package harness

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestOwnedConversation(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	plugins["unread"] = plugin{}
	t.Cleanup(func() { delete(plugins, "unread") })
	token := strings.Repeat("a", 32)
	receipt := filepath.Join(home, ".agentkit", "state", "opencode-launch-"+token)
	if err := os.MkdirAll(receipt, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(receipt, "session"), []byte("ses_Acme\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	for _, each := range []struct {
		name, harness string
		record        map[string]any
		conversation  string
		known         bool
	}{
		{"a launch's id", "claude", map[string]any{"conversation": "c", "id_source": "launcher"}, "c", true},
		{"one its hook replaced it with", "claude", map[string]any{"conversation": "c", "id_source": "claude-hook"}, "c", true},
		{"one nothing vouches for", "claude", map[string]any{"conversation": "c"}, "", false},
		{"no conversation", "claude", map[string]any{}, "", true},
		{"no receipt, whatever the record names", "codex", map[string]any{"conversation": "c", "id_source": "launcher"}, "", true},
		{"a receipt that names no launch", "codex", map[string]any{"codex_launch": "r"}, "", true},
		{"no report, whatever the record names", "opencode", map[string]any{"conversation": "c", "id_source": "launcher"}, "", true},
		{"the session its launch reported", "opencode", map[string]any{"opencode_launch": token}, "ses_Acme", true},
		{"a store Go has no plugin for", "unread", map[string]any{"conversation": "c", "id_source": "launcher"}, "", false},
		{"an adapter alone", "echo", map[string]any{"conversation": "c", "id_source": "launcher"}, "c", true},
	} {
		if conversation, known := Owned(each.harness, each.record); conversation != each.conversation || known != each.known {
			t.Errorf("%s: %q, %v", each.name, conversation, known)
		}
	}
}

func TestFreshWordsAreTheManifests(t *testing.T) {
	if words := FreshWords("codex"); words != "it starts a new Codex conversation" {
		t.Error(words)
	}
	if words := FreshWords("claude"); words != "no conversation recorded; it starts fresh" {
		t.Error(words)
	}
}
