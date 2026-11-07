package loop

import (
	"cmp"
	"context"
	"crypto/sha256"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/helper"
	"agentkit/internal/history"
	"agentkit/internal/host"
	"agentkit/internal/run"
)

// errSibling ends the pieces still running once one is stopped at its limit, as Python's cancel
// does: the suite has failed, and what they would say no longer decides anything.
var errSibling = errors.New("a sibling piece was stopped")

// A piece is one share of a suite as it ran: its output, how it ended, the output of a first go its
// re-run decided, nil for none, and how that go failed as its flaky record says, "" for "failed",
// where it ran, when its next go was asked for, and each go's exit (blame.go's went).
type piece struct {
	shard  string
	out    *os.File
	ended  ran
	failed []byte
	how    string
	there  *helper.Away // the helper it ran on, nil for here
	asked  float64
	exits  []*int
}

// pieces runs cmd, which names AK_SHARD, in pieces, Python's gate.run_suite, where its placement on
// says: on the suite helper that took it, cut in twice the VMs that machine fits empty and run on
// the VMs it has room for now, more as room frees; else here, on the heavy-suite turns held, cut in
// twice the places they were admitted at and run on a place each, more as turns free; else, where no
// turn is taken, in as many as this host fits at once.  Each has its share `AK_SHARD=k/N`, its own
// silence window and the list's deadline, its output added to progress under its own header as it
// ends, and is told when it holds a turn.  A piece red on the helper, whose offline VM fails a
// command that needs this host, runs here after the others, the tests it named there first, which
// decides (helperReds).  A red piece here goes once more alone after the others, which decides it,
// a pass then said by a `flaky:` record unless the kernel killed it for memory (starved.go); one
// stopped at its limit stops the rest.  A whole go after the others runs on a turn here, taken
// first where the suite holds none, and a go told it holds one that answers busy never ran: its
// first beside the others or any go after, it goes again alone once its turn was given back for a
// poll (again).  Each go leaves its row in history under rows where it ran, those on the helper
// dropped where it hands the suite on.  Once the pieces ended, before any go after them, the pass
// keeps what it held here as the suite's cost (measure).  The suite ends as the red piece redRank
// ranks first did, and hands on what handedOn says, its cost raised where it ran out of memory,
// however it ended, but where it is handed on (overflowed).
//
// What Python does beyond that is not Go's yet and differs here: the suite's pace.
func (l *loop) pieces(cwd, cmd string, deadline *time.Time, progress *os.File, path string, rows *history.Checked, on *placement) (_ ran, _ string, err error) {
	asked := clock() // each piece's first go is asked for now, a later one as the one before it ends
	cpus, memory := suiteCost(l.dir, cwd, cmd)
	ooms := host.MemoryEvent("oom")
	away, here := on.away, on.here
	count := host.Pieces(cpus, memory)
	places := count
	switch {
	case away != nil:
		// cut for the whole machine, not the room it has now, so the suite grows into what frees
		count, places = cmp.Or(2*away.Most, count), away.Count
	case on.holds():
		count, places = 2*on.hold.Places(), 0 // each turn starts its place (Grow)
	}
	ctx, cancel := context.WithCancelCause(l.ctx)
	defer cancel(nil)
	measured := l.measuring(ctx)
	alone := *l
	alone.ctx = ctx // a piece stopped at its limit ends its siblings, never the run
	var held sync.Mutex
	var onHelper []*history.Checking // the rows of its goes there, dropped where the suite is handed on
	all := make([]*piece, count)
	defer func() {
		for _, each := range all {
			if each != nil && each.out != nil {
				each.out.Close()
				os.Remove(each.out.Name())
			}
		}
	}()
	attempt := func(at *piece, why string, only []string) error {
		out, err := os.CreateTemp(filepath.Dir(path), stem(path)+"-piece-*.log")
		if err != nil {
			return err
		}
		if at.out != nil {
			at.out.Close()
			os.Remove(at.out.Name())
		}
		at.out = out
		where := "runs here: " + why
		if at.there != nil {
			where = "on " + at.there.Alias
		}
		l.say(fmt.Sprintf("AK_SHARD=%s %s", at.shard, where))
		kills, flaky := host.MemoryEvent("oom_kill"), at.ended.flaky // the tests its earlier goes saw fail, then pass
		if left := time.Until(*deadline); left <= 0 {
			at.ended = ran{code: 124, stopped: "ceiling"}
		} else {
			place := ""
			if at.there != nil {
				place = at.there.Alias
			}
			row := history.Check(rows, "AK_SHARD="+at.shard+" "+cmd, at.asked, place, l.say)
			if at.there != nil {
				held.Lock()
				onHelper = append(onHelper, row)
				held.Unlock()
				at.ended, err = alone.there(at.there, at.shard, left, out)
			} else {
				at.ended, err = alone.boxed(cwd, cmd, at.shard, left, out, out.Name(), false, on.holds(), only)
			}
			row.End(exitOf(at.ended, err))
			at.asked, at.exits = clock(), went(at.exits, at.ended, err)
		}
		if errors.Is(err, errSibling) {
			at.ended, err = ran{code: -15, stopped: "sibling"}, nil
		} else if err != nil {
			at.ended.flaky = flaky
			cancel(errSibling)
			return err
		}
		at.ended.starved, at.ended.flaky = at.there == nil && starved(at.ended, kills), append(flaky, at.ended.flaky...)
		if at.ended.stopped != "" && at.ended.stopped != "sibling" {
			cancel(errSibling)
		}
		held.Lock()
		defer held.Unlock()
		fmt.Fprintf(progress, "--- AK_SHARD=%s ---\n", at.shard)
		_, err = io.Copy(progress, io.NewSectionReader(out, 0, 1<<62))
		return err
	}
	// each place, a VM there or a place here, takes the next waiting piece as it frees
	waiting := make(chan *piece, count)
	for index := range all {
		all[index] = &piece{shard: fmt.Sprintf("%d/%d", index+1, count), asked: asked}
		waiting <- all[index]
	}
	defer func() {
		// a suite that does not end as one command keeps what its ended goes named, as Python's
		// run_suite does; one handed on is Python's to run again and keep
		if err != nil && !errors.Is(err, helper.ErrPython) {
			var reds, flaky []string
			for _, at := range all {
				reds, flaky = append(reds, at.ended.confirmed...), append(flaky, at.ended.flaky...)
			}
			history.TestReds(rows, reds, flaky, l.say)
		}
	}()
	defer func() {
		// before the reds above are kept, as a cost Go cannot write back ends the suite in error
		if !errors.Is(err, helper.ErrPython) {
			err = cmp.Or(err, overflowed(l.ctx, suitePath(l.dir, cwd, cmd), ooms, memory, measured.mem))
		}
	}()
	close(waiting)
	var started sync.WaitGroup
	var errs []error
	place := func(there *helper.Away) {
		started.Add(1)
		go func() {
			defer started.Done()
			for at := range waiting {
				at.there = there
				if err := attempt(at, here, nil); err != nil {
					held.Lock()
					errs = append(errs, err)
					held.Unlock()
				}
			}
		}()
	}
	for range places {
		place(away)
	}
	var joined []*helper.Away
	// a helper that takes the suite while a piece waits runs waiting pieces too, whether the suite
	// began there or on a turn here, as Python's ask does
	if away != nil || on.holds() {
		started.Add(1)
		go func() {
			defer started.Done()
			joined = alone.grow(cwd, cpus, memory, cmd, waiting, place)
		}()
	}
	if on.holds() {
		started.Add(1)
		go func() {
			defer started.Done()
			on.hold.Grow(ctx, func() bool { return len(waiting) > 0 }, func() { place(nil) })
		}()
	}
	started.Wait()
	for _, there := range joined {
		there.Finish()
	}
	on.hold.Alone()
	err = cmp.Or(context.Cause(l.ctx), errors.Join(errs...))
	if errors.Is(err, helper.ErrPython) {
		for _, row := range onHelper {
			row.Drop()
		}
	}
	if err != nil {
		return ran{}, "", err
	}
	if err := measured.kept(l.ctx, suitePath(l.dir, cwd, cmd), all, on); err != nil {
		return ran{}, "", err
	}
	// a go that answered busy never ran: alone, it goes again each time once its turn was given back
	// for a poll (again); one on the suite helper held none here
	settle := func(at *piece, why string, only []string) error {
		for at.there == nil && ctx.Err() == nil {
			if busy, err := l.again(on, cmd, at.ended, deadline); err != nil || !busy {
				return err
			}
			if err := attempt(at, why, only); err != nil {
				return err
			}
		}
		return nil
	}
	// a go once the others ended, Python's rerun: a whole one first takes a turn here where the suite
	// holds none, as only named tests go without one
	rerun := func(at *piece, why string, only []string) error {
		if only == nil {
			if err := l.turnHere(on, deadline); err != nil {
				return err
			}
		}
		if err := attempt(at, why, only); err != nil {
			return err
		}
		return settle(at, why, only)
	}
	if err := l.helperReds(ctx, all, path, rerun); err != nil {
		return ran{}, "", err
	}
	for _, at := range all {
		if at.failed != nil && at.there == nil {
			continue // its tests named on the suite helper decided it (helperReds)
		}
		if err := settle(at, pieceRetry, nil); err != nil {
			return ran{}, "", err
		}
		if at.there != nil && at.ended.code != 0 && ctx.Err() == nil {
			why := "helper " + at.there.Alias + " " + helper.Failure(at.ended.code)
			at.there = nil
			if err := rerun(at, why, nil); err != nil {
				return ran{}, "", err
			}
		}
		if at.ended.starved && ctx.Err() == nil {
			// out of memory beside its siblings: once more after them
			if err := rerun(at, pieceRetry, nil); err != nil {
				return ran{}, "", err
			}
		}
		if at.ended.code == 0 || at.ended.stopped != "" || at.ended.starved || ctx.Err() != nil {
			continue
		}
		failed, err := os.ReadFile(at.out.Name())
		if err != nil {
			return ran{}, "", err
		}
		decided, err := retryTests(at, rerun)
		if err == nil && !decided {
			err = rerun(at, pieceRetry, nil)
		}
		if err != nil {
			return ran{}, "", err
		}
		at.failed, at.how = failed, ""
	}
	return l.handedOn(cmd, all, path)
}

