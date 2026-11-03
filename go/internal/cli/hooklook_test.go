package cli

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/seat"
)

// The answer on a card a question waits on is Python's, with nothing written; any other is a fact.
func TestACardsAnswerToAStandingQuestionIsLeftToPython(t *testing.T) {
	home := sandbox(t)
	t.Setenv("AGENTKIT_SESSION", "acme")
	state := filepath.Join(home, ".agentkit", "state")
	write(t, filepath.Join(state, "session-acme.json"), `{"orchestrator": "opus"}`)
	answer := []byte(`{"hook_event_name": "PostToolUse", "tool_name": "AskUserQuestion"}`)
	fact := filepath.Join(state, "hook-acme.json")
	var out bytes.Buffer
	if code := seatState(answer, &out); code != 0 {
		t.Fatalf("no question stands: exit %d", code)
	}
	if _, err := os.Stat(fact); err != nil {
		t.Fatal("no question stands: its fact is written")
	}
	os.Remove(fact)
	if err := seat.Keep("acme", "Which port?"); err != nil {
		t.Fatal(err)
	}
	if code := seatState(answer, &out); code != leftToPython {
		t.Fatalf("exit %d", code)
	}
	if _, err := os.Stat(fact); err == nil {
		t.Fatal("what it left to Python wrote its fact")
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
