package notify

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// A receipt written before the harness named its conversation, as Python writes one on a fresh
// OpenCode launch, counts in the conversation that launch reported since: ak's line is not the
// owner's.
func TestAReceiptNamingOnlyItsLaunchCountsInTheConversationItReported(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("AGENTKIT_ADAPTER_DIR", "")
	database, err := filepath.Abs(filepath.Join("..", "harness", "testdata", "opencode.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Setenv("OPENCODE_DB", database) // ses_Free's one user row: "Rename the acme report."
	state := filepath.Join(home, ".agentkit", "state")
	write := func(path, text string) {
		t.Helper()
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil || os.WriteFile(path, []byte(text), 0o600) != nil {
			t.Fatal(path)
		}
	}
	ours, other := strings.Repeat("d", 32), strings.Repeat("e", 32)
	write(filepath.Join(home, ".agentkit", "config.toml"),
		"[models.mid]\nharness = 'opencode'\nmodel = 'acme/m'\neffort = 'high'\nprovider = 'test'\n[providers.test]\nmode = 'subscription'\n")
	write(filepath.Join(state, "session-acme.json"), `{"orchestrator": "mid", "workers": ["mid"], "opencode_launch": "`+ours+`"}`)
	write(filepath.Join(state, "opencode-launch-"+ours, "session"), "ses_Free")
	write(filepath.Join(state, "opencode-launch-"+other, "session"), "ses_Again")
	receipt := func(token string) string {
		return `{"harness": "opencode", "conversation": null, "launch": {"opencode_launch": "` + token +
			`"}, "text": "Rename the acme report.", "source": "ak", "after": 0}` + "\n"
	}
	write(filepath.Join(state, "input-acme.jsonl"), receipt(other)) // another launch's line
	if conversation, said, err := OwnerMessages("acme"); conversation != "ses_Free" || len(said) != 1 || err != nil {
		t.Fatalf("another launch's receipt: %q, %v, %v", conversation, said, err)
	}
	write(filepath.Join(state, "input-acme.jsonl"), receipt(other)+receipt(ours))
	if conversation, said, err := OwnerMessages("acme"); conversation != "ses_Free" || len(said) != 0 || err != nil {
		t.Fatalf("ak's line read as the owner's: %q, %v, %v", conversation, said, err)
	}
}
