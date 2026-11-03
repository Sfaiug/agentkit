package tick

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"

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
	idle func() bool  // whether it has nothing to act on, asked at its turn: false for a read Go cannot make
	step func() error // what Go carries out of it: errLeft where it finds what Go does not carry, else an error is its WARN line
}

// errLeft is a row that found what Go does not carry: the tick ends there, what the rows before
// did standing, and Python's tick, which runs next, finds that done, as every row does only what
// is due.
var errLeft = errors.New("left to Python")

// table is the tick's passes in the order Python's watch.local_passes runs them, the one home of
// their names and order. A later milestone fills a pass's step, and puts in its row each of those
// that act whatever the home holds: usage refresh, login reminder, browser tidy, machine check, live
// update and harness upgrade.  Each row reads the seats at its own turn, and a home holding a seat
// Go does not read leaves the tick to Python at the first row that reads one.
func table(t *ticking) []pass {
	seated := every(func(seat.Live) bool { return true })
	return []pass{
		{"merge checks", true, runless, nil},
		// a boot it has not seen moves only its baseline, with every seat it would resume up
		{"boot resume", true, all(configured, seated, restingGone), bootBaseline},
		{"held lines", false, all(configured, every(holdsNoLine)), nil},
		{"draft return", false, all(configured, seated, noneSetAside), nil},
		{"rebooted turns", false, all(configured, every(func(live seat.Live) bool { return !midturn(live, false) })), nil},
		{"login resume", true, runless, nil},
		// worker tokens are in secrets, and a run's parked login is on its run
		// a real tick reads each seat at its own turn, under its announce lock; a dry one, which
		// publishes nothing, reads them here
		{"seat health", true, all(configured, secretless, runless, t.dryly(every(healthy))), health},
		{"switched turns", false, all(configured, every(func(live seat.Live) bool { return !midturn(live, true) })), nil},
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
		{"ended waits", false, all(configured, every(waitsOnNothing)), nil},
		{"owed lines", false, every(func(live seat.Live) bool { return !live.File.Truthy("owed_lines") }), nil},
		{"switch retirement", false, noSwitches, t.retire},
		{"seat tokens", false, run.Historyless, nil},
		{"history sync", false, run.Historyless, nil},
		{"history checkpoint", false, run.Historyless, nil},
		{"weekly audit", false, all(configured, config.AuditOff), nil},
		{"typed answers", false, every(unasked), nil},
		{"card transitions", false, cardsHeld, cards},
		{"notification retry", true, func() bool {
			return empty(filepath.Join(config.Home(), "state", "notification-outbox"))
		}, nil},
		{"end hook", false, nil, hookOptions},
		{"seat revival", false, all(configured, runless, restingGone), revive},
		{"idle sleep", false, all(configured, every(awake)), nil},
		{"git housekeeping", false, all(runless, checkoutsSeen), t.housekeeping},
		// a due collection's units are Python's to clear where a user manager runs
		{"collection", false, func() bool { return !gc.Due() || !host.UserManager() }, func() error {
			gc.Schedule(t.log.line)
			return nil
		}},
		{"exit clocks", false, nil, t.stamp},
		{"seat sweep", false, all(runless, seated), nil},
		{"ended logins", false, noLoginsToEnd, nil},
		{"leftover sweep", false, leftover.Tagless, func() error { leftover.Sweep(t.log.line); return nil }},
		{"rented machines", false, all(configured, noRenting), nil},
		{"project rules", false, checkoutsSeen, fetchProjects},
		{"project setups", false, checkoutsSeen, setups},
		{"alive checks", false, all(noSeatAlive, outageless), nil},
		{"night reads", false, noNights, t.nights},
	}
}

// dryly is read where the tick is a dry one, which carries out no step to read it in.
func (t *ticking) dryly(read func() bool) func() bool {
	return func() bool { return !t.dry || read() }
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
