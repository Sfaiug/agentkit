package menu

import (
	"fmt"
	"math"
	"slices"
	"strconv"
	"time"

	"agentkit/internal/history"
	"agentkit/internal/terminal"
)

// RoundsChart is how `runs` ended (history.RoundEndings), drawn under `Review rounds`' note
// (menu.rounds_chart): the evidence its number is set from.  Under a heading, a bar of each ending
// -- each round from round 1, or a merge with review off, up to the last a run merged in, then
// `failed` -- its share of the runs taking the room the columns after it leave: its count, that
// share as a whole percent and its median hours from start to finish (barChart).
func RoundsChart(s terminal.Screen, runs []history.Row) []string {
	if len(runs) == 0 {
		return barChart(s, "no finished runs yet", nil)
	}
	first, last := 1, 0
	for _, run := range runs {
		if round, merged := run.Num("round"); merged {
			first, last = min(first, int(round)), max(last, int(round))
		}
	}
	// each round's from first to last, then the failed runs'
	hours := make([][]float64, last-first+2)
	for _, run := range runs {
		at := len(hours) - 1
		if round, merged := run.Num("round"); merged {
			at = int(round) - first
		}
		started, _ := run.Num("started_at")
		finished, _ := run.Num("finished_at")
		hours[at] = append(hours[at], (finished-started)/3600)
	}
	bars := make([]bar, len(hours))
	for at, each := range hours {
		name, word, held := "merged in round "+strconv.Itoa(first+at), "done", ""
		switch {
		case at == len(hours)-1:
			name, word = "failed", "FAIL"
		case first+at == 0:
			name = "merged with no review"
		}
		if len(each) > 0 {
			held = fmt.Sprintf("median %.1f h", median(each))
		}
		bars[at] = bar{name, float64(len(each)) / float64(len(runs)), word, []string{strconv.Itoa(len(each)),
			fmt.Sprintf("%d%%", int(math.RoundToEven(100*float64(len(each))/float64(len(runs))))), held}}
	}
	plural := "s"
	if len(runs) == 1 {
		plural = ""
	}
	since, _ := runs[0].Num("started_at")
	return barChart(s, fmt.Sprintf("how your %d run%s ended, since %s", len(runs), plural,
		time.Unix(int64(since), 0).Format("2 Jan")), bars)
}

// median is Python's statistics.median: the middle of the sorted values, or the mean of the two
// middle ones.
func median(values []float64) float64 {
	sorted := slices.Sorted(slices.Values(values))
	half := len(sorted) / 2
	if len(sorted)%2 == 1 {
		return sorted[half]
	}
	return (sorted[half-1] + sorted[half]) / 2
}
