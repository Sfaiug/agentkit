package menu

import (
	"fmt"
	"math"
	"slices"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/history"
	"agentkit/internal/terminal"
)

// RoundsChart is how `runs` ended (history.RoundEndings), drawn under `Review rounds`' note
// (menu.rounds_chart): the evidence its number is set from.  Under a heading, a bar of each ending -- each round from round
// 1, or a merge with review off, up to the last a run merged in, then `failed` -- its share of the
// runs taking the room the columns after it leave: its count, that share as a whole percent and its
// median hours from start to finish.  Below 60 columns each bar folds under its ending.
func RoundsChart(s terminal.Screen, runs []history.Row) []string {
	if len(runs) == 0 {
		return []string{"", "  no finished runs yet"}
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
	names, numbers := make([]string, len(hours)), make([][3]string, len(hours))
	widths, wide := [3]int{}, 0
	for at, each := range hours {
		names[at] = "merged in round " + strconv.Itoa(first+at)
		switch {
		case at == len(hours)-1:
			names[at] = "failed"
		case first+at == 0:
			names[at] = "merged with no review"
		}
		numbers[at] = [3]string{strconv.Itoa(len(each)), fmt.Sprintf("%d%%", int(math.RoundToEven(100*float64(len(each))/float64(len(runs)))))}
		if len(each) > 0 {
			numbers[at][2] = fmt.Sprintf("median %.1f h", median(each))
		}
		for n, number := range numbers[at] {
			widths[n] = max(widths[n], len(number))
		}
		wide = max(wide, len(names[at]))
	}
	room := s.LayoutWidth()
	folded, lead := room < 60, 4+wide
	if folded {
		lead = 4
	}
	size := max(1, room-lead-6-widths[0]-widths[1]-widths[2])
	plural := "s"
	if len(runs) == 1 {
		plural = ""
	}
	lines := []string{""}
	since, _ := runs[0].Num("started_at")
	for _, part := range terminal.Wrap(fmt.Sprintf("how your %d run%s ended, since %s", len(runs), plural,
		time.Unix(int64(since), 0).Format("2 Jan")), room-2) {
		lines = append(lines, "  "+part)
	}
	for at, each := range hours {
		word := "done"
		if at == len(hours)-1 {
			word = "FAIL"
		}
		tail := strings.TrimRight(fmt.Sprintf("%s  %*s  %*s  %s", s.ShareLine(float64(len(each))/float64(len(runs)), size, word),
			widths[0], numbers[at][0], widths[1], numbers[at][1], numbers[at][2]), " ")
		if folded {
			lines = append(lines, "  "+names[at], "    "+tail)
		} else {
			lines = append(lines, "  "+terminal.Pad(names[at], wide)+"  "+tail)
		}
	}
	return lines
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
