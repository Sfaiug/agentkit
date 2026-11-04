package seat

import (
	"fmt"
	"time"

	"agentkit/internal/run"
)

// going is shared by the seat's word and tally, including Read's vetted legacy records.
func (each ran) going() bool {
	if each.view != nil {
		return each.view.going
	}
	return each.record.Str("state") == "running"
}

func tally(mine []ran, now time.Time) string {
	if len(mine) == 0 {
		return "no runs yet"
	}
	going, needs, merged := 0, 0, 0
	for _, each := range mine {
		switch {
		case each.going():
			going++
		case each.view != nil && each.view.needs:
			needs++
		case each.record.Truthy("merged"):
			finished := run.FirstNumber(each.record, "finished_at", "started_at")
			if seconds(now)-run.GCAge <= finished && finished <= seconds(now) {
				merged++
			}
		}
	}
	if needs > 0 {
		return fmt.Sprintf("%d running · %d needs you", going, needs)
	}
	return fmt.Sprintf("%d running · %d merged", going, merged)
}
