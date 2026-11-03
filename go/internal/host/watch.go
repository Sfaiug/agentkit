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

// A Watch stops a command that goes quiet or runs too long, Python's worker.limited: its Silence,
// asked of Heard each second, and its Ceiling, none for a zero.  A command among the Marker's
// processes inside the time it gave `timeout` holds the silence off, and it counts from then.
// Before runs ahead of the stop, while the command's processes can still be read.
type Watch struct {
	Silence, Ceiling time.Duration
	Heard            func() any
	Marker           string
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
		last, seen := started, w.Heard()
		tick := time.NewTicker(watchEvery)
		defer tick.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case now := <-tick.C:
				if current := w.Heard(); current != seen {
					last, seen = now, current
				}
				switch {
				case w.Ceiling > 0 && now.Sub(started) >= w.Ceiling:
					reason = "ceiling"
				case w.Silence > 0 && now.Sub(last) >= w.Silence:
					if Declared(w.Marker, float64(now.UnixNano())/1e9) {
						last = now
					} else {
						reason = "silence"
					}
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
