package notify

import (
	"os"
	"path/filepath"
	"slices"
	"testing"
)

func TestEachConversationASeatLeftIsTheOneItsEntryNames(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("AGENTKIT_ADAPTER_DIR", "")
	write := func(path, text string) {
		t.Helper()
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil || os.WriteFile(path, []byte(text), 0o600) != nil {
			t.Fatal(path)
		}
	}
	write(filepath.Join(home, ".agentkit", "config.toml"),
		"[models.gemini]\nharness='antigravity'\nmodel='gemini-3'\neffort='high'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
	// the current launch's evidence names the conversation the seat is on now, never one it left
	write(filepath.Join(home, ".agentkit", "state", "session-acme.json"), `{"orchestrator": "gemini",
		"antigravity_launch": "token-now", "antigravity_open": {"launch": "token-now", "conversation": "c-now"},
		"left": [{"harness": "antigravity", "conversation": "c-before"}]}`)
	had, err := Conversations("acme", false)
	var names []string
	for _, each := range had {
		names = append(names, each.Name)
	}
	if err != nil || !slices.Equal(names, []string{"c-before", "c-now"}) {
		t.Fatalf("%q, %v", names, err)
	}
}
