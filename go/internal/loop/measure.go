package loop

import (
	"cmp"
	"context"
	"errors"
	"math"
	"os"
	"path/filepath"
	"sync"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// sampleEvery is how often a pass's measure reads its cgroup, Python's ACTIVITY_POLL, at which each
// piece's watch samples it.
var sampleEvery = time.Second

// A measure is what a pass of a suite in pieces held, Python's _SuiteMeasure: the most its cgroup
// held, swap included and less the file cache reclaim frees, over what it held as the pass began.
// The cgroup is the run's systemd scope, else this process's where that holds nothing but this
// process and what it started (host.Measured): elsewhere a change in memory is not the suite's.
type measure struct {
	run      any // the run's id as its record holds it
	began    time.Time
	group    string // the cgroup read, "" for none
	baseline float64
	held     sync.Mutex
	peak     float64
	mem      float64 // the memory per piece kept, 0 for none: what an overflowed pass costs where more
}

// measuring begins the measure of a pass whose pieces run until ctx ends, its cgroup read each
// sampleEvery meanwhile.
func (l *loop) measuring(ctx context.Context) *measure {
	m, scope := &measure{began: time.Now()}, ""
	if record, _ := run.Read(l.dir); record != nil {
		m.run, scope = record.Get("run_id"), record.Str("scope")
	}
	group, ok := host.Measured(host.ScopeUnits(scope))
	if ok {
		m.baseline, ok = host.HeldMB(group)
	}
	if !ok {
		return m
	}
	m.group, m.peak = group, m.baseline
	go func() {
		tick := time.NewTicker(sampleEvery)
		defer tick.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-tick.C:
				if held, ok := host.HeldMB(m.group); ok {
					m.held.Lock()
					m.peak = max(m.peak, held)
					m.held.Unlock()
				}
			}
		}
	}()
	return m
}

// kept saves the pass of all, once its pieces ended, as the suite's cost at path, Python's
// _SuiteMeasure.save as run_suite calls it: its wall time and the run's id, a retry of the same run
// keeping the slower attempt's time; the CPUs per place where every piece here said its own, and
// the memory it held over the places that ran here at once, each never under a heavy suite's first
// estimate.  Pieces on the suite helper held nothing here; a pass whose pieces waited for turns did
// not run at once, and one with a piece stopped or busy did not run whole: neither keeps a cost.
func (m *measure) kept(ctx context.Context, path string, all []*piece, on *placement) error {
	var here []*piece
	for _, at := range all {
		if at.ended.stopped != "" || at.ended.code == host.SuiteBusy {
			return nil
		}
		if at.there == nil {
			here = append(here, at)
		}
	}
	elapsed := time.Since(m.began).Seconds()
	if len(here) == 0 || on.holds() && on.hold.Waited() || elapsed <= 0 {
		return nil
	}
	places := len(all)
	if on.holds() {
		places = on.hold.Places()
	}
	places = min(places, len(here))
	spent, read := 0.0, true
	for _, at := range here {
		if at.ended.cpu == nil {
			read = false
			break
		}
		spent += *at.ended.cpu
	}
	m.held.Lock()
	held := (m.peak - m.baseline) / float64(places)
	m.held.Unlock()
	cpus, least := host.Cost(spent/(elapsed*float64(places)), 0)
	if m.group != "" {
		m.mem = max(held, least)
	}
	return costed(ctx, path, "keeping its pass's cost", func(cost *run.Object) {
		// a fast retry must not erase the slow whole attempt that earned a split
		if seconds, ok := cost.Num("wall_seconds"); !ok || !run.Equal(cost.Get("run_id"), m.run) || math.IsInf(seconds, 0) || math.IsNaN(seconds) || elapsed >= seconds {
			cost.Set("wall_seconds", elapsed)
		}
		cost.Set("run_id", m.run)
		if read {
			cost.Set("cpus", cpus)
		}
		switch {
		case m.group == "":
		case held > least:
			cost.Set("mem_mb", held)
		default:
			cost.Set("mem_mb", int(least)) // Python's max keeps the estimate's int
		}
	})
}

// costed changes the suite's cost kept at path as change does, Python's write_suite_cost under its
// state lock: the cost's other fields kept.  A cost Go cannot write back is Python's before anything
// is written, doing what it says; one that cannot be saved keeps what it held, as to Python.  A
// driver stopped, ctx's end, waits for no lock: its error is the stop's.
func costed(ctx context.Context, path, doing string, change func(*run.Object)) error {
	if config.EnsureDirs() != nil {
		return nil
	}
	held, err := lock.Wait(ctx, filepath.Join(config.Home(), "state", "watch.lock"))
	if err != nil {
		return context.Cause(ctx)
	}
	defer held.Close()
	cost, err := run.ReadJSON(path)
	if errors.Is(err, run.ErrLoneSurrogate) {
		return notYet("the suite's cost "+path+" holds what Go cannot write back", doing)
	}
	cost = cmp.Or(cost, run.NewObject())
	change(cost)
	saved, err := os.CreateTemp(filepath.Dir(path), "tmp")
	if err != nil {
		return nil
	}
	_, err = saved.WriteString(run.Line(cost))
	if closed := saved.Close(); err != nil || closed != nil || os.Rename(saved.Name(), path) != nil {
		os.Remove(saved.Name())
	}
	return nil
}
