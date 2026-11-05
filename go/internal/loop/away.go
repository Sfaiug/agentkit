package loop

import (
	"context"
	"fmt"
	"os"
	"time"

	"agentkit/internal/helper"
	"agentkit/internal/host"
)

// gatePoll is how often a suite on a helper asks the helpers again while a piece of it waits,
// Python's GATE_POLL.
const gatePoll = 15 * time.Second

// there runs one piece on the helper that took its suite, Python's worker.limited of helper.piece:
// its own silence and the list's deadline, its output into out.  Only a green piece is Go's: one
// red, lost or turned away there, or stopped, is Python's, which runs its tests again here or sends
// it on to the next machine.
func (l *loop) there(away *helper.Away, shard string, limit time.Duration, out *os.File) (ran, error) {
	ctx, watched := host.Watch{Silence: l.silence, Ceiling: limit, Heard: host.Written(out.Name()), Marker: l.dir}.Stop(l.ctx)
	code := away.Piece(ctx, shard, out)
	stopped := watched()
	if l.ctx.Err() != nil {
		return ran{}, context.Cause(l.ctx)
	}
	if stopped != "" {
		return ran{}, fmt.Errorf("%w: AK_SHARD=%s on %s was stopped for %s", helper.ErrPython, shard, away.Alias, stopped)
	}
	if code != 0 {
		return ran{}, fmt.Errorf("%w: AK_SHARD=%s on %s ended %d", helper.ErrPython, shard, away.Alias, code)
	}
	return ran{testReport: testReport{flaky: away.Flaky(shard)}}, nil
}

// grow asks the helpers again each poll while a piece waits, Python's ask: a suite one takes runs
// waiting pieces on its VMs too, each started by start, so a suite that began on little room grows
// into what frees.  It never waits on an answer past the last waiting piece: one that comes later
// finishes the helper it joined.  What it joined is finished once their pieces end.
func (l *loop) grow(cwd string, cpus, memory float64, cmd string, waiting chan *piece, start func(*helper.Away)) (joined []*helper.Away) {
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
				for range min(there.Count, len(waiting)) {
					start(there)
				}
			}
		case <-tick.C:
		case <-l.ctx.Done():
		}
		if l.ctx.Err() != nil || len(waiting) == 0 {
			if late := answer; late != nil {
				go func() {
					if there := <-late; there != nil {
						there.Finish()
					}
				}()
			}
			return joined
		}
		if answer == nil && time.Since(asked) >= gatePoll {
			asked, answer, said = time.Now(), make(chan *helper.Away, 1), &[]string{}
			go func(answer chan *helper.Away, said *[]string) {
				there, _, _ := helper.Start(cwd, cpus, memory, cmd, func(line string) { *said = append(*said, line) })
				answer <- there
			}(answer, said)
		}
	}
}
