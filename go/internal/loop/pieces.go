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
	"agentkit/internal/host"
	"agentkit/internal/run"
)

// errSibling ends the pieces still running once one is stopped at its limit, as Python's cancel
// does: the suite has failed, and what they would say no longer decides anything.
var errSibling = errors.New("a sibling piece was stopped")

// A piece is one share of a suite as it ran: its output, how it ended, the output of a first go its
// re-run decided, nil for none, and where it ran.
type piece struct {
	shard  string
	out    *os.File
	ended  ran
	failed []byte
	there  *helper.Away // the helper it ran on, nil for here
}

// pieces runs cmd, which names AK_SHARD, in pieces, Python's gate.run_suite with no turn held: on
// the suite helper that takes it, cut in twice the VMs that machine fits empty and run on the VMs it
// has room for now, more as room frees, else here, in as many as this host fits at once.  Each has
// its share `AK_SHARD=k/N`, its own silence window and the list's deadline, its output added to
// progress under its own header as it ends.  A red piece here goes once more alone after the
// others, which decides it, a pass then said by a `flaky:` record; one stopped at its limit stops
// the rest, as a piece that does not pass on the helper does, which is Python's (helper.ErrPython).
// The suite ends as its first red piece did, and hands on what handedOn says.
//
// What Python does beyond that is not Go's yet and differs here: a heavy-suite turn, and the
// suite's pace and cost measured for its next run.
func (l *loop) pieces(cwd, cmd string, deadline time.Time, progress *os.File, path string) (ran, string, error) {
	cpus, memory := suiteCost(l.dir, cwd, cmd)
	away, here, err := helper.Start(cwd, cpus, memory, cmd, l.say)
	if err != nil {
		return ran{}, "", err
	}
	count := host.Pieces(cpus, memory)
	places := count
	if away != nil {
		defer away.Finish()
		// cut for the whole machine, not the room it has now, so the suite grows into what frees
		count, places = cmp.Or(2*away.Most, count), away.Count
	} else {
		l.say("suite runs here: " + here)
	}
	ctx, cancel := context.WithCancelCause(l.ctx)
	defer cancel(nil)
	alone := *l
	alone.ctx = ctx // a piece stopped at its limit ends its siblings, never the run
	var held sync.Mutex
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
		if left := time.Until(deadline); left <= 0 {
			at.ended = ran{code: 124, stopped: "ceiling"}
		} else if at.there != nil {
			at.ended, err = alone.there(at.there, at.shard, left, out)
		} else {
			at.ended, err = alone.boxed(cwd, cmd, at.shard, left, out, out.Name(), false, only)
		}
		if errors.Is(err, errSibling) {
			at.ended, err = ran{code: -15, stopped: "sibling"}, nil
		} else if err != nil {
			cancel(errSibling)
			return err
		}
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
		all[index] = &piece{shard: fmt.Sprintf("%d/%d", index+1, count)}
		waiting <- all[index]
	}
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
	if away != nil {
		started.Add(1)
		go func() {
			defer started.Done()
			joined = alone.grow(cwd, cpus, memory, cmd, waiting, place)
		}()
	}
	started.Wait()
	for _, there := range joined {
		there.Finish()
	}
	if err := cmp.Or(context.Cause(l.ctx), errors.Join(errs...)); err != nil {
		return ran{}, "", err
	}
	for _, at := range all {
		if at.ended.code == 0 || at.ended.stopped != "" || ctx.Err() != nil {
			continue
		}
		failed, err := os.ReadFile(at.out.Name())
		if err != nil {
			return ran{}, "", err
		}
		if err := retryTests(at, attempt); err != nil {
			return ran{}, "", err
		}
		at.failed = failed
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
			if ended.code == 0 {
				ended.piece, ended.confirmed = at.shard, at.ended.confirmed
			}
			ended.code = cmp.Or(ended.code, at.ended.code)
		}
		ended.flaky = ended.flaky || at.ended.flaky || at.failed != nil && at.ended.code == 0
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
			record, err := l.flakyRecord(fmt.Sprintf("%s (AK_SHARD=%s)", cmd, at.shard), at.failed, again, path, int(share))
			if err != nil {
				return ran{}, "", err
			}
			flakes = append(flakes, record)
		}
	}
	return ended, strings.Join(append(append(green, red...), flakes...), "\n\n"), nil
}

// suiteCost is one piece's cores and memory as a finished run of the suite measured them, Python's
// gate.suite_cost, a heavy suite's first estimate for what none measured: keyed on the repository's
// main checkout and the command.
func suiteCost(dir, cwd, cmd string) (float64, float64) {
	repo := cwd
	if record, _ := run.Read(dir); record != nil {
		repo = cmp.Or(record.Str("repo"), cwd)
	}
	key := sha256.Sum256([]byte(config.Resolve(repo) + "\n" + cmd))
	kept, _ := run.ReadJSON(filepath.Join(config.Home(), "state", fmt.Sprintf("suite-%x.json", key)))
	if kept == nil {
		kept = run.NewObject()
	}
	cpus, _ := kept.Num("cpus")
	memory, _ := kept.Num("mem_mb")
	return host.Cost(cpus, memory)
}
