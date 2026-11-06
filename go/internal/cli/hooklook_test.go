package cli

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/seat"
)

// The owner's answer on a card is Go's where it answers what the seat kept back, and Python's,
// with nothing written, where a notice stands for it or Go cannot name the seat's conversation.
func TestACardsAnswerIsLeftToPythonOnlyWhereGoCannotRecordIt(t *testing.T) {
	home := sandbox(t)
	t.Setenv("AGENTKIT_SESSION", "acme")
	state := filepath.Join(home, ".agentkit", "state")
	answer := []byte(`{"hook_event_name": "PostToolUse", "tool_name": "AskUserQuestion", ` +
		`"tool_response": {"answers": {"Which port?": "8080"}}}`)
	fact := filepath.Join(state, "hook-acme.json")
	write(t, filepath.Join(home, ".agentkit", "config.toml"), "[models.opus]\nharness='claude'\nmodel='claude-opus'\neffort='xhigh'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
	if err := seat.Keep("acme", "Which port?"); err != nil {
		t.Fatal(err)
	}
	for _, step := range []struct {
		why, file, data string
		code            int
	}{
		{"a question kept back", "session-acme.json", `{"orchestrator": "opus"}`, 0},
		{"a seat of no harness Go knows", "session-acme.json", `{"orchestrator": "nobody"}`, leftToPython},
		{"a notice standing", "notify-acme.json", `{"session": "acme", "kind": "needs", "text": "Which port?", "time": 1}`, leftToPython},
	} {
		write(t, filepath.Join(state, step.file), step.data)
		os.Remove(fact)
		if code := seatState(answer, new(bytes.Buffer)); code != step.code {
			t.Fatalf("%s: exit %d", step.why, code)
		}
		if _, err := os.Stat(fact); (err == nil) != (step.code == 0) {
			t.Fatalf("%s: its fact written %v", step.why, err == nil)
		}
	}
}

// A seat's own question is kept for its turn's end, or refused once its plan is done.
func TestASeatsOwnQuestion(t *testing.T) {
	home := sandbox(t)
	t.Setenv("AGENTKIT_SESSION", "acme")
	state := filepath.Join(home, ".agentkit", "state")
	write(t, filepath.Join(state, "session-acme.json"), `{"orchestrator": "nobody"}`)
	assertCall(t, []string{"notify", "needs", "Which port?"}, 3, "", "ak notify needs: not implemented in Go yet\n")
	write(t, filepath.Join(home, ".agentkit", "config.toml"), "[models.opus]\nharness='claude'\nmodel='claude-opus'\neffort='xhigh'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
	write(t, filepath.Join(state, "session-acme.json"), `{"orchestrator": "opus"}`)
	if code := Main([]string{"notify", "needs", "  Which port?  "}, new(bytes.Buffer), new(bytes.Buffer)); code != 0 {
		t.Fatalf("its question: exit %d", code)
	}
	if data, _ := os.ReadFile(filepath.Join(state, "seat-acme.json")); !strings.Contains(string(data), `"text": "Which port?"`) || !strings.Contains(string(data), `"wait": null`) {
		t.Fatalf("it kept %s", data)
	}
	if _, err := os.Stat(filepath.Join(state, "notify-acme.json")); err == nil {
		t.Fatal("a question kept back is no notice yet")
	}
	write(t, filepath.Join(state, "plan-acme.md"), "- [x] Ship it · your eye · acme · written 2026-10-23 09:00\n")
	var refused bytes.Buffer
	if code := Main([]string{"notify", "needs", "Which branch?"}, new(bytes.Buffer), &refused); code != 2 || !strings.Contains(refused.String(), "Your plan is done") {
		t.Fatalf("a done seat's question: exit %d, %s", code, refused.String())
	}
}
