package menu

import (
	"fmt"
	"math"
	"strconv"
	"time"

	"agentkit/internal/history"
	"agentkit/internal/terminal"
)

// SizeChart is how changes of each size did (`runs`, history.FirstReviewSizes) under a line limit,
// Python's menu.size_chart, the evidence it is set from: under heading, a bar of each step lines
// below limit, then one from it up marked `over`, of what ran under a higher one; at "no limit", up
// to the largest.  Each: its share passed, as a whole percent, and its count.  The heading counts
// the runs, each a noun where one is given, since the first one's day.
func SizeChart(s terminal.Screen, runs []history.Row, limit any, step int, heading, noun string) []string {
	if len(runs) == 0 {
		return barChart(s, heading+" · none yet", nil)
	}
	dash := "–"
	if s.ASCII() {
		dash = "-"
	}
	top, limited := limit.(int)
	if !limited {
		for _, run := range runs {
			lines, _ := run.Num("lines")
			top = max(top, (int(lines)/step+1)*step)
		}
	}
	type size struct {
		name      string
		low, high float64
		over      string
	}
	var sizes []size
	for low := 0; low < top; low += step {
		high := min(low+step, top)
		sizes = append(sizes, size{fmt.Sprint(low, dash, high-1), float64(low), float64(high), ""})
	}
	if limited {
		sizes = append(sizes, size{fmt.Sprint(top, "+"), float64(top), math.Inf(1), "over"})
	}
	bars := make([]bar, len(sizes))
	for at, each := range sizes {
		passed, count := 0.0, 0
		for _, run := range runs {
			if lines, _ := run.Num("lines"); each.low <= lines && lines < each.high {
				done, _ := run.Num("passed")
				passed, count = passed+done, count+1
			}
		}
		percent := ""
		if count > 0 {
			percent = fmt.Sprintf("%d%%", int(math.RoundToEven(100*passed/float64(count))))
		}
		bars[at] = bar{each.name, passed / float64(max(1, count)), "done", []string{percent, strconv.Itoa(count), each.over}}
	}
	counted := strconv.Itoa(len(runs))
	if noun != "" {
		counted += " " + noun
		if len(runs) != 1 {
			counted += "s"
		}
	}
	since, _ := runs[0].Num("started_at")
	return barChart(s, fmt.Sprintf("%s · %s since %s", heading, counted, time.Unix(int64(since), 0).Format("2 Jan")), bars)
}
