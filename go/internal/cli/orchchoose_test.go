package cli

import (
	"bytes"
	"os"
	"strings"
	"testing"

	"agentkit/internal/terminal"
)

func TestOrchestratorQuestionKeepsTheNextLineForTheNextQuestion(t *testing.T) {
	for _, each := range []struct{ answer, want string }{
		{"2", "beta"}, {"BETA", "beta"}, {"", "acme"}, {"not-a-model\n\x1b[A\n2", "beta"}, {"\x1b", ""},
	} {
		in, out, err := os.Pipe()
		if err != nil {
			t.Fatal(err)
		}
		out.WriteString(each.answer + "\nnext\n")
		out.Close()
		previous := os.Stdin
		os.Stdin = in
		var shown bytes.Buffer
		name, ok := askOrchestrator(&shown, []string{"acme", "beta"}, "acme", " (why)")
		next := terminal.Answer(&bytes.Buffer{}, "")
		os.Stdin = previous
		in.Close()
		if name != each.want || ok != (each.want != "") || next != "next" ||
			!strings.Contains(shown.String(), "Orchestrator [acme] (why): ") {
			t.Fatalf("%q: got %q, %v; next %q; shown %q", each.answer, name, ok, next, shown.String())
		}
	}
}
