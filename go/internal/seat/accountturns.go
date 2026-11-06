package seat

import (
	"context"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/notify"
	"agentkit/internal/run"
)

// AccountTurns is continue_turns(accounts=True) for lines the adapter took as a first prompt.
// Other continuations remain Python's at their own seat, before changing its mark.
func AccountTurns() (bool, error) {
	for _, path := range config.SeatFiles() {
		name, _ := sessionFile(filepath.Base(path))
		mark := revivalFile(name).Dict("midturn")
		if mark == nil || !mark.Truthy("account") {
			continue
		}
		if !mark.Truthy("launched") || !strings.HasPrefix(mark.Str("line"), strings.Split(heldContinue, "%s")[0]) {
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
			if mark.Str("boot") == host.BootID() && mark.Str("name") == current && Watching(current) && turn <= at && tries+1 < 3 {
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
