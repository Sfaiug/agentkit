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
// one's that it named failed, which run here next (helperReds).  One lost there ends with its exit
// where the suite has a place here, which it goes back to the line for (piecesLeft).  One lost where
// it has none, one turned away or out of memory there, or one stopped, is Python's, which sends it
// on to the next machine or runs it again alone.
func (l *loop) there(away *helper.Away, shard string, limit time.Duration, out *os.File, here bool) (ran, error) {
	code, stopped, err := l.onHelper(away, shard, limit, out)
	if err != nil {
		return ran{}, err
	}
	if stopped != "" {
		return ran{}, fmt.Errorf("%w: AK_SHARD=%s on %s was stopped for %s", helper.ErrPython, shard, away.Alias, stopped)
	}
	if here && helper.Lost(code) {
		return ran{code: code}, nil
	}
	if helper.Gone(code) {
		return ran{}, fmt.Errorf("%w: AK_SHARD=%s on %s ended %d", helper.ErrPython, shard, away.Alias, code)
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
// or on a turn here, grows into what frees.  It asks until no piece waits or runs, as a lost one
// waits again, and never waits on an answer past that: one that comes later finishes the helper it
// joined.  What it joined is finished once their pieces end.
func (l *loop) grow(cwd string, cpus, memory float64, cmd, times string, waiting *piecesLeft, start func(*helper.Away)) (joined []*helper.Away) {
	tick := time.NewTicker(time.Second)
	defer tick.Stop()
	asked := time.Now()
	var answer chan *helper.Away
	var said *[]string
	for {
		select {
		case there := <-answer:
			answer = nil
			if there != nil {
				for _, line := range *said {
					l.say(line)
				}
				joined = append(joined, there)
				for range min(there.Count, waiting.waits()) {
					start(there)
				}
			}
		case <-tick.C:
		case <-l.ctx.Done():
		}
		if l.ctx.Err() != nil || waiting.over() {
			if late := answer; late != nil {
				go func() {
					if there := <-late; there != nil {
						there.Finish()
					}
				}()
			}
			return joined
		}
		if answer == nil && waiting.waits() > 0 && time.Since(asked) >= gatePoll {
			asked, answer, said = time.Now(), make(chan *helper.Away, 1), &[]string{}
			go func(answer chan *helper.Away, said *[]string) {
				there, _, _ := helper.Start(cwd, cpus, memory, cmd, times, l.changed, nil, func(line string) { *said = append(*said, line) })
				answer <- there
			}(answer, said)
		}
	}
}
