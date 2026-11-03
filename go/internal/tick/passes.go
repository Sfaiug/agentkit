package tick

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"sync"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/gc"
	"agentkit/internal/host"
	"agentkit/internal/job"
	"agentkit/internal/leftover"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// A pass is one row of the tick, as one of Python's watch.local_passes.
type pass struct {
	name string
	dry  bool         // a dry tick reads it too
	idle func() bool  // whether it has nothing to act on: false for a read Go cannot make
	step func() error // what Go carries out of it: an error is its WARN line
}

// table is the tick's passes in the order Python's watch.local_passes runs them, the one home of
// their names and order. A later milestone fills a pass's step, and puts in its row each of those
// that act whatever the home holds: usage refresh, login reminder, browser tidy, machine check, live
// update and harness upgrade.  The seats are read once, before any step (t.seats), and a home
// holding any other seat leaves every row that reads one to Python.
func table(t *ticking) []pass {
	if t.seats == nil {
		t.seats = sync.OnceValues(func() ([]seat.Live, bool) { return seat.Lives(time.Now()) })
	}
	seated := t.every(func(seat.Live) bool { return true })
	return []pass{
		{"merge checks", true, runless, nil},
		// a boot it has not seen moves only its baseline, with every seat it would resume up
		{"boot resume", true, all(configured, seated), bootBaseline},
		{"held lines", false, all(configured, t.every(holdsNoLine)), nil},
		{"draft return", false, all(configured, seated, noneSetAside), nil},
		{"rebooted turns", false, all(configured, t.every(func(live seat.Live) bool { return !midturn(live, false) })), nil},
		{"login resume", true, runless, nil},
		// worker tokens are in secrets, and a run's parked login is on its run
		{"seat health", true, all(configured, secretless, runless, t.every(healthy)), t.health},
		{"switched turns", false, all(configured, t.every(func(live seat.Live) bool { return !midturn(live, true) })), nil},
		{"dead loops", true, all(configured, runless), nil},
		{"dead jobs", true, jobless, nil},
		{"stall recovery", true, all(configured, runless), nil},
		{"lease scan", false, runless, nil},
		{"lease restart", false, runless, nil},
		{"seat headroom", false, nil, t.giveWay},
		{"state save", false, nil, t.save},
		{"token reminder", false, nil, nil},
		// its workers are the seat's own selection, which Go does not read yet
		{"exhausted resume", true, func() bool {
			return configured() && os.Getenv("AGENTKIT_SESSION") == "" && runless()
		}, nil},
		{"error retry", true, runless, nil},
		{"waiting resume", true, runless, nil},
		{"old endings", false, runless, nil},
		{"endings", false, runless, nil},
		{"job handbacks", false, jobless, nil},
		{"ended waits", false, all(configured, t.every(waitsOnNothing)), nil},
		{"owed lines", false, t.every(func(live seat.Live) bool { return !live.File.Truthy("owed_lines") }), nil},
		{"switch retirement", false, noSwitches, t.retire},
		{"seat tokens", false, run.Historyless, nil},
		{"history sync", false, run.Historyless, nil},
		{"history checkpoint", false, run.Historyless, nil},
		{"weekly audit", false, all(configured, config.AuditOff), nil},
		{"typed answers", false, t.every(unasked), nil},
		{"card transitions", false, all(t.cardsHeld, t.every(uncarded)), t.cards},
		{"notification retry", true, func() bool {
			return empty(filepath.Join(config.Home(), "state", "notification-outbox"))
		}, nil},
		{"end hook", false, nil, hookOptions},
		{"seat revival", false, all(configured, runless, seated), t.revive},
		{"idle sleep", false, all(configured, t.every(awake)), nil},
		{"git housekeeping", false, all(runless, seated, checkoutsSeen), t.housekeeping},
		// a due collection's units are Python's to clear where a user manager runs
		{"collection", false, func() bool { return !gc.Due() || !host.UserManager() }, func() error {
			gc.Schedule(t.log.line)
			return nil
		}},
		{"exit clocks", false, seated, t.stamp},
		{"seat sweep", false, all(runless, seated), nil},
		{"ended logins", false, noLoginsToEnd, nil},
		{"leftover sweep", false, leftover.Tagless, func() error { leftover.Sweep(t.log.line); return nil }},
		{"rented machines", false, all(configured, noRenting), nil},
		{"project rules", false, all(seated, checkoutsSeen), t.fetchProjects},
		{"project setups", false, checkoutsSeen, setups},
		{"alive checks", false, all(t.every(declaresNoAlive), outageless), nil},
		{"night reads", false, noNights, t.nights},
	}
}

// idle is whether watch.json and every pass the tick t runs say there is nothing to act on, read
// with nothing written. The state folder comes first: the passes' seat records are listed from it.
func idle(t *ticking, dry bool) bool {
	if state, ok := loadState(); !ok || !quiet(state) || !config.Listable(statePath("")) {
		return false
	}
	for _, each := range table(t) {
		if (each.dry || !dry) && each.idle != nil && !each.idle() {
			return false
		}
	}
	return true
}

func all(reads ...func() bool) func() bool {
	return func() bool {
		for _, read := range reads {
			if !read() {
				return false
			}
		}
		return true
	}
}

// configured is whether the config loads; Python's passes that load it warn where it does not.
func configured() bool { return config.Check() == nil }

func runless() bool { return empty(run.Runs()) }

func jobless() bool { return empty(job.Jobs()) }

func secretless() bool { return empty(filepath.Join(config.Home(), "secrets")) }

// empty is whether the folder holds nothing, or is not there.
func empty(dir string) bool {
	entries, err := os.ReadDir(dir)
	return errors.Is(err, fs.ErrNotExist) || err == nil && len(entries) == 0
}
