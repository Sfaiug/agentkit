package hookfact

import (
	"os"
	"path/filepath"
	"slices"
	"testing"
)

func TestAFactLandsOverAnOlderOneCarryingItsWorkUntilTheNextStop(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	t.Setenv("USERPROFILE", os.Getenv("HOME"))
	state := filepath.Join(os.Getenv("HOME"), ".agentkit", "state")
	fact := func() string {
		data, _ := os.ReadFile(filepath.Join(state, "hook-acme.json"))
		return string(data)
	}
	prompt := Fact{Session: "acme", Event: "UserPromptSubmit", At: 20, Holds: []string{"shell"}}
	steps := []struct {
		fact Fact
		kept bool
		want string
	}{
		{Fact{Session: "acme", Event: "Stop", Kind: "background", At: 10, Holds: []string{"shell"}}, false,
			`{"session":"acme","event":"Stop","kind":"background","text":"","at":10,"holds":["shell"]}`},
		{Fact{Session: "acme", Event: "UserPromptSubmit", At: 20}, false,
			`{"session":"acme","event":"UserPromptSubmit","kind":"","text":"","at":20,"holds":["shell"]}`},
		// heard before the one standing: it never lands over it
		{Fact{Session: "acme", Event: "Notification", Kind: "idle_prompt", At: 15}, false,
			`{"session":"acme","event":"UserPromptSubmit","kind":"","text":"","at":20,"holds":["shell"]}`},
		// newer, but the rule keeps the one standing
		{Fact{Session: "acme", Event: "Notification", Kind: "permission_prompt", At: 25}, true,
			`{"session":"acme","event":"UserPromptSubmit","kind":"","text":"","at":20,"holds":["shell"]}`},
		{Fact{Session: "acme", Event: "Stop", At: 30.5}, false,
			`{"session":"acme","event":"Stop","kind":"","text":"","at":30.5}`},
	}
	for _, step := range steps {
		keep := func(standing Fact) bool {
			if step.kept && (standing.Event != prompt.Event || standing.At != prompt.At || !slices.Equal(standing.Holds, prompt.Holds)) {
				t.Fatalf("the rule was handed %+v, not the fact standing", standing)
			}
			return step.kept
		}
		if err := Record(" acme ", step.fact, keep); err != nil {
			t.Fatal(err)
		}
		if got := fact(); got != step.want+"\n" {
			t.Fatalf("after %s at %v the fact is %s, want %s", step.fact.Event, step.fact.At, got, step.want)
		}
	}
	if _, err := os.Stat(filepath.Join(state, ".hook-acme.lock")); err != nil {
		t.Fatalf("the lock Python's writers share was not taken: %v", err)
	}
	if err := Record("a/b", Fact{At: 40}, func(Fact) bool { return false }); err == nil {
		t.Fatal("a seat name that is a path was written")
	}
}
