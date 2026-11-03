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
