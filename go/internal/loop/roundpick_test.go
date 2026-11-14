package loop

import (
	"os"
	"path/filepath"
	"slices"
	"testing"

	"agentkit/internal/run"
)

// A pick within a round ranks each model at the efforts the run launched with, as Python's off
// config.at_efforts: five, launched low, is its low row there, the dearer and the worse, and four
// comes first, though five at the high effort the config says now is the pick.
func TestARoundsPickRanksAtTheRunsEfforts(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	write := func(path, text string) {
		t.Helper()
		if err := os.MkdirAll(filepath.Dir(path), 0o777); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(text), 0o666); err != nil {
			t.Fatal(err)
		}
	}
	row := func(release, effort, quality, cost string) string {
		return `{"release": "` + release + `", "maker": "Acme", "effort": "` + effort + `", "values": {"aa.intelligenceIndex": 50, ` +
			`"aa.frontierCode20": ` + quality + `, "arena.agent": ` + quality + `, "aa.omniscience": 50, ` +
			`"aa.intelligenceIndexEvaluations.frontiercode-2-0.costPerTask": ` + cost + `}, "yours": [{"harness": "claude", "model": "` + release + `"}]}`
	}
	write(filepath.Join(home, ".agentkit", "state", "matrix.json"), `{"matrix": {"lineup": [`+
		row("acme-5", "high", "0.6", "1")+`, `+row("acme-5", "low", "0.2", "3")+`, `+row("acme-4", "high", "0.4", "2")+`]}}`)
	write(filepath.Join(home, ".agentkit", "config.toml"), "companies = ['Acme']\n[providers.p]\nmode = 'subscription'\n"+
		"[models.five]\nharness = 'claude'\nmodel = 'acme-5'\neffort = 'high'\nprovider = 'p'\n"+
		"[models.four]\nharness = 'claude'\nmodel = 'acme-4'\neffort = 'high'\nprovider = 'p'\n")
	l := &loop{workers: []string{"five", "four"}, reviewers: []string{"five", "four"},
		efforts: run.Fields("five", run.Fields("effort", "high", "exec_effort", "low", "review_effort", "low"))}
	live, ok := l.rules()
	if !ok {
		t.Fatal("the pick is handed over")
	}
	round, ok := l.roundRules()
	if !ok {
		t.Fatal("the round's pick is handed over")
	}
	for _, review := range []bool{false, true} {
		if got := live.Order(unmetered{}, review, nil); !slices.Equal(got, []string{"five", "four"}) {
			t.Fatalf("at the config's efforts, review %v picked in the order %v", review, got)
		}
		if got := round.Order(unmetered{}, review, nil); !slices.Equal(got, []string{"four", "five"}) {
			t.Fatalf("at the run's efforts, review %v picked in the order %v", review, got)
		}
	}
}
