package pick

import (
	"slices"
	"testing"

	"agentkit/internal/config"
)

// paces is a read where each model has room, a budget and the pace given, none where it is absent.
type paces map[string]float64

func (paces) Spent(string) string             { return "" }
func (paces) Budget(string) (float64, string) { return 1, "" }
func (paces) OnCredits(string) bool           { return false }
func (p paces) Pace(name string) (float64, bool) {
	pace, known := p[name]
	return pace, known
}

func TestAPaygModelWaitsUntilEverySubscriptionRunsAheadOfPace(t *testing.T) {
	unranked := func(bool, map[string]config.Model, []string) func(a, b string) int {
		return func(string, string) int { return 0 }
	}
	rules := &Rules{executors: []string{"opus", "mimo"}, payg: map[string]bool{"mimo": true}, margin: 10, rank: unranked}
	for _, each := range []struct {
		room paces
		want []string
	}{
		{paces{"opus": 10, "mimo": 0}, []string{"opus"}}, // at the margin is still below it
		{paces{"mimo": 0}, []string{"opus"}},             // a subscription reporting no pace
		{paces{"opus": 10.5, "mimo": 50}, []string{"opus", "mimo"}},
	} {
		if got := rules.Order(each.room, false, nil); !slices.Equal(got, each.want) {
			t.Errorf("%v: %v, want %v", each.room, got, each.want)
		}
	}
}
