package notify

import (
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

// A fresh OpenCode seat names its conversation only at its first prompt: until then its
// conversations are the Claude one it left, read strictly with nothing of OpenCode read or judged,
// and it has no messages of its own now, as Python's owner_messages reads its conversation_of.
func TestAConversationItsHarnessHasNotNamedIsNoneOfTheSeats(t *testing.T) {
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
		"[models.mimo]\nharness='opencode'\nmodel='mimo'\neffort='high'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
	cwd := filepath.Join(home, "acme")
	write(filepath.Join(home, ".agentkit", "state", "session-acme.json"), `{"orchestrator": "mimo", "cwd": `+
		strings.ReplaceAll(`"`+cwd+`"`, `\`, `\\`)+`, "conversation": null, "opencode_launch": "`+strings.Repeat("a", 32)+`",
		"left": [{"harness": "claude", "conversation": "c-before"}]}`)
	folder := regexp.MustCompile(`[^A-Za-z0-9]`).ReplaceAllString(cwd, "-")
	write(filepath.Join(home, ".claude", "projects", folder, "c-before.jsonl"),
		`{"type": "user", "timestamp": "2026-11-05T10:00:00Z", "message": {"role": "user", "content": "Add a retry button."}}`+"\n")
	had, err := Conversations("acme", true)
	if err != nil || len(had) != 1 || had[0].Name != "c-before" || len(had[0].Messages) != 1 {
		t.Fatalf("%+v, %v", had, err)
	}
	if now, messages, err := OwnerMessages("acme"); now != "" || messages != nil || err != nil {
		t.Errorf("now %q: %v, %v", now, messages, err)
	}
}

// Asking whether an Antigravity launch has named its conversation learns nothing and takes no
// lock: listed loosely or read strictly, the home stays as it was.
func TestAskingANameWritesNothingBeforeAHandover(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("AGENTKIT_ADAPTER_DIR", "")
	state := filepath.Join(home, ".agentkit", "state")
	if os.MkdirAll(state, 0o700) != nil {
		t.Fatal(state)
	}
	os.WriteFile(filepath.Join(home, ".agentkit", "config.toml"), []byte("[models.astra]\nharness='antigravity'\n"+
		"model='astra'\neffort='high'\nprovider='test'\n[providers.test]\nmode='subscription'\n"), 0o600)
	os.WriteFile(filepath.Join(state, "session-acme.json"), []byte(`{"orchestrator": "astra", "antigravity_launch": "`+
		strings.Repeat("a", 32)+`"}`), 0o600)
	if _, err := Conversations("acme", true); !errors.Is(err, ErrUnread) {
		t.Errorf("strictly: %v", err)
	}
	if _, had, err := Listed("acme", false); err != nil || len(had) != 1 {
		t.Errorf("listed loosely: %+v, %v", had, err)
	}
	if _, err := os.Stat(filepath.Join(state, "antigravity-claim.lock")); err == nil {
		t.Errorf("asking a name made the claim's lock")
	}
}
