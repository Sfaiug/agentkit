package loop

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"time"

	"agentkit/internal/helper"
	"agentkit/internal/host"
	"agentkit/internal/run"
	"agentkit/internal/turn"
)

// errTurnPython is a heavy-suite turn's case Go leaves to Python, said before anything is written: a
// line's check whose member left its line, which Python goes on with as a round check.
var errTurnPython = errors.New("not Go's yet")

// A placement is where one heavy command runs, Python's gate_turn: on this host's heavy-suite
// turns, or as a suite in pieces on the suite helper's machine that took it, which takes none here.
type placement struct {
	hold   *turn.Hold
	ask    turn.Ask     // how it waits for a turn again once it answered busy
	busied bool         // and that it did, said once
	away   *helper.Away // the machine that took it, nil for none
	here   string       // why it runs here
}

// holds is whether the command runs on a turn here, which it is told (host.HeavyTurn).
func (p *placement) holds() bool { return p != nil && p.hold != nil }

// close gives the turns back and the machine its tree, once.
func (p *placement) close() {
	if p != nil {
		p.hold.Give()
		if p.away != nil {
			p.away.Finish()
			p.away = nil
		}
	}
}

// heavy is whether cmd waits for this host's heavy-suite turn before it starts, as Python's checks
// do: a suite in pieces, a round's suite, a `# once` command and whatever a line's checker runs,
// but tests named alone, which cost what a model's own test does: on a host out of CPU no turn
// comes until it is idle, and that wait held whole lines up to an hour (30 Oct 2026).
func (l *loop) heavy(cmd string, selection *checkSelection) bool {
	if selection != nil && selection.tests != nil {
		return false
	}
	return l.line != "" || l.changed != "" || slices.Contains(l.once, cmd) || namesShard.MatchString(cmd) && !selection.pinned()
}

// placed is where cmd runs, nil for a light one: a suite in pieces on the suite helper that takes
// it, else on every turn its pieces fit here, asking the helpers again at each look, and any other
// heavy command on one turn.  path is the check's log, which says the wait.
func (l *loop) placed(cwd, cmd string, selection *checkSelection, path string) (*placement, error) {
	if !l.heavy(cmd, selection) {
		return nil, nil
	}
	at := &placement{ask: turn.Ask{Dir: l.dir, Line: l.line != "", Log: path, Say: l.say, Poll: l.stillWaits}}
	ask := at.ask
	if namesShard.MatchString(cmd) && !selection.pinned() {
		cpus, memory := suiteCost(l.dir, cwd, cmd)
		at.ask.Pieces, at.ask.CPUs, at.ask.MemoryMB = true, cpus, memory
		ask = at.ask
		var err error
		if at.away, at.here, err = helper.Start(cwd, cpus, memory, cmd, nil, l.say); err != nil || at.away != nil {
			return at, err
		}
		l.say("suite runs here: " + at.here)
		ask.Poll = func() (bool, error) {
			if _, err := l.stillWaits(); err != nil {
				return false, err
			}
			// what a look says is said once the suite goes there, not at each look
			var said []string
			away, _, err := helper.Start(cwd, cpus, memory, cmd, nil, func(line string) { said = append(said, line) })
			if away != nil {
				for _, line := range said {
					l.say(line)
				}
				at.away = away
			}
			return away != nil, err
		}
	}
	var err error
	at.hold, err = turn.Take(l.ctx, ask)
	return at, err
}

// again is whether cmd, which ended so on the placement's turn, answered that the turn is busy
// (host.SuiteBusy): its own host-wide lock is another copy's, so it never ran, and runs again.  As
// Python's busy_turn, it first gives its turn back for a poll, which every other suite may use
// meanwhile and which counts toward the ceiling, so a command that only ever says busy still ends,
// then waits for one as a new waiter (turnHere).
func (l *loop) again(on *placement, cmd string, ended ran, deadline *time.Time) (bool, error) {
	if !on.holds() || ended.code != host.SuiteBusy || ended.stopped != "" {
		return false, nil
	}
	if !on.busied {
		on.busied = true
		l.say(fmt.Sprintf("done-when: busy: %s exited %d; it runs again each poll, its heavy suite turn given back meanwhile", cmd, host.SuiteBusy))
	}
	on.hold.Give()
	on.hold = nil
	select {
	case <-l.ctx.Done():
		return false, context.Cause(l.ctx)
	case <-time.After(turn.Poll):
	}
	if _, err := l.stillWaits(); err != nil {
		return false, err
	}
	err := l.turnHere(on, deadline)
	return err == nil, err
}

// turnHere takes one turn here for what runs alone where the placement holds none, Python's
// turn_here: a whole piece of a suite that ran on the suite helper, or a command that answered
// busy.  No ceiling is charged with the wait: it moves deadline on.
func (l *loop) turnHere(on *placement, deadline *time.Time) error {
	if on.holds() {
		return nil
	}
	began := time.Now()
	hold, err := turn.Take(l.ctx, on.ask)
	hold.Alone() // a suite in pieces runs it alone, after the others
	on.hold = hold
	*deadline = deadline.Add(time.Since(began))
	return err
}

// stillWaits ends a wait for a turn that no longer has one coming: the run stopped, or a line's
// check's member left that line.
func (l *loop) stillWaits() (bool, error) {
	if err := l.stopCheck(); err != nil || l.line == "" {
		return false, err
	}
	if record, _ := run.Read(l.dir); record == nil || !run.Member(record) || landingLine(record) != l.line {
		return false, fmt.Errorf("%s left %s while its check waited for a heavy suite turn: %w", l.id, l.line, errTurnPython)
	}
	return false, nil
}
