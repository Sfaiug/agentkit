package loop

import (
	"context"
	"fmt"
	"os"
	"time"

	"agentkit/internal/helper"
	"agentkit/internal/host"
)

// gatePoll is how often a suite asks the helpers again while a piece of it waits, Python's
// GATE_POLL.
const gatePoll = 15 * time.Second

// there runs one piece of a suite there (onHelper), the tests it named flaky there kept, and a red
// one's that it named failed, which run here next (helperReds).  One the machine lost or turned
// away ends with its exit, given back (helper.Back) to wait again (piecesLeft); one stopped is
// Python's, which runs it again alone.
func (l *loop) there(away *helper.Away, shard string, limit time.Duration, out *os.File) (ran, error) {
	code, stopped, err := l.onHelper(away, shard, limit, out)
	if err != nil {
		return ran{}, err
	}
	if stopped != "" {
		return ran{}, fmt.Errorf("%w: AK_SHARD=%s on %s was stopped for %s", helper.ErrPython, shard, away.Alias, stopped)
	}
	if helper.Gone(code) {
		return ran{code: code}, away.Back(shard, code, l.say)
	}
	ended := ran{code: code, testReport: testReport{flaky: away.Named(shard, "flaky")}}
	if code != 0 {
		ended.failed = away.Named(shard, "failed")
	}
	return ended, nil
}

// onHelper runs the piece of shard on the helper that took it, Python's worker.limited of
// helper.piece: its own silence and limit, its output into out.  Its exit there, and the stop that
// ended it, "" for none.
func (l *loop) onHelper(away *helper.Away, shard string, limit time.Duration, out *os.File) (int, string, error) {
	ctx, watched := host.Watch{Silence: l.silence, Ceiling: limit, Heard: host.Written(out.Name()), Declared: host.Declared(l.dir)}.Stop(l.ctx)
	code := away.Piece(ctx, shard, out)
	stopped := watched()
	if l.ctx.Err() != nil {
		return 0, "", context.Cause(l.ctx)
	}
	return code, stopped, nil
}

// grow asks the helpers again each poll while a piece waits, Python's ask: a suite one takes runs
// waiting pieces on its VMs too, each started by start, so a suite that began on little room there,
// or on a turn here, grows into what frees.  It asks until the places are over, as a piece a
// machine gave back waits again, and never waits on an answer past that: one that comes later
// finishes the helper it joined.  A look that fails ends the suite with its error, as the look at
// its start does.  What it joined is finished once their pieces end.
func (l *loop) grow(cwd string, cpus, memory float64, cmd, times string, waiting *piecesLeft, start func(*helper.Away)) (joined []*helper.Away, err error) {
	type look struct {
		there *helper.Away
		said  []string // said once the suite goes there, not at each look
		err   error
	}
	tick := time.NewTicker(time.Second)
	defer tick.Stop()
	asked := time.Now()
	var answer chan look
	for {
		select {
		case got := <-answer:
			answer = nil
			if got.err != nil {
				return joined, got.err
			}
			if got.there != nil {
				for _, line := range got.said {
					l.say(line)
				}
				joined = append(joined, got.there)
				for range min(got.there.Count, waiting.waits()) {
					start(got.there)
				}
			}
		case <-tick.C:
		case <-l.ctx.Done():
		}
		if l.ctx.Err() != nil || waiting.over() {
			if late := answer; late != nil {
				go func() {
					if got := <-late; got.there != nil {
						got.there.Finish()
					}
				}()
			}
			return joined, nil
		}
		if answer == nil && waiting.waits() > 0 && time.Since(asked) >= gatePoll {
			asked, answer = time.Now(), make(chan look, 1)
			go func(answer chan look) {
				var got look
				got.there, _, got.err = helper.Start(cwd, cpus, memory, cmd, times, l.changed, nil, func(line string) { got.said = append(got.said, line) })
				answer <- got
			}(answer)
		}
	}
}
