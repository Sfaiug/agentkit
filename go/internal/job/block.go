package job

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"sort"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// A Shown job is one `ak run status` shows: its directory and its receipt.
type Shown struct {
	Dir     string
	Receipt *run.Object
}

// Listed are the jobs `ak run status` shows, newest started first (status.cmd_status): the seat's,
// or every one outside a seat, that finished in the last seven days or not yet, all of them with
// history.  False where a receipt holds what Go cannot keep.
func Listed(seat string, history bool, now time.Time) ([]Shown, bool) {
	var shown []Shown
	entries, _ := os.ReadDir(Jobs())
	for _, entry := range entries {
		dir := filepath.Join(Jobs(), entry.Name())
		if info, err := os.Stat(dir); err != nil || !info.IsDir() {
			continue
		}
		receipt, err := Read(dir)
		if errors.Is(err, run.ErrLoneSurrogate) {
			return nil, false
		}
		if receipt == nil {
			continue
		}
		if _, ok := receipt.Get("tasks").([]any); !ok {
			continue
		}
		// a job names the seat it was launched from `seat`; it resolves as a run's does
		launched := run.Fields("launched_session", receipt.Get("seat"))
		if seat != "" && run.Seat(launched) != seat {
			continue
		}
		if at, ok := receipt.Num("finished_at"); !history && ok && seconds(now)-at > run.GCAge {
			continue
		}
		shown = append(shown, Shown{dir, receipt})
	}
	sort.SliceStable(shown, func(i, j int) bool {
		return run.FirstNumber(shown[i].Receipt, "started_at") > run.FirstNumber(shown[j].Receipt, "started_at")
	})
	return shown, true
}

// Runs are the ids of the runs the job's tasks name.
func (s Shown) Runs() []string {
	var ids []string
	for _, task := range tasks(s.Receipt) {
		if id := task.Str("run_id"); id != "" {
			ids = append(ids, id)
		}
	}
	return ids
}

// Block is the job's lines in `ak run status`: how many of its tasks are in each state, a line
// when its launcher is gone, and each task's verdict as its run stands now.  `runs` is a task's
// run as the listing reaped it, nil for none.  Nothing is written.
func (s Shown) Block(runs func(id string) *run.Object, models map[string]config.Model, index run.Index, now time.Time) []string {
	// a finished job's launcher has nothing left to do (job.reap_job)
	alive := s.Receipt.Truthy("finished_at") || run.ProcessActive(s.Receipt)
	read := func(task *run.Object) *run.Object {
		if record := runs(task.Str("run_id")); record != nil {
			return record
		}
		return run.NewObject()
	}
	current := s.current(alive, read, models, index)
	lines := []string{"job " + run.Text(s.Receipt.Get("job_id")) + ": " + counts(current)}
	if !alive {
		lines = append(lines, s.goneLine(read, now))
	}
	for _, task := range current {
		if task.Truthy("verdict_line") {
			lines = append(lines, "  "+run.Text(task.Get("verdict_line")))
		}
	}
	return lines
}

// current is each task as its run stands now (job.job_now).  A job writes a task's word and line
// as the task settles and never again, so a settled task, and every task of a job whose launcher
// is gone, reads its run's word now; a task the live launcher still drives keeps its own, as its
// ladder may yet resume or rerun the run.  A line stops saying `needs you` once the job's line
// was handed back to its seat, or the task's run is settled.
func (s Shown) current(alive bool, read func(*run.Object) *run.Object, models map[string]config.Model, index run.Index) []*run.Object {
	card := s.Receipt.Dict("card_sent")
	handed := card != nil && card.Str("kind") == "handback" || s.Receipt.Truthy("handback_pending")
	var shown []*run.Object
	for _, task := range tasks(s.Receipt) {
		record := read(task)
		if record.Truthy("state") && (!alive || slices.Contains(Terminal, task.Str("state"))) {
			word := run.Text(record.Get("state"))
			switch {
			case record.Truthy("merged"):
				// a merge is merged whatever today's config makes of its review's providers
				word = "merged"
			case run.Ended(record):
				word = Classify(record, models)
			case word == "waiting":
				word = "waiting to merge"
			}
			// a run that finished after the job wrote its line has new rounds to tell
			if word != task.Str("state") || run.FirstNumber(record, "finished_at") > run.FirstNumber(task, "finished_at") {
				line := run.Text(task.Get("name")) + ": " + word
				if run.Ended(record) {
					line = VerdictLine(task, word, record)
				}
				task = task.Copy()
				run.SetAll(task, "state", word, "verdict_line", line)
			}
		}
		if task.Truthy("verdict_line") && (handed || index.Settled(record)) {
			task = task.Copy()
			task.Set("verdict_line", strings.ReplaceAll(task.Str("verdict_line"), ": needs you", ""))
		}
		shown = append(shown, task)
	}
	return shown
}

