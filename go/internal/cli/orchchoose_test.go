package cli

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/terminal"
)

func TestOrchestratorQuestionKeepsTheNextLineForTheNextQuestion(t *testing.T) {
	home := sandbox(t)
	write(t, filepath.Join(home, ".agentkit", "config.toml"), testConfig+
		"[models.beta]\nharness='echo'\nmodel='echo-2'\neffort='high'\nprovider='test'\n")
	for _, each := range []struct{ answer, want, reason string }{
		{"2", "beta", "selected"}, {"BETA", "beta", "selected"}, {"", "acme", "default"},
		{"not-a-model\n\x1b[A\n2", "beta", "selected"}, {"\x1b", "", ""},
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
		name, reason, ok, err := askOrchestrator(&shown)
		next := terminal.Answer(&bytes.Buffer{}, "")
		os.Stdin = previous
		in.Close()
		if name != each.want || reason != each.reason || ok != (each.want != "") || err != nil || next != "next" ||
			!strings.Contains(shown.String(), "Orchestrator [acme]: ") {
			t.Fatalf("%q: got %q (%s), %v, %v; next %q; shown %q", each.answer, name, reason, ok, err, next, shown.String())
		}
	}
}
