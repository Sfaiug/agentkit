package tick

import (
	"errors"

	"agentkit/internal/browser"
	"agentkit/internal/config"
	"agentkit/internal/gc"
	"agentkit/internal/googlecloud"
	"agentkit/internal/handback"
	"agentkit/internal/history"
	"agentkit/internal/host"
	"agentkit/internal/leftover"
	"agentkit/internal/machines"
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
// their names and order. A later milestone fills a pass's step. Each row reads the seats at its
// own turn, and a home holding a seat Go does not read leaves the tick to Python at the first row
// that reads one. A step a dry tick runs checks t.dry where it would act; until it does, it is wet.
func table(t *ticking) []pass {
	seated := every(func(seat.Live) bool { return true })
	return []pass{
		{"merge checks", true, t.dryly(noMergeWork), t.wet(t.mergeChecks)},
		{"boot resume", true, configured, t.bootResume},
		{"held lines", false, all(configured, every(holdsNoLine)), nil},
		{"draft return", false, all(configured, seated, noneSetAside), nil},
		{"rebooted turns", false, configured, continueTurns(false)},
		{"login resume", true, nil, t.loginResume},
		// a run's parked login is on its run
		{"seat health", true, all(configured, noRunHealthWork), t.health},
		{"switched turns", false, configured, continueTurns(true)},
		{"dead loops", true, all(configured, t.dryly(noDeadLoops)), t.wet(t.deadLoops)},
		{"dead jobs", true, noDeadJobs, nil},
		{"stall recovery", true, all(configured, noStallRecovery, t.dryly(noneParked)), t.wet(t.tellParked)},
		{"seat headroom", false, nil, t.giveWay},
		{"state save", false, nil, t.save},
		// a dry tick's reading is the snapshot as it stands, which no row Go carries reads
		{"usage refresh", true, configured, t.wet(refreshUsage)},
		{"login reminder", false, nil, t.remindLogins},
		{"token reminder", false, nil, t.remindTokens},
		{"exhausted resume", true, all(configured, unseated, t.dryly(noExhaustedResume)), t.wet(t.exhaustedResume)},
		{"error retry", true, t.dryly(noErrorRetry), t.wet(t.errorRetry)},
		{"waiting resume", true, nil, t.waiting},
		{"old endings", false, nil, func() error {
			if !handback.MarkHistory(t.log.line) {
				return errLeft
			}
			return nil
		}},
		{"endings", false, t.endingsIdle, t.endings},
		{"job handbacks", false, nil, t.jobHandbacks},
		{"ended waits", false, all(configured, seated), t.endedWaits},
		{"owed lines", false, nil, t.owedLines},
		{"switch retirement", false, checkoutsSeen, t.retire},
		{"seat tokens", false, nil, seatTokens},
		{"history sync", false, nil, func() error {
			if !history.Agree(t.log.line) {
				return errLeft
			}
			return nil
		}},
		{"history checkpoint", false, nil, func() error { history.Checkpoint(); return nil }},
		{"weekly audit", false, configured, t.audit},
		{"typed answers", false, every(answerable), t.typedAnswers},
		{"card transitions", false, cardsHeld, func() error { return cards(t.log.errOut, t.log.line) }},
		{"notification retry", true, nil, t.retryNotifications},
		{"server hooks", false, nil, hookOptions},
		{"seat revival", false, configured, t.revive},
		{"seat weights", false, nil, func() error { host.Front(); return nil }},
		{"idle sleep", false, configured, t.sleep},
		{"git housekeeping", false, checkoutsSeen, t.housekeeping},
		{"collection", false, nil, func() error {
			if !gc.Schedule(t.log.line) {
				return errLeft
			}
			return nil
		}},
		{"exit clocks", false, nil, t.stamp},
		{"seat sweep", false, nil, t.sweep},
		{"ended logins", false, noLoginsToEnd, nil},
		{"leftover sweep", false, nil, func() error {
			if !leftover.Sweep(t.log.line) {
				return errLeft
			}
			return nil
		}},
		{"browser tidy", false, nil, func() error {
			if !browser.Tidy(epoch(t.clock()), t.log.line) {
				return errLeft
			}
			return nil
		}},
		{"rented machines", false, configured, func() error {
			carried, err := googlecloud.Watch()
			if !carried {
				return errLeft
			}
			return err
		}},
		{"machine check", false, nil, machines.Check},
		{"project rules", false, checkoutsSeen, t.fetchProjects},
		{"project setups", false, checkoutsSeen, setups},
		{"alive checks", false, nil, t.alive},
		{"night reads", false, noNights, t.nights},
		{"live update", false, liveUpdateIdle, t.liveUpdate},
		{"harness upgrade", false, nil, t.harnessUpgrade},
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
