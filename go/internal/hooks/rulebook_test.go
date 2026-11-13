package hooks_test

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/hooks"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

const conversation = "7d3c1e2a-5b4f-4a6e-8c9d-0e1f2a3b4c5d"

func newsSeat(t *testing.T, current string) (hooks.Rulebooks, string) {
	t.Helper()
	t.Setenv("HOME", t.TempDir())
	state := filepath.Join(os.Getenv("HOME"), ".agentkit", "state")
	if err := os.MkdirAll(state, 0o700); err != nil {
		t.Fatal(err)
	}
	record := run.NewObject()
	record.Set("orchestrator", "opus")
	record.Set("conversation", conversation)
	record.Set("id_source", "launcher")
	record.Set("resumable", true)
	record.Set("rulebook_sha", hooks.RulebookDigest([]byte("Rule one.\n")))
	for name, text := range map[string]string{
		"session-acme.json": run.Encode(record), "rulebook-acme.md": "Rule one.\n",
	} {
		if err := os.WriteFile(filepath.Join(state, name), []byte(text), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	return hooks.Rulebooks{Current: func(string) (string, error) { return current, nil }, Update: seat.Update}, state
}

func TestFailedHandoverIsRetried(t *testing.T) {
	books, state := newsSeat(t, "Rule two.\n")
	books.Update = func(string, func(*run.Object) bool) error { return errors.New("cannot record") }
	if news, _ := books.PromptNews("acme", conversation, nil); news != "" {
		t.Fatalf("unrecorded handover: %q", news)
	}
	if _, err := os.Stat(filepath.Join(state, "held-acme.md")); !os.IsNotExist(err) {
		t.Fatalf("unrecorded rules held: %v", err)
	}
	books.Update = seat.Update
	if news, _ := books.PromptNews("acme", conversation, nil); !strings.Contains(news, "\n-Rule one.\n+Rule two.\n") {
		t.Fatalf("retry lost the diff: %q", news)
	}
	if news, _ := books.PromptNews("acme", conversation, nil); news != "" {
		t.Fatalf("already held: %q", news)
	}
}

func TestFailedChangeFileKeepsItsCodeUntilAcknowledged(t *testing.T) {
	books, state := newsSeat(t, "Rule two. "+strings.Repeat("😀", 5000)+"\n")
	change := filepath.Join(state, "change-acme.md")
	if err := os.Mkdir(change, 0o700); err != nil {
		t.Fatal(err)
	}
	if news, _ := books.PromptNews("acme", conversation, nil); news != "" {
		t.Fatalf("unwritten file named: %q", news)
	}
	record, err := run.ReadJSON(filepath.Join(state, "session-acme.json"))
	if err != nil || record == nil || record.Dict("rulebook_told") == nil || record.Has("rulebook_read") {
		t.Fatalf("pending rules lost or held: %v, %v", record, err)
	}
	code := record.Dict("rulebook_told").Str("code")
	if err := os.Remove(change); err != nil {
		t.Fatal(err)
	}
	if news, _ := books.PromptNews("acme", conversation, nil); !strings.Contains(news, change) {
		t.Fatalf("retry did not name its file: %q", news)
	}
	data, err := os.ReadFile(change)
	if err != nil || !strings.HasSuffix(string(data), "ak orch rules "+code+"\n") {
		t.Fatalf("retry changed its code: %v", err)
	}
	if _, err := books.RulebookRead("acme", "wrong"); err == nil {
		t.Fatal("another code acknowledged the file")
	}
	if known, err := books.RulebookRead("acme", code); !known || err != nil {
		t.Fatalf("acknowledgement: %v, %v", known, err)
	}
	if news, _ := books.PromptNews("acme", conversation, nil); news != "" {
		t.Fatalf("acknowledged file still named: %q", news)
	}
}
