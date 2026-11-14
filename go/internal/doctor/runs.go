package doctor

import (
	"fmt"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/run"
	"agentkit/internal/terminal"
	"agentkit/internal/tick"
)

// census is the runs line, Python's watch.runs_health: of the runs started in the last day, how
// many ended, how many are going and each lost by name, a dead loop (tick.DeadLoop) whose last
// write is older than grace, the time the tick has to resume it; then the endings owed, however
// old, the oldest's age; and whether any is lost.  False where a record is one Go cannot read.
func census(grace float64) (line string, lost, read bool) {
	now := time.Now()
	seconds := float64(now.UnixNano()) / 1e9
	var started, ended int
	var owed []float64
	var names []string
	read = run.Every(func(dir string, record *run.Object) bool {
		finished, dated := record.Num("finished_at")
		if run.OwesEnding(record, now) {
			if !dated {
				finished = run.LastWrite(dir)
			}
			owed = append(owed, seconds-finished)
		}
		if begun, ok := record.Num("started_at"); !ok || seconds-begun >= 86400 {
			return true
		}
		started++
		if run.Ended(record) {
			ended++
		} else if age := seconds - run.LastWrite(dir); age >= grace && tick.DeadLoop(dir, record, seconds) {
			names = append(names, fmt.Sprintf("%s (%s since last write)", filepath.Base(dir), terminal.FormatAge(age)))
		}
		return true
	})
	if !read {
		return "", false, false
	}
	noun := "endings"
	if len(owed) == 1 {
		noun = "ending"
	}
	line = fmt.Sprintf("%d started in the last day · %d ended · %d going · %d %s owed", started, ended, started-ended-len(names), len(owed), noun)
	if len(owed) > 0 {
		line += ", oldest " + terminal.FormatAge(slices.Max(owed))
	}
	if len(names) > 0 {
		line += " · lost: " + strings.Join(names, ", ")
	}
	return line, len(names) > 0, true
}
