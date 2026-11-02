package worker

import (
	"bytes"
	"context"
	"io"
	"os"
	"strings"
	"time"

	"agentkit/internal/host"
	"agentkit/internal/run"
)

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

// Heard is Written, or with heartbeats the count of whole lines of no such `type`: those only say
// a tool still runs, so a hung tool call heartbeating away still goes silent.
func Heard(path string, heartbeats []string) func() any {
	if len(heartbeats) == 0 {
		return Written(path)
	}
	var at int64
	var rest []byte
	said := 0
	beat := func(line []byte) bool {
		value, _ := run.Decode(line)
		event, _ := value.(*run.Object)
		if event == nil {
			return false
		}
		for _, kind := range heartbeats {
			if event.Str("type") == kind {
				return true
			}
		}
		return false
	}
	return func() any {
		file, err := os.Open(path)
		if err != nil {
			return said
		}
		defer file.Close()
		if end, err := file.Seek(0, io.SeekEnd); err != nil {
			return said
		} else if end < at {
			at, rest = 0, nil // rewritten from its start
		}
		file.Seek(at, io.SeekStart)
		more, _ := io.ReadAll(file)
		at += int64(len(more))
		lines := bytes.Split(append(rest, more...), []byte("\n"))
		rest = lines[len(lines)-1]
		for _, line := range lines[:len(lines)-1] {
			if strings.TrimSpace(string(line)) != "" && !beat(line) {
				said++
			}
		}
		return said
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
		tick := time.NewTicker(poll)
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
					if host.Declared(w.Marker, float64(now.UnixNano())/1e9) {
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
