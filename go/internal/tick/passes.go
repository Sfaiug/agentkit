package tick

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/gc"
	"agentkit/internal/handback"
	"agentkit/internal/host"
	"agentkit/internal/job"
	"agentkit/internal/leftover"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// A pass is one row of the tick, as one of Python's watch.local_passes.
type pass struct {
	name string
	dry  bool         // a dry tick runs it too, as Python's does
	idle func() bool  // whether it has nothing to act on, asked at its turn: false for a read Go cannot make
	step func() error // what Go carries out of it: errLeft where it finds what Go does not carry, else an error is its WARN line
}

// errLeft is a row that found what Go does not carry: the tick ends there, what the rows before
// did standing, and Python's tick, which runs next, finds that done, as every row does only what
// is due.
var errLeft = errors.New("left to Python")

// table is the tick's passes in the order Python's watch.local_passes runs them, the one home of
// their names and order. A later milestone fills a pass's step, and puts in its row each of those
// that act whatever the home holds: usage refresh, login reminder, browser tidy, machine check
// and harness upgrade.  Each row reads the seats at its own turn, and a home holding a seat
// Go does not read leaves the tick to Python at the first row that reads one. A step a dry tick
// runs checks t.dry where it would act; until it does, it is wet.
func table(t *ticking) []pass {
	seated := every(func(seat.Live) bool { return true })
	return []pass{
		{"merge checks", true, t.dryly(noMergeWork), t.wet(t.mergeChecks)},
		// installation establishes a baseline; another boot leaves recovery to Python
		{"boot resume", true, all(configured, seated, noBootResume), t.wet(bootBaseline)},
		{"held lines", false, all(configured, every(holdsNoLine)), nil},
		{"draft return", false, all(configured, seated, noneSetAside), nil},
		{"rebooted turns", false, all(configured, every(func(live seat.Live) bool { return !midturn(live, false) })), nil},
		{"login resume", true, noLoginResume, nil},
		// worker tokens are in secrets, and a run's parked login is on its run
		// a real tick reads each seat at its own turn, under its announce lock; a dry one, which
		// publishes nothing, reads them here
		{"seat health", true, all(configured, secretless, noRunHealthWork, t.dryly(every(healthy))), t.wet(t.health)},
		{"switched turns", false, configured, accountTurns},
		{"dead loops", true, all(configured, noDeadLoops), nil},
		{"dead jobs", true, jobless, nil},
		{"stall recovery", true, all(configured, noStallRecovery), nil},
		{"seat headroom", false, nil, t.giveWay},
		{"state save", false, nil, t.save},
		{"login reminder", false, nil, loginReminder},
		{"token reminder", false, nil, nil},
		{"exhausted resume", true, noExhaustedResume, nil},
		{"error retry", true, t.dryly(noErrorRetry), t.wet(t.errorRetry)},
		{"waiting resume", true, t.waitingIdle, t.wet(t.waiting)},
		{"old endings", false, nil, func() error {
			if !handback.MarkHistory(t.log.line) {
				return errLeft
			}
			return nil
		}},
		{"endings", false, t.endingsIdle, t.endings},
		{"job handbacks", false, jobless, nil},
		{"ended waits", false, all(configured, seated), t.endedWaits},
		{"owed lines", false, nil, t.owedLines},
		{"switch retirement", false, noSwitches, t.retire},
		{"seat tokens", false, run.Historyless, nil},
		{"history sync", false, run.Historyless, nil},
		{"history checkpoint", false, run.Historyless, nil},
		{"weekly audit", false, configured, t.audit},
		{"typed answers", false, every(unasked), nil},
		{"card transitions", false, cardsHeld, func() error { return cards(t.log.errOut) }},
		{"notification retry", true, nil, t.retryNotifications},
		{"end hook", false, nil, hookOptions},
		{"seat revival", false, configured, t.revive},
		{"idle sleep", false, all(configured, every(awake)), nil},
		{"git housekeeping", false, checkoutsSeen, t.housekeeping},
		// a due collection's units are Python's to clear where a user manager runs
		{"collection", false, func() bool { return !gc.Due() || !host.UserManager() }, func() error {
			gc.Schedule(t.log.line)
			return nil
		}},
		{"exit clocks", false, nil, t.stamp},
		{"seat sweep", false, all(noRunSweep, seated, t.retainedSeats), nil},
		{"ended logins", false, noLoginsToEnd, nil},
		{"leftover sweep", false, leftover.Tagless, func() error { leftover.Sweep(t.log.line); return nil }},
		{"rented machines", false, all(configured, noRenting), nil},
		{"project rules", false, checkoutsSeen, fetchProjects},
		{"project setups", false, checkoutsSeen, setups},
		{"alive checks", false, all(noSeatAlive, outageless), nil},
		{"night reads", false, noNights, t.nights},
		{"live update", false, liveUpdateIdle, t.liveUpdate},
	}
}

// dryly is read where the tick is a dry one, which carries out no wet step to read it in.
func (t *ticking) dryly(read func() bool) func() bool {
	return func() bool { return !t.dry || read() }
}

// wet is a step that does not check t.dry yet: a dry tick runs none of it, and its row's idle
// read answers for it.
func (t *ticking) wet(step func() error) func() error {
	if t.dry {
		return nil
	}
	return step
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

func jobless() bool { return empty(job.Jobs()) }

func secretless() bool { return empty(filepath.Join(config.Home(), "secrets")) }

// empty is whether the folder holds nothing, or is not there.
func empty(dir string) bool {
	entries, err := os.ReadDir(dir)
	return errors.Is(err, fs.ErrNotExist) || err == nil && len(entries) == 0
}
