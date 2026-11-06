package seat

import (
	"context"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/notify"
	"agentkit/internal/run"
)

// ContinueTurns is continue_turns, for the marks of moves to another account (accounts) or else of
// reboots: a line its adapter took as a first prompt waits, three passes at most, for that prompt's
// stamp, and the mark of a seat gone again, or of another boot, comes off.  A line still to type
// into a seat up on this boot remains Python's, before its mark changes.
func ContinueTurns(accounts bool) (bool, error) {
	for _, path := range config.SeatFiles() {
		name, _ := sessionFile(filepath.Base(path))
		mark := revivalFile(name).Dict("midturn")
		if mark == nil || mark.Truthy("account") != accounts {
			continue
		}
		if !mark.Truthy("launched") && mark.Str("boot") == host.BootID() && Watching(name) {
			return false, nil
		}
		err := notify.Held(context.Background(), name, func(current string) error {
			if !run.Equal(revivalFile(current).Get("midturn"), mark) {
				return nil
			}
			at, _ := mark.Num("at")
			stop, _ := run.ReadJSON(ownFile("stop", current))
			turn := 0.0
			if stop != nil {
				turn, _ = stop.Num("turn")
			}
			tries, _ := mark.Int("tries")
			var next any
			if mark.Truthy("launched") && mark.Str("boot") == host.BootID() && mark.Str("name") == current && Watching(current) && turn <= at && tries+1 < 3 {
				next = mark.Copy()
				next.(*run.Object).Set("tries", tries+1)
			}
			return Write(current, "midturn", next)
		})
		if err != nil {
			return true, err
		}
	}
	return true, nil
}
