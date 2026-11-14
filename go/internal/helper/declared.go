package helper

import (
	"strconv"
	"strings"
	"time"

	"agentkit/internal/host"
)

// kept is how long at most a bound found in a turn's container holds it before the machine is
// asked again, Python's machine_turn.KEPT: past the silence limit the watch asks every second, and
// a command ending before its bound holds the turn at most this long more.
const kept = 60 * time.Second

// Declared says, for the worker's Watch, whether a command in the turn's container is inside the
// time it gave `timeout`, Python's machine_turn._declared: the machine is asked again once the
// bound it last named ends, or kept on; one that does not answer holds nothing.  The argv it lists
// are read and dropped, never logged: a command line may hold what the turn was given.
func (t *Turn) Declared() func(now float64) bool {
	var until time.Time
	return func(float64) bool {
		if !time.Now().Before(until) {
			_, said := ask(t.away.Alias, 30*time.Second, nil, "processes", t.away.key)
			// from its arrival: the seconds each process has run were read as it was sent
			now, left := time.Now(), 0.0
			for _, line := range strings.Split(said, "\n") {
				words := strings.Fields(line)
				if len(words) == 0 {
					continue
				}
				if ran, err := strconv.ParseUint(words[0], 10, 64); err == nil {
					if bound := host.TimeoutSeconds(words[1:]); bound > 0 {
						left = max(left, bound-float64(ran))
					}
				}
			}
			until = now.Add(min(time.Duration(left*float64(time.Second)), kept))
		}
		return time.Now().Before(until)
	}
}
