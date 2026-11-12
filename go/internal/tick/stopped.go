package tick

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/notify"
	"agentkit/internal/run"
)

// A tick watches ticks end, as Python's watch.tick_notice does: once they stop, the owner is
// paged once, and the next tick to end says once, with no mention, that they end again.  The
// episode is state/watch.tick.page.json, `{"since": ...}` and then its `back`, kept before each
// page goes, so a sender killed after delivery still owes the next line; the outbox keeps each
// page to once.

// pageFloor is how long ticks go without ending before the owner is paged: a 36-minute tick has
// ended unaided here.
const pageFloor = 2 * hung

func stopPath() string { return statePath("watch.tick.page.json") }

// unended pages the owner once no tick has ended for pageFloor while the last tick began within
// hung of this one, which tells ticks failing one after another from a host or cron that ran
// none; previous is zero where no tick began before.  Its clock, tick_completed_at, starts at the
// last tick's end, and only a tick that ends whole moves it on.
func (t *ticking) unended(began, previous time.Time) {
	if !t.state.Has("tick_completed_at") {
		last := any(run.Number("0"))
		if tick := t.state.Dict("tick"); tick != nil {
			last = generation(tick.Get("ended_at"))
		}
		if at(last) == 0 {
			last = run.Float(epoch(began))
		}
		t.state.Set("tick_completed_at", last)
	}
	since := generation(t.state.Get("tick_completed_at"))
	silent := epoch(began) - at(since)
	if at(since) != 0 && silent >= pageFloor.Seconds() && !previous.IsZero() && began.Sub(previous) < hung {
		stopped(since, fmt.Sprintf("no tick has ended for %d min", int(silent/60)), t.log)
	}
}

// stopped pages the owner that no tick has ended since that stamp, and why it says so, once an
// episode however many ticks ask; nothing where a tick completed since, as a paused observer may find.
func stopped(since any, why string, l *log) {
	episode(l, func(stop *run.Object) error {
		state, ok := loadState()
		if !ok {
			return errUnwritable
		}
		if at(since) < at(generation(state.Get("tick_completed_at"))) {
			return nil
		}
		if stop == nil || stop.Truthy("back") {
			stop = run.SetAll(run.NewObject(), "since", since)
			if err := replaceFile(stopPath(), run.Line(stop)); err != nil {
				return err
			}
		}
		_, err := notify.Page("tick-stopped:"+run.Text(stop.Get("since")), "🔴 ak ticks stopped ending · "+why, true, l.errOut)
		return err
	})
}

// ended is a tick that ended at that stamp: once the episode's page is out it says, with no
// mention, how long ticks did not end, and once that is out too the episode is over; an episode
// whose page never went out ends unsaid.
func ended(end any, l *log) {
	episode(l, func(stop *run.Object) error {
		if stop == nil {
			return nil
		}
		since := run.Text(stop.Get("since"))
		paged, err := notify.Paged("tick-stopped:" + since)
		if err != nil {
			return err
		}
		if paged {
			if !stop.Has("back") {
				stop.Set("back", end)
				if err := replaceFile(stopPath(), run.Line(stop)); err != nil {
					return err
				}
			}
			line := "ak ticks end again after " + lasted(at(stop.Get("back"))-at(stop.Get("since")))
			due, err := notify.Page("tick-back:"+since, line, false, l.errOut)
			if err != nil || due {
				return err
			}
		}
		if err := os.Remove(stopPath()); err != nil && !errors.Is(err, fs.ErrNotExist) {
			return err
		}
		return nil
	})
}

// episode runs fn on the episode, nil for none, under its own lock, which keeps overlapping
// ticks' notices apart without waiting on watch.json's, held by a stopped tick inside a pass.  A
// notice that fails is the tick's WARN line, and the tick goes on.
func episode(l *log, fn func(stop *run.Object) error) {
	held, err := lock.Wait(context.Background(), statePath("watch.tick.page.lock"))
	if err == nil {
		defer held.Close()
		// a record unread, or no object, is none
		data, _ := os.ReadFile(stopPath())
		value, _ := run.Decode(data)
		stop, _ := value.(*run.Object)
		if stop != nil && len(stop.Keys()) == 0 {
			stop = nil
		}
		err = fn(stop)
	}
	if err != nil {
		l.line("WARN tick notification did not run: " + config.PyError(err))
	}
}
