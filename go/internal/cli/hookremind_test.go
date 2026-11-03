package cli

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// A turn whose closing message leaves unsaid a question recorded for the owner goes back to say
// it, twice at most: the third stop stands.  One that says it, as a list of its choices too, stands.
func TestAStopGoesBackToSayAQuestionItsMessageLeftOut(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("AGENTKIT_ADAPTER_DIR", "")
	t.Setenv("AGENTKIT_SESSION", "acme")
	t.Setenv("AK_RUN_ROLE", "")
	state := filepath.Join(home, ".agentkit", "state")
	if err := os.MkdirAll(state, 0o700); err != nil {
		t.Fatal(err)
	}
	write := func(name, text string) {
		t.Helper()
		if err := os.WriteFile(filepath.Join(state, name), []byte(text), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	write("session-acme.json", `{"orchestrator": "opus", "cwd": "/code/acme", "conversation": "conv-1"}`)
	stop := func(said string) string {
		var out bytes.Buffer
		if code := orchestratorStop([]byte(`{"hook_event_name": "Stop", "last_assistant_message": "`+said+`"}`), &out); code != 0 {
			t.Fatalf("exit %d", code)
		}
		return out.String()
	}
	write("seat-acme.json", `{"unasked": {"text": "Which port? Options: 8080, 9090.", "at": 3}}`)
	write("stop-acme.json", `{"session": "acme", "turn": 5}`)
	for range 2 {
		if out := stop("I finished the independent work."); !strings.Contains(out, `"decision": "block"`) || !strings.Contains(out, "Which port? Options: 8080, 9090.") {
			t.Fatalf("the question left out: %q", out)
		}
	}
	if out := stop("I finished the independent work."); out != "" {
		t.Fatalf("the third stop: %q", out)
	}
	write("stop-acme.json", `{"session": "acme", "turn": 6}`)
	if out := stop(`Which port?\n\n1. 8080\n2. 9090`); out != "" {
		t.Fatalf("the question said: %q", out)
	}
}
