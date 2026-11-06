package tick

import (
	"time"

	"agentkit/internal/seat"
)

func stampGone(now time.Time) error {
	home, known := seat.TickHome(now)
	if !known {
		return errLeft
	}
	return home.StampGone(now)
}

func seatProjects() ([]string, error) {
	home, known := seat.TickHome(time.Now())
	if !known {
		return nil, errLeft
	}
	return home.Repositories(), nil
}

// sweep is the seat sweep row, the one sweep the ak screen's opening runs too.
func (t *ticking) sweep() error {
	carried, err := seat.Sweep(t.clock(), t.log.line)
	if !carried {
		return errLeft
	}
	return err
}
