package tick

import (
	"cmp"
	"fmt"
	"io"
	"time"

	"agentkit/internal/notify"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

func (t *ticking) revive() error {
	if !noRunRevival() && !seat.FileProjects(t.clock()) {
		return errLeft
	}
	going, known := revivalRuns()
	if !known {
		return errLeft
	}
	home, known := seat.TickHome(t.clock())
	if !known {
		return errLeft
	}
	carried, err := home.ReviveTurns(t.clock(), going, t.log.line, t.log.errOut)
	if !carried {
		return cmp.Or(err, errLeft)
	}
	if err != nil {
		return err
	}
	return t.reviveRuns(going)
}

// The claim precedes the launch under the lifecycle lock: a failed open is tried once,
// and an owner's close cannot land between the decision and the reopen.
func (t *ticking) reviveRuns(going map[string]string) error {
	return locked(func() error {
		home, known := seat.TickHome(t.clock())
		if !known {
			return errLeft
		}
		for _, each := range home.Revivals() {
			// a live seat's deaths are ReviveTurns' to clear, read before it reopened any
			if each.Live || each.Closed {
				continue
			}
			id := going[each.Name]
			if id == "" {
				continue
			}
			if !each.Supported {
				return errLeft
			}
			now := epoch(t.clock())
			deaths := each.File.List("reopened_at")
			if each.File.Truthy("reopened_at") && deaths == nil {
				deaths = []any{each.File.Get("reopened_at")}
			}
			if len(deaths) > 0 {
				last, ok := run.Num(deaths[len(deaths)-1])
				// A paged failure stays the owner's until seen live, however old its claim.
				if each.Failed || !ok || now-last < 600 || len(deaths) > 2 {
					continue
				}
			}
			if !each.CanOpen {
				return errLeft
			}
			recent := []any{}
			for _, death := range deaths {
				if at, ok := run.Num(death); ok && now-at < 3600 {
					recent = append(recent, death)
				}
			}
			if err := seat.Write(each.Name, "reopened_at", append(recent, run.Float(now))); err != nil {
				return err
			}
			why := "it died again both times it was reopened within the hour"
			if len(recent) < 2 {
				var err error
				if why, err = t.reopen(each, "continue: your run "+id+" is still going; pick up where you left off"); err != nil {
					return err
				}
				if why == "" {
					t.log.line("reopened " + each.Name + " and asked it to continue " + id)
					continue
				}
			}
			text := fmt.Sprintf("Its orchestrator session %s is gone while run %s is still going. agentkit tried to reopen the seat and could not: %s. Press its number in the menu, then say: continue %s.", each.Name, id, why, id)
			if err := notify.Alert(each.Name, text, fmt.Sprintf("revive:%s:%s:%d", each.Name, id, int64(now)), t.log.out); err != nil {
				return err
			}
		}
		return nil
	})
}

// reopen is watch.revive: the gone seat opened again as its number opens it, on its own
// conversation, owing that line, which is typed once its harness has had its warm-up; why it did
// not come back, else "".
func (t *ticking) reopen(each seat.Revival, line string) (string, error) {
	opened, err := seat.Reopen(each.Name, seat.How{}, io.Discard, io.Discard)
	if err != nil {
		return err.Error(), nil
	}
	if !opened {
		return "its harness did not provide a command to reopen it", nil
	}
	if each.Fresh {
		line += "; this seat was started fresh because its earlier conversation could not be resumed"
	}
	if err := seat.OweLine(each.Name, line); err != nil {
		return "", err
	}
	time.Sleep(seat.Warmup)
	_, err = seat.TellOwed(each.Name, t.log.line)
	return "", err
}

func (t *ticking) owedLines() error {
	names, known := seat.Seats(t.clock())
	if !known {
		return errLeft
	}
	for _, name := range names {
		if carried, err := seat.TellOwed(name, t.log.line); err != nil || !carried {
			if err != nil {
				return err
			}
			return errLeft
		}
	}
	return nil
}
