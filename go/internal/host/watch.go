package host

import (
	"context"
	"os"
	"time"
)

// watchEvery is how often a Watch asks.
const watchEvery = time.Second

// Written is what says the file at path grew or changed, for StopOnSilence: even output without
// a newline counts.
func Written(path string) func() any {
	return func() any {
		info, err := os.Stat(path)
		if err != nil {
			return nil
		}
		return [2]int64{info.Size(), info.ModTime().UnixNano()}
	}
}

// boxStart is how long a box may take to come up before silence counts regardless, Python's
// BOX_START: a stuck box cannot hang its command.
const boxStart = 300 * time.Second

// A Watch stops a command that goes quiet or runs too long, Python's worker.limited: its Silence,
// asked of Heard each second, and its Ceiling, none for a zero.  Silence is the command's: where
// Began is given, it counts from when Began says the command's box is up, or boxStart after the
// start.  A command Declared says is inside the time it gave `timeout` holds the silence off,
// and once that bound ends silence counts from the first look that found it ended, never from an
// earlier look, however long the bound outlasted it.  Before runs ahead of the stop, while the
// command's processes can still be read.
type Watch struct {
	Silence, Ceiling time.Duration
	Heard            func() any
	Began            func() bool
	Declared         func(now float64) bool
	Before           func()
}

// Stop is ctx, ended too once the watch says so, and the func that ends the watch, saying what
// ended ctx: "silence", "ceiling", or "" where it ended no command.
func (w Watch) Stop(ctx context.Context) (context.Context, func() string) {
	if w.Silence <= 0 && w.Ceiling <= 0 {
		return ctx, func() string { return "" }
	}
	ctx, cancel := context.WithCancel(ctx)
	ended, reason := make(chan struct{}), ""
	go func() {
		defer close(ended)
		started := time.Now()
		last, held, seen := started, started, w.Heard()
		starting, bound := w.Began != nil, false
		tick := time.NewTicker(watchEvery)
		defer tick.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case now := <-tick.C:
				if current := w.Heard(); current != seen {
					last, seen, bound = now, current, false
				}
				if starting {
					last = now
					starting = !w.Began() && now.Sub(started) < boxStart
				}
				if w.Silence > 0 && now.Sub(last) >= w.Silence && w.Declared != nil {
					// a bound ends between the look that found it and the next: silence counts from
					// that next look's end, never from before the bound's
					was := bound
					if bound = w.Declared(float64(now.UnixNano()) / 1e9); was || bound {
						held = time.Now()
					}
				}
				switch {
				case w.Ceiling > 0 && now.Sub(started) >= w.Ceiling:
					reason = "ceiling"
				case w.Silence > 0 && now.Sub(last) >= w.Silence && now.Sub(held) >= w.Silence:
					reason = "silence"
				}
				if reason != "" {
					if w.Before != nil {
						w.Before()
					}
					cancel()
					return
				}
			}
		}
	}()
	return ctx, func() string {
		cancel()
		<-ended
		return reason
	}
}
