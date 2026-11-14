package cli

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

// An OpenCode prompt in the owner's words names the session it went into, which may move the
// seat there: Go hands that over in the seat's pane with nothing written, and outside it, where
// nothing moves the seat, writes the prompt.
func TestAPromptThatMayMoveTheSeatIsHandedOverInItsPane(t *testing.T) {
	home := sandbox(t)
	state := filepath.Join(home, ".agentkit", "state")
	write(t, filepath.Join(home, ".agentkit", "config.toml"), "[models.mimo]\nharness='opencode'\nmodel='mimo-1'\neffort='low'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
	write(t, filepath.Join(state, "session-acme.json"), `{"orchestrator": "mimo", "conversation": "ses_AcmeOld"}`)
	t.Setenv("AGENTKIT_SESSION", "acme")
	prompt := []byte(`{"hook_event_name": "UserPromptSubmit", "message": "Build acme.", "session_id": "ses_AcmeNew"}`)
	for pane, want := range map[string]int{"%1": 3, "": 0} {
		t.Setenv("TMUX", "/tmp/ak-none,1,0")
		t.Setenv("TMUX_PANE", pane)
		os.Remove(filepath.Join(state, "stop-acme.json"))
		if code := seatState(prompt, new(bytes.Buffer)); code != want {
			t.Fatalf("pane %q: exit %d", pane, code)
		}
		if _, err := os.Stat(filepath.Join(state, "stop-acme.json")); (err == nil) != (want == 0) {
			t.Fatalf("pane %q: its turn written %v", pane, err == nil)
		}
	}
}
