package tick

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"sync"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/job"
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
// that act whatever the home holds: usage refresh, login reminder, collection, browser tidy,
// machine check, live update and harness upgrade.
func table(t *ticking) []pass {
	seatless := sync.OnceValue(func() bool { return len(config.SeatFiles()) == 0 && seat.OnNoServer() })
	return []pass{
		{"merge checks", true, runless, nil},
		// a boot it has not seen moves only its baseline, with no seat to resume
		{"boot resume", true, all(configured, seatless), bootBaseline},
		{"held lines", false, all(configured, seatless), nil},
		{"draft return", false, all(configured, seatless), nil},
		{"rebooted turns", false, all(configured, seatless), nil},
		{"login resume", true, runless, nil},
		// worker tokens are in secrets, and a run's parked login is on its run
		{"seat health", true, all(configured, secretless, seatless, runless), nil},
		{"switched turns", false, all(configured, seatless), nil},
		{"dead loops", true, all(configured, runless), nil},
		{"dead jobs", true, jobless, nil},
		{"stall recovery", true, all(configured, runless), nil},
		{"lease scan", false, runless, nil},
		{"lease restart", false, runless, nil},
		{"seat headroom", false, host.NoSliceCeiling, nil},
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
		{"ended waits", false, all(configured, seatless), nil},
		{"owed lines", false, seatless, nil},
		// it reads its record before it asks each checkout for its switches
		{"switch retirement", false, seat.NoCheckouts, retireRead},
		{"seat tokens", false, all(seatless, run.Historyless), nil},
		{"history sync", false, run.Historyless, nil},
		{"history checkpoint", false, run.Historyless, nil},
		{"weekly audit", false, all(configured, config.AuditOff), nil},
		{"typed answers", false, seatless, nil},
		{"card transitions", false, all(seatless, cardless), nil},
		{"notification retry", true, func() bool {
			return empty(filepath.Join(config.Home(), "state", "notification-outbox"))
		}, nil},
		{"end hook", false, seatless, nil},
		{"seat revival", false, all(configured, runless, seatless), nil},
		{"idle sleep", false, all(configured, seatless), nil},
		{"git housekeeping", false, all(runless, seatless, seat.NoCheckouts), nil},
		{"exit clocks", false, seatless, nil},
		{"seat sweep", false, all(runless, seatless), nil},
		{"ended logins", false, noLoginsToEnd, nil},
		{"leftover sweep", false, noLeftovers, nil},
		{"rented machines", false, all(configured, noRenting), nil},
		{"project rules", false, all(seatless, seat.NoCheckouts), nil},
		{"project setups", false, seat.NoCheckouts, nil},
		{"alive checks", false, all(seatless, outageless), nil},
		{"night reads", false, seat.NoCheckouts, nil},
	}
}

// idle is whether watch.json and every pass the tick runs say there is nothing to act on, read
// with nothing written. The state folder comes first: the passes' seat records are listed from it.
func idle(dry bool) bool {
	if state, ok := loadState(); !ok || !quiet(state) || !config.Listable(statePath("")) {
		return false
	}
	for _, each := range table(&ticking{}) {
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
