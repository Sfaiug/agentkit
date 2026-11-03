package harness

import "testing"

func TestOwnedConversation(t *testing.T) {
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
		{"a receipt to verify", "codex", map[string]any{"codex_launch": "r"}, "", false},
		{"a store of its own", "opencode", map[string]any{"conversation": "c", "id_source": "launcher"}, "", false},
		{"a store Go has no plugin for", "antigravity", map[string]any{}, "", false},
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
