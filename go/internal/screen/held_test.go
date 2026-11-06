package screen

import (
	"slices"
	"strings"
	"testing"

	"agentkit/internal/config"
)

// A command a harness moved to the background is held while its screen lists it under the
// composer; the list gone holds nothing, and a footer too narrow to read says nothing either way.
func TestHeldIsTheBackgroundListUnderTheComposer(t *testing.T) {
	chrome, err := config.Section("antigravity", "screen")
	if err != nil {
		t.Fatal(err)
	}
	rules, err := config.ScreenRules("antigravity")
	if err != nil {
		t.Fatal(err)
	}
	read, err := Compile(chrome, rules)
	if err != nil {
		t.Fatal(err)
	}
	rule, footer := strings.Repeat("─", 40), "? for shortcuts              agentkit (GPT-OSS 120B (Medium))  /agents · 1 task(s) · /tasks"
	for _, each := range []struct {
		name, tail string
		held       []string
		read       bool
	}{
		{"one running", rule + "\n>\n" + rule + "\n  ● [12:08:46] sleep 45 running\n" + rule + "\n" + footer, []string{"shell"}, true},
		{"two running", rule + "\n>\n" + rule + "\n● [12:08:46] sleep 45 running\n● [12:09:01] make acme running\n" + rule + "\n" + footer, []string{"shell", "shell"}, true},
		{"none", rule + "\n>\n" + rule + "\n? for shortcuts              agentkit (GPT-OSS 120B (Medium))  /agents", []string{}, true},
		{"too narrow", rule + "\n>\n" + rule + "\n? for shortcuts", nil, false},
	} {
		held, known := read.Held(each.tail)
		if known != each.read || !slices.Equal(held, each.held) {
			t.Errorf("%s: %q, %v", each.name, held, known)
		}
	}
	if held, known := claude(t).Held("anything"); held != nil || known {
		t.Error("a harness whose manifest reads none said what it holds")
	}
}
