package history

import (
	"math"
	"slices"
	"strings"
)

// Peaks is history.db as Python's gate reads it to let a run in, through a connection that cannot
// write: nil, which measured nothing, where none stands or SQLite cannot open it; an error where its
// tokens wait for the one-time repair Python's read makes first, which Go leaves to Python.
func Peaks() (*DB, error) {
	db := Look()
	if db == nil {
		return nil, nil
	}
	if _, err := db.recounted(); err != nil {
		db.Close()
		return nil, err
	}
	return db, nil
}

// RecentPeak is Python's history.recent_peak_rss_mb: the median measured peak of the real runs
// that finished in the week up to now, false where none was measured.
func (db *DB) RecentPeak(now float64) (float64, bool) {
	rows, _ := db.EndedRuns(now-7*86400, now)
	var peaks []float64
	for _, row := range rows {
		if peak, ok := row.Num("peak_rss_mb"); ok && !math.IsInf(peak, 0) && !math.IsNaN(peak) && peak > 0 {
			peaks = append(peaks, peak)
		}
	}
	if len(peaks) == 0 {
		return 0, false
	}
	slices.Sort(peaks)
	middle := len(peaks) / 2
	if len(peaks)%2 == 1 {
		return peaks[middle], true
	}
	return (peaks[middle-1] + peaks[middle]) / 2, true
}

// SoFar is Python's history.peaks_so_far: each of those runs' peak so far by run id, as its
// sampler wrote it, none for a run unmeasured.
func (db *DB) SoFar(ids []string) map[string]float64 {
	found := map[string]float64{}
	if len(ids) == 0 {
		return found
	}
	args := make([]any, len(ids))
	for i, id := range ids {
		args[i] = id
	}
	rows, _ := db.read("SELECT run_id, peak_rss_mb FROM runs WHERE peak_rss_mb IS NOT NULL AND run_id IN (?"+
		strings.Repeat(", ?", len(ids)-1)+")", args...)
	for _, row := range rows {
		if peak, ok := row.Num("peak_rss_mb"); ok {
			found[row.Text("run_id")] = peak
		}
	}
	return found
}
