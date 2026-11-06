package seat

import (
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"agentkit/internal/run"
)

// walkEvery is how long one walk of a quiet run answers for (menu.WALK_EVERY): silence is told in
// hours, so a minute never shows, however many files a run's sandbox leaves behind.
const walkEvery = time.Minute

// walked holds a quiet run's directory: when it was walked and the newest write that found.
var walked = struct {
	sync.Mutex
	runs map[string]walk
}{runs: map[string]walk{}}

type walk struct {
	at     time.Time
	newest float64
}

// silence is how long the run in dir has gone without a write, in seconds, from the newest write
// anywhere under it (menu.silent_for_run); 0 for a run no loop works.  Its record and its log are
// written as it goes, so either within the hour answers without walking every file it holds.
func silence(dir string, record *run.Object, now time.Time) float64 {
	if !run.Active(record) {
		return 0
	}
	for _, name := range []string{"run.json", "log.txt"} {
		if info, err := os.Stat(filepath.Join(dir, name)); err == nil && now.Sub(info.ModTime()) <= time.Hour {
			return 0
		}
	}
	walked.Lock()
	kept, known := walked.runs[dir]
	if !known || time.Since(kept.at) >= walkEvery {
		kept = walk{time.Now(), lastWrite(dir)}
		walked.runs[dir] = kept
	}
	walked.Unlock()
	newest := kept.newest
	if newest == 0 {
		newest = at(record.Get("started_at"))
	}
	if newest == 0 {
		return 0
	}
	return seconds(now) - newest
}

// lastWrite is the newest write under dir (watch.run_last_write): the run's last sign of life.
// Locks and temp files are the tick's own bookkeeping, not the run's life.
func lastWrite(dir string) float64 {
	var latest float64
	filepath.WalkDir(dir, func(path string, entry fs.DirEntry, err error) error {
		if err != nil || entry.IsDir() || strings.HasSuffix(path, ".lock") || strings.HasSuffix(path, ".tmp") {
			return nil
		}
		// a link to a directory is one os.walk lists and never enters
		if info, err := os.Stat(path); err == nil && !info.IsDir() {
			latest = max(latest, seconds(info.ModTime()))
		}
		return nil
	})
	return latest
}
