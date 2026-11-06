package tmux

import "testing"

func TestWordQuotesAsTmuxReads(t *testing.T) {
	for text, want := range map[string]string{
		"ak orch front":        "'ak orch front'",
		`it's "#1" for $HOME\`: `"it's \"\#1\" for \$HOME\\"`,
	} {
		if got := Word(text); got != want {
			t.Fatalf("Word(%q) = %s, want %s", text, got, want)
		}
	}
}
