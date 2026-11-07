package cli

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
)

// Open work goes back twice; the third stop stands and keeps back for the owner how the seat
// goes on, its last words after the question, their end where they run long, its wait dropped.
func TestTheThirdStopWithWorkOpenAsksTheOwner(t *testing.T) {
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
	for name, text := range map[string]string{
		"session-acme.json": `{"orchestrator": "opus", "cwd": "/code/acme", "conversation": "conv-1"}`,
		"plan-acme.md":      "- [ ] Ship the parser\n",
		"stop-acme.json":    `{"session": "acme", "turn": 5}`,
		"seat-acme.json":    `{"wait": {"kind": "run", "on": "20261030-0900-fix-api", "at": 4, "over": true}}`,
	} {
		if err := os.WriteFile(filepath.Join(state, name), []byte(text), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	said := strings.Repeat("x", 150) + "\n\n  I cannot   reach " + strings.Repeat("y", 100)
	for n, want := range []string{"You stopped with work open", "You stopped with work open", ""} {
		var out bytes.Buffer
		if code := orchestratorStop([]byte(`{"hook_event_name": "Stop", "last_assistant_message": "`+
			strings.ReplaceAll(said, "\n", `\n`)+`"}`), &out); code != 0 || !strings.Contains(out.String(), want) || want == "" && out.Len() > 0 {
			t.Fatalf("stop %d: exit %d, %q", n+1, code, out.String())
		}
	}
	file, _ := run.ReadJSON(filepath.Join(state, "seat-acme.json"))
	asked := file.Dict("unasked")
	words := "…" + strings.Repeat("x", 83) + " I cannot reach " + strings.Repeat("y", 100)
	if asked.Str("text") != stuck+" "+words || file.Get("wait") != nil || !strings.Contains(run.Line(asked), `"ended"`) {
		t.Fatalf("the owner's question: %s", run.Line(file))
	}
}

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

// A conversation whose harness's manifest has no table to read its question cards with, Codex's,
// may hold one unanswered: open work there is Python's to send back, the latch left as it was.
func TestOpenWorkInAConversationGoCannotReadIsLeftToPython(t *testing.T) {
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
	latch := `{"session": "acme", "turn": 5, "blocks": 0}`
	for name, text := range map[string]string{
		"session-acme.json": `{"orchestrator": "astra", "cwd": "/code/acme", "conversation": "conv-1"}`,
		"plan-acme.md":      "- [ ] Ship the parser\n",
		"stop-acme.json":    latch,
		"chat.jsonl":        `{"payload": {"type": "function_call", "name": "request_user_input", "call_id": "card-1"}}` + "\n",
	} {
		if err := os.WriteFile(filepath.Join(state, name), []byte(text), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	var out bytes.Buffer
	stop := `{"hook_event_name": "Stop", "last_assistant_message": "Waiting for your answer.", "transcript_path": "` +
		filepath.ToSlash(filepath.Join(state, "chat.jsonl")) + `"}`
	if code := orchestratorStop([]byte(stop), &out); code != 3 || out.Len() > 0 {
		t.Fatalf("exit %d, %q", code, out.String())
	}
	if data, _ := os.ReadFile(filepath.Join(state, "stop-acme.json")); string(data) != latch {
		t.Fatalf("the latch: %s", data)
	}
}
