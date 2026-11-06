package tick

import (
	"cmp"
	"math"
	"slices"

	"agentkit/internal/history"
	"agentkit/internal/host"
	"agentkit/internal/seat"
)

const week = 7 * 86400

// sleep is the idle sleep row (sleep.tick): every seat rested past its harness's prompt cache
// sleeps, one a seat.  While memory is tight Python's tick also sleeps the seat idle the longest
// sooner, and says how tight, which Go leaves to it, as it does a seat whose rest Go does not read
// that may sleep: with nothing put to sleep.
func (t *ticking) sleep() error {
	rests, unread, known := seat.Resting(t.clock())
	if !known {
		return errLeft
	}
	if len(rests)+len(unread) == 0 {
		return nil
	}
	now := epoch(t.clock())
	due := func(rest seat.Rest) bool { return now-rest.Since > rest.Cache }
	tight, err := host.MemoryTight(func() (float64, bool, error) { return recentPeak(now) })
	if err != nil {
		return err
	}
	if tight || slices.ContainsFunc(unread, due) {
		return errLeft
	}
	slices.SortStableFunc(rests, func(a, b seat.Rest) int { return cmp.Or(cmp.Compare(a.Since, b.Since), cmp.Compare(a.Name, b.Name)) })
	for _, rest := range rests {
		if !due(rest) {
			continue
		}
		slept, err := seat.Sleep(rest)
		if err != nil {
			return err
		}
		if slept {
			t.log.line("put " + rest.Name + " to sleep, rested past its prompt cache")
		}
	}
	return nil
}

// recentPeak is history.recent_peak_rss_mb: the median peak of the real runs that finished in the
// last seven days, false where none was measured.  A history Go leaves to Python leaves the row.
func recentPeak(now float64) (float64, bool, error) {
	db, err := history.Open()
	if err != nil {
		return 0, false, errLeft
	}
	if db == nil {
		return 0, false, nil
	}
	defer db.Close()
	rows, _ := db.EndedRuns(now-week, now)
	var peaks []float64
	for _, row := range rows {
		if peak, ok := row.Num("peak_rss_mb"); ok && !math.IsInf(peak, 0) && !math.IsNaN(peak) && peak > 0 {
			peaks = append(peaks, peak)
		}
	}
	if len(peaks) == 0 {
		return 0, false, nil
	}
	slices.Sort(peaks)
	middle := len(peaks) / 2
	if len(peaks)%2 == 1 {
		return peaks[middle], true, nil
	}
	return (peaks[middle-1] + peaks[middle]) / 2, true, nil
}