// handedOn is how the pieces ended as one command, and what they hand on: the green pieces, then
// the red ones last, where a failure's diagnostics read, then the flaky records.  They share one
// piecesCap, each part at most outCap: the red pieces take their shares first, so one red piece
// keeps its whole outCap however many ran, and the green pieces and flaky records share the rest.
func (l *loop) handedOn(cmd string, all []*piece, path string) (ran, string, error) {
	reds, others := 0, 0
	for _, at := range all {
		switch {
		case at.ended.code != 0:
			reds++
		case at.failed != nil:
			others += 2 // its output and its flaky record
		default:
			others++
		}
	}
	redShare := int64(min(outCap, piecesCap/max(reds, 1)))
	share := min(outCap, (piecesCap-int64(reds)*redShare)/int64(max(others, 1)))
	var green, red, flakes []string
	var ended ran
	for _, at := range all {
		most, into, status := share, &green, fmt.Sprintf("exit %d", at.ended.code)
		if at.ended.code != 0 {
			most, into = redShare, &red
			if ended.code == 0 || redRank(at.ended) < redRank(ended) {
				ended.piece, ended.confirmed, ended.starved = at.shard, at.ended.confirmed, at.ended.starved
			}
			ended.code = cmp.Or(ended.code, at.ended.code)
		}
		if at.ended.starved {
			status = "ran out of memory"
		}
		ended.flaky, ended.reds = append(ended.flaky, at.ended.flaky...), append(ended.reds, at.ended.confirmed...)
		if len(at.exits) > 0 {
			ended.exits = append(ended.exits, at.exits)
		}
		if at.ended.stopped != "" {
			status = "killed at the limit"
			if at.ended.stopped != "sibling" && ended.stopped == "" {
				ended.stopped, ended.left = at.ended.stopped, at.ended.left
			}
		}
		text, err := cutFrom(at.out, 0, l.dir, stem(path)+"-AK_SHARD-"+strings.ReplaceAll(at.shard, "/", "-of-"), most)
		if err != nil {
			return ran{}, "", err
		}
		*into = append(*into, strings.TrimRightFunc(fmt.Sprintf("--- AK_SHARD=%s ---\n[%s]\n%s", at.shard, status, text), config.Space))
		if at.failed != nil && at.ended.code == 0 {
			again, err := os.ReadFile(at.out.Name())
			if err != nil {
				return ran{}, "", err
			}
			record, err := l.flakyRecord(fmt.Sprintf("%s (AK_SHARD=%s)", cmd, at.shard), cmp.Or(at.how, "failed"), at.failed, again, path, int(share))
			if err != nil {
				return ran{}, "", err
			}
			flakes = append(flakes, record)
		}
	}
	return ended, strings.Join(append(append(green, red...), flakes...), "\n\n"), nil
}

// suiteCost is one piece's cores and memory as a finished run of the suite measured them, Python's
// gate.suite_cost, a heavy suite's first estimate for what none measured.
func suiteCost(dir, cwd, cmd string) (float64, float64) {
	kept, _ := run.ReadJSON(suitePath(dir, cwd, cmd))
	if kept == nil {
		kept = run.NewObject()
	}
	cpus, _ := kept.Num("cpus")
	memory, _ := kept.Num("mem_mb")
	return host.Cost(cpus, memory)
}

// suitePath is where the suite's cost is kept, Python's gate.suite_cost: keyed on the repository's
// main checkout and the command.
func suitePath(dir, cwd, cmd string) string {
	repo := cwd
	if record, _ := run.Read(dir); record != nil {
		repo = cmp.Or(record.Str("repo"), cwd)
	}
	key := sha256.Sum256([]byte(config.Resolve(repo) + "\n" + cmd))
	return filepath.Join(config.Home(), "state", fmt.Sprintf("suite-%x.json", key))
}
