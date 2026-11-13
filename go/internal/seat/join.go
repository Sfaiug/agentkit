package seat

import (
	"context"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"sync"

	"agentkit/internal/config"
	"agentkit/internal/notify"
	"agentkit/internal/run"
)

// Votes is whether every run that seat launched holds the project it votes for, settled by the
// launch that made it, or votes for none: one written before its launch's preflight, or before the
// field, is read from its task by Python's run_project, which Go does not, and one with no task,
// repository or task file to read belongs to none.
func Votes(name string) bool {
	for _, dir := range run.Dirs() {
		if record, _ := run.Read(dir); record != nil && run.Seat(record) == name && !record.Has("project") && !voteless(record) {
			return false
		}
	}
	return true
}

func voteless(record *run.Object) bool {
	_, err := os.Stat(filepath.Join(run.Runs(), record.Str("run_id"), "task.md"))
	return err != nil && !record.Truthy("repo") && record.Str("task_file") == ""
}

// JoinProject files that seat under the project most of its runs belong to, again at each launch,
// as Python's handback.join_session_project does: a seat filed by hand keeps its project, a tie
// or no votes keeps its filing, and of the most voted the first by name wins.  Counted under the
// seat's typing lock, so a count taken before a later launch's run was there is never written
// after that launch's.
func JoinProject(name string) error {
	return notify.Held(context.Background(), name, func(current string) error {
		state := filepath.Join(config.Home(), "state")
		record, err := run.ReadJSON(filepath.Join(state, "session-"+current+".json"))
		if errors.Is(err, fs.ErrNotExist) {
			return nil // a seat gone has nothing to file, its job's later tasks still its own
		}
		if record == nil || record.Has(config.Renamed) || record.Truthy("filed") {
			return err
		}
		filed, stands := record.Get("repo"), sync.OnceValue(listed)
		votes := map[string]int{}
		for _, dir := range run.Dirs() {
			if ran, _ := run.Read(dir); ran != nil && run.Seat(ran) == current {
				if checkout := checkoutOf(ran.Str("project"), stands); checkout != "" {
					votes[checkout]++
				}
			}
		}
		repo, most := filed, 0
		for _, count := range votes {
			most = max(most, count)
		}
		if held, _ := filed.(string); most > 0 && votes[held] != most {
			repo = nil
			for voted, count := range votes {
				if chosen, _ := repo.(string); count == most && (repo == nil || base(voted) < base(chosen) || base(voted) == base(chosen) && voted < chosen) {
					repo = voted
				}
			}
		}
		if run.Equal(repo, filed) {
			return nil
		}
		return update(state, current, set([]field{{"repo", repo}}))
	})
}
