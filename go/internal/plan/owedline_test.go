package plan

import (
	"os"
	"path/filepath"
	"testing"
)

// The line a seat owes is its plan's first owed line in its own words, as stop.owed_line says it.
func TestTheLineOwedIsTheFirstInItsOwnWords(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	t.Setenv("USERPROFILE", os.Getenv("HOME"))
	state := filepath.Join(os.Getenv("HOME"), ".agentkit", "state")
	if err := os.MkdirAll(state, 0o700); err != nil {
		t.Fatal(err)
	}
	where := " · acme · written 2026-10-20 09:00"
	for text, want := range map[string]string{
		"- [x] Merge the parser\n- [ ] Ship   it\n- [ ] Tell them\n":                         "Ship   it",
		"- [x] z · check: `true`" + where + "\n- [ ] Ship it · check: `true`" + where + "\n": "z",
		"- [x] Merge the parser\n": "",
	} {
		if err := os.WriteFile(filepath.Join(state, "plan-acme.md"), []byte(text), 0o600); err != nil {
			t.Fatal(err)
		}
		line, owes, err := Look{}.OwedLine("acme")
		if line != want || owes != (want != "") || err != nil {
			t.Errorf("%q: %q %v %v, want %q", text, line, owes, err, want)
		}
	}
}
