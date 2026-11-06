package seat

import (
	"os"
	"os/exec"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/tmux"
)

func TestALegacySeatsNameIsTaken(t *testing.T) {
	if _, err := exec.LookPath("tmux"); err != nil {
		t.Skip("no tmux installed")
	}
	sandbox(t)
	t.Cleanup(func() { tmux.Ask(tmux.Default, "kill-server") })
	if err := tmux.Spawn(tmux.Default, os.Getenv("PATH"), "new-session", "-d", "-s", "unnamed", "sleep 60", ";",
		"set-option", "-t", "=unnamed:", tmux.Mark, "1"); err != nil {
		t.Fatal(err)
	}
	names := ReadNames()
	if reserved, known := names.Reservations(); !known || !reserved["unnamed"] {
		t.Errorf("the menu offers a legacy seat's name: %v, %v", reserved, known)
	}
	if taken, known := names.Taken("unnamed"); !taken || !known {
		t.Errorf("ak orch new takes a legacy seat's name: %v, %v", taken, known)
	}
}

func TestMenuReadsAnOrchestratorBuildingAlone(t *testing.T) {
	for _, live := range []bool{false, true} {
		home := sandbox(t)
		record(t, home, "acme", map[string]any{"workers": []string{}, "reviewers": []string{"astra"}})
		if live {
			drawn(t, home, "acme", prompting)
		}
		found, known := Menu(moment)
		if !known || len(found.Seats) != 1 {
			t.Fatalf("live %v: menu did not list the seat", live)
		}
		seat := found.Seats[0]
		if seat.Orchestrator != "opus" || seat.Workers != "" || seat.Warning != "" || !found.Settled() {
			t.Fatalf("live %v: %+v", live, seat)
		}
		builds, reviews := found.Crew(seat)
		if len(builds) != 0 || len(reviews) != 1 || reviews[0] != config.ModelAt("astra", "review_effort", found.models) {
			t.Fatalf("live %v: builders %v, reviewers %v", live, builds, reviews)
		}
	}
}
