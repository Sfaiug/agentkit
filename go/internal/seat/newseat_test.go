package seat

import (
	"testing"

	"agentkit/internal/config"
)

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
		if seat.Orchestrator != "opus" || seat.Workers != "" || seat.Warning != "" || !found.Settled(moment) {
			t.Fatalf("live %v: %+v", live, seat)
		}
		builds, reviews := found.Crew(seat)
		if len(builds) != 0 || len(reviews) != 1 || reviews[0] != config.ModelAt("astra", "review_effort", found.models) {
			t.Fatalf("live %v: builders %v, reviewers %v", live, builds, reviews)
		}
	}
}
