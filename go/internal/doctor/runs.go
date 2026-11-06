package doctor

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/host"
	"agentkit/internal/run"
	"agentkit/internal/terminal"
)

// census is the runs line, Python's watch.runs_health: the runs going, those ended today and the
// endings owed, the oldest's age, then each active run nothing works, dead; and whether a dead
// run's last write is older than grace, the time the tick has to resume it.  False where a record
// is one Go cannot read.
func census(grace float64) (line string, stuck, read bool) {
	now := time.Now()
	seconds := float64(now.UnixNano()) / 1e9
	var going, ended int
	var owed []float64
	var dead []string
	var resumed map[string]bool
	for _, dir := range run.Dirs() {
		record, err := run.Read(dir)
		if errors.Is(err, run.ErrLoneSurrogate) {
			return "", false, false
		}
		if record == nil {
			continue
		}
		if run.GoingState(record) {
			going++
		}
		finished, dated := record.Num("finished_at")
		if run.Ended(record) && dated && time.Unix(int64(finished), 0).Format(time.DateOnly) == now.Format(time.DateOnly) {
			ended++
		}
		if run.OwesEnding(record, now) {
			if !dated {
				finished = run.LastWrite(dir)
			}
			owed = append(owed, seconds-finished)
		}
		// a worker that calls doctor after its loop died is one of the run's processes too
		if !run.Active(record) || run.ProcessActive(record) || slices.ContainsFunc(host.Carrying(dir), live) {
			continue
		}
		if resumed == nil {
			resumed = resumes()
		}
		if resumed[filepath.Base(dir)] {
			continue
		}
		age := seconds - run.LastWrite(dir)
		dead = append(dead, fmt.Sprintf("%s (%s since last write)", filepath.Base(dir), terminal.FormatAge(age)))
		stuck = stuck || age >= grace
	}
	noun := "endings"
	if len(owed) == 1 {
		noun = "ending"
	}
	line = fmt.Sprintf("%d going · %d ended today · %d %s owed", going, ended, len(owed), noun)
	if len(owed) > 0 {
		line += ", oldest " + terminal.FormatAge(slices.Max(owed))
	}
	if len(dead) > 0 {
		line += " · dead: " + strings.Join(dead, ", ")
	}
	return line, stuck, true
}

// live is whether the process runs, not one that has exited and not yet been reaped.
func live(pid int) bool {
	stat, ok := host.ReadStat(pid)
	return ok && !stat.Exited()
}

// resumes are the runs an `ak run resume <id>` runs for: a live process whose arguments after the
// program are exactly those, whatever program file runs it.
func resumes() map[string]bool {
	found := map[string]bool{}
	entries, _ := os.ReadDir("/proc")
	for _, entry := range entries {
		pid, err := strconv.Atoi(entry.Name())
		if err != nil || !live(pid) {
			continue
		}
		said, err := os.ReadFile("/proc/" + entry.Name() + "/cmdline")
		args := strings.Split(strings.TrimSuffix(string(said), "\x00"), "\x00")
		if err == nil && len(args) == 4 && args[1] == "run" && args[2] == "resume" {
			found[args[3]] = true
		}
	}
	return found
}
