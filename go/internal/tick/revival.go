package tick

import (
	"cmp"

	"agentkit/internal/host"
	"agentkit/internal/seat"
)

// A first baseline and an unchanged boot resume nobody. Recovery after another boot is still
// Python's, before any later row acts on the seats it would reopen.
func noBootResume() bool {
	state, known := loadState()
	return known && (state.Str("boot_id") == "" || host.BootID() == "" ||
		state.Str("boot_id") == host.BootID() || restingGone())
}

func (t *ticking) revive() error {
	if !noRunRevival() && !seat.FileProjects(t.clock()) {
		return errLeft
	}
	home, known := seat.Looking(t.clock())
	if !known {
		return errLeft
	}
	carried, err := home.ReviveQuestions(t.clock(), t.log.line, t.log.errOut)
	if !carried {
		return cmp.Or(err, errLeft)
	}
	return err
}

func (t *ticking) owedLines() error {
	carried, err := seat.TellRevivalLines(t.log.line)
	if !carried {
		return cmp.Or(err, errLeft)
	}
	return err
}
