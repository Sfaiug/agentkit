package tick

import (
	"time"

	"agentkit/internal/seat"
)

func restingGone() bool {
	home, known := seat.TickHome(time.Now())
	return known && home.RestingGone()
}

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

func noSeatAlive() bool {
	repos, err := seatProjects()
	if err != nil {
		return false
	}
	for _, repo := range repos {
		if declares(repo, "alive") {
			return false
		}
	}
	return true
}

func (t *ticking) retainedSeats() bool {
	now := t.clock()
	home, known := seat.TickHome(now)
	return known && home.Retained(now)
}
