package loop

import (
	"time"

	"agentkit/internal/helper"
	"agentkit/internal/turn"
)

// placeAgain is where the pieces still waiting once no place is left go, Python's turn_here: this
// host's heavy-suite turns, held on on, the machines asked each poll meanwhile (elsewhere), ending
// the wait holding none where one takes the suite: that machine, nil for the turns.  No ceiling is
// charged with the wait: it moves deadline on.
func (l *loop) placeAgain(cwd string, cpus, memory float64, cmd string, on *placement, deadline *time.Time) (there *helper.Away, err error) {
	ask := on.ask
	ask.Poll = l.elsewhere(cwd, cpus, memory, cmd, on.times, &there)
	began := time.Now()
	on.hold, err = turn.Take(l.ctx, ask)
	*deadline = deadline.Add(time.Since(began))
	return there, err
}

// elsewhere is the poll of a suite's wait for a turn here, Python's elsewhere: it asks the machines,
// and one that takes the suite, kept in there, ends the wait, as a look that fails ends the suite
// with its error.  What a look says is said once the suite goes there, not at each look.
func (l *loop) elsewhere(cwd string, cpus, memory float64, cmd, times string, there **helper.Away) func() (bool, error) {
	return func() (bool, error) {
		if _, err := l.stillWaits(); err != nil {
			return false, err
		}
		var said []string
		away, _, err := helper.Start(cwd, cpus, memory, cmd, times, nil, func(line string) { said = append(said, line) })
		if away != nil {
			for _, line := range said {
				l.say(line)
			}
			*there = away
		}
		return away != nil, err
	}
}
