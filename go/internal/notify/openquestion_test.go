package notify

import (
	"os"
	"testing"
	"time"

	"agentkit/internal/run"
)

// A first open whose write failed is still owed: the writer changed an object of its own, never
// the parse every reader of the notice shares.
func TestAFirstOpenThatFailedToSaveIsSavedByTheNext(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	if err := os.MkdirAll(state(), 0o700); err != nil {
		t.Fatal(err)
	}
	path := seatFile("notify", "acme", "json")
	if err := os.WriteFile(path, []byte(`{"kind":"needs","text":"Which one?","time":1}`), 0o600); err != nil {
		t.Fatal(err)
	}
	time.Sleep(1100 * time.Millisecond) // at rest, so its parse is kept
	if Last("acme") == nil {
		t.Fatal("the question does not stand")
	}
	blocked := seatFile("notify", "acme", "tmp") // where the notice is written first
	if err := os.Mkdir(blocked, 0o700); err != nil {
		t.Fatal(err)
	}
	capture := func(string) string { return "the owner's first screen" }
	if _, err := OpenedQuestion("acme", capture); err == nil {
		t.Fatal("the blocked write was saved")
	}
	if err := os.Remove(blocked); err != nil {
		t.Fatal(err)
	}
	if carried, err := OpenedQuestion("acme", capture); !carried || err != nil {
		t.Fatalf("the next open: %v, %v", carried, err)
	}
	if saved, err := run.ReadJSON(path); err != nil || saved.Get("opened_at") == nil || saved.Str("opened_pane") != capture("") {
		t.Fatalf("the first open is unsaved: %s, %v", run.Line(saved), err)
	}
}
