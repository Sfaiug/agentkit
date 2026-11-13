package menu

import (
	"slices"
	"testing"
	"time"

	"agentkit/internal/history"
)

// A bar each step below the limit, the last cut at the limit where it falls between steps, then one
// from it up marked `over`; at "no limit" up to the largest; with none, `none yet`: Python's
// size_chart's lines.
func TestSizeChartDrawsEachSizeAsPythonDoes(t *testing.T) {
	local := time.Local
	time.Local = time.UTC
	t.Cleanup(func() { time.Local = local })
	t.Setenv("NO_COLOR", "1")
	const day = 1793836800
	sized := func(start, lines, passed int64) history.Row {
		return history.Row{"started_at": day + start, "lines": lines, "passed": passed}
	}
	runs := []history.Row{sized(0, 10, 1), sized(10, 99, 0), sized(20, 120, 1), sized(30, 260, 0), sized(40, 410, 1)}
	for _, each := range []struct {
		runs  []history.Row
		limit any
		step  int
		noun  string
		want  []string
	}{
		{runs, "no limit", 100, "build", []string{"", "  how changes did · 5 builds since 5 Nov",
			"  0–99     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━─────────────────────────────   50%  2",
			"  100–199  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  100%  1",
			"  200–299  ──────────────────────────────────────────────────────────    0%  1",
			"  300–399  ──────────────────────────────────────────────────────────        0",
			"  400–499  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  100%  1"}},
		{runs, 250, 100, "build", []string{"", "  how changes did · 5 builds since 5 Nov",
			"  0–99     ━━━━━━━━━━━━━━━━━━━━━━━━━━━───────────────────────────   50%  2",
			"  100–199  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  100%  1",
			"  200–249  ──────────────────────────────────────────────────────        0",
			"  250+     ━━━━━━━━━━━━━━━━━━━━━━━━━━━───────────────────────────   50%  2  over"}},
		{runs[:3], 50, 25, "", []string{"", "  how changes did · 3 since 5 Nov",
			"  0–24   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  100%  1",
			"  25–49  ────────────────────────────────────────────────────────        0",
			"  50+    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━────────────────────────────   50%  2  over"}},
		{nil, 300, 100, "build", []string{"", "  how changes did · none yet"}},
	} {
		if got := SizeChart(screenAt(t, "80"), each.runs, each.limit, each.step, "how changes did", each.noun); !slices.Equal(got, each.want) {
			t.Errorf("at %v:\n%q\nwant\n%q", each.limit, got, each.want)
		}
	}
}
