package tick

import (
	"time"

	"agentkit/internal/seat"
)

func restingGone() bool {
	home, known := seat.Looking(time.Now())
	return known && home.RestingGone()
}

func stampGone(now time.Time) error {
	home, known := seat.Looking(now)
	if !known {
		return errLeft
	}
	return home.StampGone(now)
}

func seatProjects() ([]string, error) {
	home, known := seat.Looking(time.Now())
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
