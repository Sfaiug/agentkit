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
// re-run decided, nil for none, where it ran, and when its next go was asked for.
type piece struct {
	shard  string
	out    *os.File
	ended  ran
	failed []byte
	there  *helper.Away // the helper it ran on, nil for here
	asked  float64
}

// pieces runs cmd, which names AK_SHARD, in pieces, Python's gate.run_suite with no turn held: on
// the suite helper that takes it, cut in twice the VMs that machine fits empty and run on the VMs it
// has room for now, more as room frees, else here, in as many as this host fits at once.  Each has
// its share `AK_SHARD=k/N`, its own silence window and the list's deadline, its output added to
// progress under its own header as it ends.  A piece red on the helper, whose offline VM fails a
// command that needs this host, runs here after the others, which decides (there).  A red piece
// here goes once more alone after the others, which decides it, a pass then said by a `flaky:`
// record unless the kernel killed it for memory (starved.go); one stopped at its limit stops the
// rest.  Each go leaves its row in history under rows where it ran, the goes on the helper once
// they all ended Go's.  The suite ends as its first red piece did, and hands on what handedOn says.
//
// What Python does beyond that is not Go's yet and differs here: a heavy-suite turn, and the
// suite's pace and cost measured for its next run.
func (l *loop) pieces(cwd, cmd string, deadline time.Time, progress *os.File, path string, rows *history.Checked) (ran, string, error) {
	asked := clock() // each piece's first go is asked for now, a later one as the one before it ends
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
	var kept []func() // the rows of the goes there, kept once the suite is known Go's
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
		kills, flaky := host.OOMKills(), at.ended.flaky // the tests its earlier goes saw fail, then pass
		if left := time.Until(deadline); left <= 0 {
			at.ended = ran{code: 124, stopped: "ceiling"}
		} else {
			command := "AK_SHARD=" + at.shard + " " + cmd
			if at.there != nil {
				keep := history.Ran(rows, command, at.asked, at.there.Alias, l.say)
				at.ended, err = alone.there(at.there, at.shard, left, out)
				exit := exitOf(at.ended, err)
				held.Lock()
				kept = append(kept, func() { keep(exit) })
				held.Unlock()
			} else {
				finish := history.Check(rows, command, at.asked, "", l.say)
				at.ended, err = alone.boxed(cwd, cmd, at.shard, left, out, out.Name(), false, only)
				finish(exitOf(at.ended, err))
			}
			at.asked = clock()
		}
		if errors.Is(err, errSibling) {
			at.ended, err = ran{code: -15, stopped: "sibling"}, nil
		} else if err != nil {
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
	err = cmp.Or(context.Cause(l.ctx), errors.Join(errs...))
	if !errors.Is(err, helper.ErrPython) {
		// a suite handed on keeps no row: Python runs it again
		for _, keep := range kept {
			keep()
		}
	}
	if err != nil {
		return ran{}, "", err
	}
	for _, at := range all {
		if at.there != nil && at.ended.code != 0 && ctx.Err() == nil {
			// its go here takes its place in the suite's output: a copy keeps what it printed there
			kept, err := os.CreateTemp(l.dir, stem(path)+"-helper-failed-*.log")
			if err == nil {
				_, err = io.Copy(kept, io.NewSectionReader(at.out, 0, 1<<62))
				kept.Close()
			}
			if err != nil {
				return ran{}, "", err
			}
			l.say(fmt.Sprintf("WARN AK_SHARD=%s failed on the suite helper; what it printed there: %s", at.shard, kept.Name()))
			why := "helper " + at.there.Alias + " " + helper.Failure(at.ended.code)
			at.there = nil
			if err := attempt(at, why, nil); err != nil {
				return ran{}, "", err
			}
		}
		if at.ended.starved && ctx.Err() == nil {
			// out of memory beside its siblings: once more after them
			if err := attempt(at, pieceRetry, nil); err != nil {
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
			// a piece out of memory hands on its red only where no other piece is red
			if ended.code == 0 || ended.starved && !at.ended.starved {
				ended.piece, ended.confirmed, ended.starved = at.shard, at.ended.confirmed, at.ended.starved
			}
			ended.code = cmp.Or(ended.code, at.ended.code)
		}
		if at.ended.starved {
			status = "ran out of memory"
		}
		ended.flaky, ended.reds = append(ended.flaky, at.ended.flaky...), append(ended.reds, at.ended.confirmed...)
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
