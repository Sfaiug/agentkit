package matrix

import (
	"cmp"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/history"
)

// stretches are a login's readings of provider, (at, used) each, in time order, cut between any
// two between which one of the unknown turns on that login of the provider (runsAlone) ran,
// Python's spend._stretches: what such a turn spent counts nowhere, so no stretch spans it.
func (s *spend) stretches(provider, account string, readings [][2]float64, unknown []history.Unknown) [][][2]float64 {
	var spans []history.Unknown
	for _, turn := range unknown {
		if turn.Account == cmp.Or(account, config.DefaultAccount) && s.runsAlone(turn.Harness, provider) {
			spans = append(spans, turn)
		}
	}
	slices.SortFunc(readings, func(a, b [2]float64) int { return cmp.Or(cmp.Compare(a[0], b[0]), cmp.Compare(a[1], b[1])) })
	var found [][][2]float64
	var stretch [][2]float64
	for _, reading := range readings {
		if len(stretch) > 0 && slices.ContainsFunc(spans, func(turn history.Unknown) bool {
			return turn.Began < reading[0] && turn.End > stretch[len(stretch)-1][0]
		}) {
			found, stretch = append(found, stretch), nil
		}
		stretch = append(stretch, reading)
	}
	return append(found, stretch)
}
