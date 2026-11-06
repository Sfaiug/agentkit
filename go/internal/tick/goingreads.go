package tick

import (
	"io/fs"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/host"
	"agentkit/internal/run"
)

// A going loop with recent output needs no stall recovery. Locks and temporaries are
// the tick's writes, so they never count as the loop's life (watch.stall_clock).
func notSilent(dir string, record *run.Object) bool {
	// a dead loop's silence is measured too: only a live one is asked whether the host froze it
	pid, _ := record.Int("pid")
	alive := run.ProcessActive(record)
	if record.Truthy("frozen_since") || alive && host.Frozen(pid) {
		return false
	}
	minutes := float64(run.SilenceMinutes)
	if record.Has("silence_minutes") {
		var known bool
		if minutes, known = dated(record, "silence_minutes"); !known || minutes <= 0 {
			return false
		}
	}
	latest := run.FirstNumber(record, "thawed_at")
	if wait := record.Dict("transient_wait"); wait != nil && run.Equal(wait.Get("pid"), record.Get("pid")) {
		latest = max(latest, run.FirstNumber(wait, "until"))
	}
	if alive && record.Truthy("delivery_wait") && run.Equal(record.Get("delivery_wait"), record.Get("pid")) {
		return true
	}
	err := filepath.WalkDir(dir, func(path string, entry fs.DirEntry, err error) error {
		if err != nil || entry.IsDir() || strings.HasSuffix(entry.Name(), ".lock") || strings.HasSuffix(entry.Name(), ".tmp") {
			return err
		}
		info, err := entry.Info()
		if err == nil {
			latest = max(latest, epoch(info.ModTime()))
		}
		return err
	})
	return err == nil && epoch(time.Now())-latest < minutes*60
}
