package cli

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// Whether a finished plan owes its done check is kept, with what the answer read, by a command Go
// carries, and by none it hands over: `ak plan` lists a plan that owes none and keeps that; once
// the owner says more, the plan owes its check, which Python's listing makes, and the listing
// leaves HOME as it was.
func TestAnAnswerToTheDoneCheckIsKeptOnlyByACommandGoCarries(t *testing.T) {
	home := sandbox(t)
	t.Setenv("AGENTKIT_SESSION", "acme")
	os.Remove(filepath.Join(home, ".agentkit", "config.toml")) // a Claude seat's, as ak's own config has it
	state := filepath.Join(home, ".agentkit", "state")
	write(t, filepath.Join(state, "session-acme.json"), `{"orchestrator": "opus", "cwd": "/code/acme", "conversation": "conv-acme"}`)
	write(t, filepath.Join(state, "plan-acme.md"), "- [x] Ship the parser\n")
	transcript := filepath.Join(home, ".claude", "projects", "-code-acme", "conv-acme.jsonl")
	write(t, transcript, "")
	var out, errOut bytes.Buffer
	if code := Main([]string{"plan"}, &out, &errOut); code != 0 || !strings.Contains(out.String(), "- [x] Ship the parser") {
		t.Fatalf("listed: exit %d, %q, %q", code, out.String(), errOut.String())
	}
	if kept, err := os.ReadFile(filepath.Join(state, "owed-acme.json")); err != nil || !strings.Contains(string(kept), `"owed": false`) {
		t.Fatalf("its answer: %q, %v", kept, err)
	}
	write(t, transcript, `{"type": "user", "timestamp": "2026-11-05T10:00:00Z", "message": {"role": "user", "content": "Ship the parser."}}`+"\n")
	assertCall(t, []string{"plan"}, 3, "", "ak plan: not implemented in Go yet\n")
}
