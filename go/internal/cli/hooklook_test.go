package cli

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/seat"
)

// The owner's answer on a card heard outside the seat's own pane is its fact and answers nothing,
// as Python's look answers nothing there.
func TestACardsAnswerHeardOutsideItsPaneAnswersNothing(t *testing.T) {
	home := sandbox(t)
	t.Setenv("AGENTKIT_SESSION", "acme")
	t.Setenv("TMUX", "")
	state := filepath.Join(home, ".agentkit", "state")
	write(t, filepath.Join(home, ".agentkit", "config.toml"), "[models.opus]\nharness='claude'\nmodel='claude-opus'\neffort='xhigh'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
	write(t, filepath.Join(state, "session-acme.json"), `{"orchestrator": "opus"}`)
	if err := seat.Keep("acme", "Which port?"); err != nil {
		t.Fatal(err)
	}
	kept, _ := os.ReadFile(filepath.Join(state, "seat-acme.json"))
	answer := []byte(`{"hook_event_name": "PostToolUse", "tool_name": "AskUserQuestion", ` +
		`"tool_response": {"answers": {"Which port?": "8080"}}}`)
	if code := seatState(answer, new(bytes.Buffer)); code != 0 {
		t.Fatalf("exit %d", code)
	}
	if _, err := os.Stat(filepath.Join(state, "hook-acme.json")); err != nil {
		t.Fatal("its fact is not written")
	}
	if now, _ := os.ReadFile(filepath.Join(state, "seat-acme.json")); !bytes.Equal(now, kept) {
		t.Fatalf("it answered %s", now)
	}
	if _, err := os.Stat(filepath.Join(home, ".agentkit", "history.db")); err == nil {
		t.Fatal("it wrote the owner's time")
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
