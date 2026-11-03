package screen

import (
	"testing"

	"agentkit/internal/config"
)

func claude(t *testing.T) *Rules {
	t.Helper()
	chrome, err := config.Section("claude", "screen")
	if err != nil {
		t.Fatal(err)
	}
	rules, err := config.ScreenRules("claude")
	if err != nil {
		t.Fatal(err)
	}
	read, err := Compile(chrome, rules)
	if err != nil {
		t.Fatal(err)
	}
	return read
}

func TestEveryManifestCompiles(t *testing.T) {
	names, err := config.ManifestNames()
	if err != nil || len(names) < 6 {
		t.Fatal(names, err)
	}
	for _, name := range names {
		chrome, err := config.Section(name, "screen")
		if err != nil {
			t.Fatal(err)
		}
		rules, err := config.ScreenRules(name)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := Compile(chrome, rules); err != nil {
			t.Errorf("%s: %v", name, err)
		}
	}
}

func TestWhatPythonRefusesIsARefusal(t *testing.T) {
	chrome := map[string]any{"composer": "x"}
	if _, err := Compile(chrome, []map[string]any{{"id": "a", "state": "working", "newest": `(x`}}); err == nil {
		t.Error("a rule Python refuses compiled")
	}
	if _, err := Compile(map[string]any{"composer": `[x`}, nil); err == nil {
		t.Error("chrome Python refuses compiled")
	}
	if _, err := Compile(chrome, []map[string]any{{"id": "a", "state": "busy"}}); err == nil {
		t.Error("a state no seat has compiled")
	}
}

const (
	rule80 = "────────────────────────────────────────"
	foot   = "  ⏵⏵ bypass permissions on (shift+tab to cycle)"
)

func TestTheComposerRowReadsAfterPythonsStrip(t *testing.T) {
	got := claude(t).Read(rule80 + "\n❯ \n" + rule80 + "\n" + foot)
	if got.State != "at_prompt" || got.Rule != "prompt.composer" {
		t.Fatalf("%+v", got)
	}
}

func TestTheComposerTellsTypedTextFromASuggestion(t *testing.T) {
	read := claude(t)
	for tail, want := range map[string]Reading{
		rule80 + "\n❯ fix the build\n" + rule80 + "\n" + foot:                      {"draft", "prompt.draft", "fix the build"},
		rule80 + "\n\x1b[2m❯ try this\x1b[0m\n" + rule80 + "\n" + foot:             {"at_prompt", "prompt.suggestion", "❯ try this"},
		rule80 + "\n❯ \x1b[7mf\x1b[0m\x1b[2mix it\x1b[0m\n" + rule80 + "\n" + foot: {"at_prompt", "prompt.suggestion", "❯ fix it"},
		"● it said ❯ quoted\nmore output":                                          {},
	} {
		if got := read.Read(tail); got != want {
			t.Errorf("%q: %+v, not %+v", tail, got, want)
		}
	}
}

func TestAViewScrolledAwayReadsNothing(t *testing.T) {
	tail := "● old words\n" + "Enter to select · ↑/↓ to navigate\nJump to bottom (ctrl+End) ↓\n" + rule80
	if got := claude(t).Read(tail); got != (Reading{}) {
		t.Fatalf("%+v", got)
	}
}

func TestSaidLeavesOutTheChromeBelowWhatWasSaid(t *testing.T) {
	said := claude(t).Said("● done\n" + rule80 + "\n❯ unsent words\n" + rule80 + "\n" + foot)
	if len(said) != 1 || said[0] != "● done" {
		t.Fatalf("%q", said)
	}
}

func TestLastInColour(t *testing.T) {
	pane := "\x1b[31m● API Error\x1b[0m\n● the words API Error"
	if whole, attributes := LastInColour(pane, 0, "● API Error"); !whole || !attributes {
		t.Fatal(whole, attributes)
	}
	if whole, attributes := LastInColour(pane, 1, "● the words API Error"); whole || !attributes {
		t.Fatal(whole, attributes)
	}
	if _, attributes := LastInColour("● API Error", 0, "● API Error"); attributes {
		t.Fatal("a plain capture holds no attributes")
	}
}
