package menu

import (
	"slices"
	"testing"
	"time"

	"agentkit/internal/history"
)

// Each round from the lowest merge to the last is a bar, then the failed runs', each with its count,
// share and median hours, folded under its ending below 60 columns: Python's rounds_chart's lines.
func TestRoundsChartDrawsEachEndingAsPythonDoes(t *testing.T) {
	local := time.Local
	time.Local = time.UTC
	t.Cleanup(func() { time.Local = local })
	t.Setenv("NO_COLOR", "1")
	const day, hour = 1793836800, 3600.0
	ended := func(start, hours float64, merged bool, round int) history.RoundEnding {
		return history.RoundEnding{Started: day + start, Finished: day + start + hours*hour, Merged: merged, Round: round}
	}
	runs := []history.RoundEnding{ended(0, 2, true, 1), ended(10, 3, true, 1), ended(20, 5, true, 2),
		ended(30, 1, false, 0), ended(40, 4, true, 4), ended(50, 1.5, true, 0)}
	for _, each := range []struct {
		columns string
		runs    []history.RoundEnding
		want    []string
	}{
		{"80", runs, []string{"", "  how your 6 runs ended, since 5 Nov",
			"  merged with no review  ━━━━━╸───────────────────────────  1  17%  median 1.5 h",
			"  merged in round 1      ━━━━━━━━━━━──────────────────────  2  33%  median 2.5 h",
			"  merged in round 2      ━━━━━╸───────────────────────────  1  17%  median 5.0 h",
			"  merged in round 3      ─────────────────────────────────  0   0%",
			"  merged in round 4      ━━━━━╸───────────────────────────  1  17%  median 4.0 h",
			"  failed                 ━━━━━╸───────────────────────────  1  17%  median 1.0 h"}},
		{"40", runs[:1], []string{"", "  how your 1 run ended, since 5 Nov",
			"  merged in round 1", "    ━━━━━━━━━━━━━  1  100%  median 2.0 h",
			"  failed", "    ─────────────  0    0%"}},
		{"80", nil, []string{"", "  no finished runs yet"}},
	} {
		if got := RoundsChart(screenAt(t, each.columns), each.runs); !slices.Equal(got, each.want) {
			t.Errorf("%s columns:\n%q\nwant\n%q", each.columns, got, each.want)
		}
	}
}
