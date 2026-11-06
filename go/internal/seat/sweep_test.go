package seat

import (
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"testing"
	"time"
)

func TestTheSweepForgetsAGoneSeatAWeekAfterItsLastSighting(t *testing.T) {
	if _, err := exec.LookPath("tmux"); err != nil {
		t.Skip("no tmux installed") // tmux's own word that a seat is gone is what lets it go
	}
	now := time.Now()
	home := sandbox(t)
	for name, days := range map[string]int{"acme": 8, "beta": 6} {
		record(t, home, name, map[string]any{"seen": seconds(now.AddDate(0, 0, -days))})
	}
	var said []string
	if carried, err := Sweep(now, func(line string) { said = append(said, line) }); !carried || err != nil {
		t.Fatal(carried, err)
	}
	state := filepath.Join(home, ".agentkit", "state")
	if _, err := os.Lstat(filepath.Join(state, "session-acme.json")); err == nil {
		t.Error("the seat gone eight days is still recorded")
	}
	if _, err := os.Lstat(filepath.Join(state, "session-beta.json")); err != nil {
		t.Error("the seat gone six days is forgotten")
	}
	if !slices.Equal(said, []string{"forgot the session acme, gone for 8d"}) {
		t.Error(said)
	}
}

func TestAHarnessWhoseForgetGoDoesNotCarryLeavesTheSweepToPythonBeforeAnythingGoes(t *testing.T) {
	now := time.Now()
	home := sandbox(t)
	record(t, home, "acme", map[string]any{"orchestrator": "astra", "workers": []string{"astra"}, "seen": seconds(now.AddDate(0, 0, -8))})
	// an enrollment an earlier forget could not delete, which every Codex forget asks again
	write(t, filepath.Join(home, ".agentkit", "state", "codex-remote-0123456789abcdef0123456789abcdef.forgotten"), "")
	if carried, err := Sweep(now, func(line string) { t.Error(line) }); carried || err != nil {
		t.Fatal(carried, err)
	}
	if _, err := os.Lstat(filepath.Join(home, ".agentkit", "state", "session-acme.json")); err != nil {
		t.Error("the record went before Python's sweep")
	}
}

func TestACardThatDoesNotCloseLeavesTheRestOfTheSeatForgotten(t *testing.T) {
	if _, err := exec.LookPath("tmux"); err != nil {
		t.Skip("no tmux installed")
	}
	now := time.Now()
	home := sandbox(t)
	token := "0123456789abcdef0123456789abcdef"
	record(t, home, "acme", map[string]any{"orchestrator": "astra", "workers": []string{"astra"}, "codex_launch": token,
		"seen": seconds(now.AddDate(0, 0, -8))})
	state := filepath.Join(home, ".agentkit", "state")
	write(t, filepath.Join(state, "codex-launch-"+token+".json"), "{}")
	write(t, filepath.Join(state, "card-acme.json"), "{")
	var said []string
	if carried, err := Sweep(now, func(line string) { said = append(said, line) }); !carried || err != nil {
		t.Fatal(carried, err)
	}
	for _, gone := range []string{"session-acme.json", "codex-launch-" + token + ".json"} {
		if _, err := os.Lstat(filepath.Join(state, gone)); err == nil {
			t.Error(gone, "outlived the seat's forgetting")
		}
	}
	if _, err := os.Lstat(filepath.Join(state, "card-acme.json")); err != nil {
		t.Error("the card that did not read went without its retry")
	}
	if !slices.Equal(said, []string{"forgot the session acme, gone for 8d",
		"WARN the card of acme was not closed (JSONDecodeError); retry required"}) {
		t.Error(said)
	}
}