// counts is how many tasks are in each state (job.job_block_line): running and queued first,
// then the ends, then any other word a task's run gave, as it first came.
func counts(tasks []*run.Object) string {
	tally, seen := map[string]int{}, []string{}
	for _, task := range tasks {
		state := run.Text(task.Get("state"))
		if tally[state] == 0 {
			seen = append(seen, state)
		}
		tally[state]++
	}
	first := []string{"running", "queued", "merged", "passed", "skipped", "failed", "blocked", "stopped"}
	var parts []string
	for _, state := range slices.Concat(first, slices.DeleteFunc(seen, func(state string) bool { return slices.Contains(first, state) })) {
		if tally[state] > 0 {
			parts = append(parts, fmt.Sprintf("%d %s", tally[state], state))
		}
	}
	if parts == nil {
		return "no tasks"
	}
	return strings.Join(parts, ", ")
}

// goneLine is the line under a job whose launcher is gone: whose it is to go on (job.job_gone_line).
func (s Shown) goneLine(read func(*run.Object) *run.Object, now time.Time) string {
	if why := s.admission(read, now); why != "" {
		return "  launcher gone; the next tick relaunches it · " + why
	}
	id := filepath.Base(s.Dir)
	return "  launcher gone; ak run resume " + id + " to continue, ak run stop " + id + " to end it"
}

// admission is why the tick may relaunch the job, or "" where that is a person's (job.job_admission):
// a seat launched it, that seat, by its name now, still exists and its owner did not close it, the
// directory it was launched from is still there, no task or its run was stopped, no run of an
// unfinished task that stopped short of its ending was handed back, told or looked at, and the
// launcher wrote in its directory under a day ago, not twice relaunched in the hour before.
func (s Shown) admission(read func(*run.Object) *run.Object, now time.Time) string {
	if !s.Receipt.Truthy("seat") {
		return ""
	}
	seat, _, err := config.ResolveSession(s.Receipt.Str("seat"))
	if err != nil || seat == "" {
		return ""
	}
	if path, err := config.SessionPath(seat); err != nil || !regular(path) {
		return ""
	}
	if file, _ := run.ReadJSON(filepath.Join(config.Home(), "state", "seat-"+seat+".json")); file != nil && file.Truthy("closed_by_owner") {
		return ""
	}
	if info, err := os.Stat(s.Receipt.Str("cwd")); !s.Receipt.Truthy("cwd") || err != nil || !info.IsDir() {
		return ""
	}
	for _, task := range tasks(s.Receipt) {
		record := read(task)
		if task.Str("state") == "stopped" || record.Str("state") == "stopped" {
			return ""
		}
		if !slices.Contains(Terminal, task.Str("state")) && !run.Ended(record) &&
			(record.Truthy("handed_back") || record.Truthy("recovery_notified") || record.Truthy("recovery_acknowledged_at")) {
			return ""
		}
	}
	// a launcher dies without writing an ending: its heartbeat stands in for one
	alive := run.LastWrite(s.Dir)
	if ago := seconds(now) - alive; ago < 0 || ago >= 86400 {
		return ""
	}
	relaunched := 0
	for _, at := range s.Receipt.List("relaunches") {
		if at, ok := run.Num(at); ok && 0 <= alive-at && alive-at < run.DeadWindow {
			relaunched++
		}
	}
	if relaunched >= 2 {
		return ""
	}
	return "session " + seat + " exists; alive under 24h ago; no task stopped"
}

// tasks are the receipt's tasks Go reads.
func tasks(receipt *run.Object) []*run.Object {
	var found []*run.Object
	for _, each := range receipt.List("tasks") {
		if task, ok := each.(*run.Object); ok {
			found = append(found, task)
		}
	}
	return found
}

func regular(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.Mode().IsRegular()
}

func seconds(at time.Time) float64 {
	return float64(at.UnixNano()) / 1e9
}
