package loop

import (
	"time"

	"agentkit/internal/helper"
	"agentkit/internal/turn"
)

// placeAgain is where the pieces still waiting once no place is left go, Python's turn_here: this
// host's heavy-suite turns, held on on, the machines asked each poll meanwhile, ending the wait
// holding none where one takes the suite: that machine, nil for the turns.  No ceiling is charged
// with the wait: it moves deadline on.
func (l *loop) placeAgain(cwd string, cpus, memory float64, cmd string, on *placement, deadline *time.Time) (*helper.Away, error) {
	ask, there := on.ask, (*helper.Away)(nil)
	ask.Poll = func() (bool, error) {
		if _, err := l.stillWaits(); err != nil {
			return false, err
		}
		// a machine ak may rent since the suite began is Python's to rent: the wait goes on here
		there, _ = l.asked(cwd, cpus, memory, cmd, on.times)
		return there != nil, nil
	}
	began := time.Now()
	hold, err := turn.Take(l.ctx, ask)
	on.hold, *deadline = hold, deadline.Add(time.Since(began))
	return there, err
}

// asked is the machine that takes the suite, nil for none, Python's elsewhere: what the look says
// is said once the suite goes there, not at each look.
func (l *loop) asked(cwd string, cpus, memory float64, cmd, times string) (*helper.Away, error) {
	var said []string
	there, _, err := helper.Start(cwd, cpus, memory, cmd, times, l.changed, nil, func(line string) { said = append(said, line) })
	if there != nil {
		for _, line := range said {
			l.say(line)
		}
	}
	return there, err
}
