package cli

import (
	"sync/atomic"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/seat"
)

// openedFrame is the piped ak screen's frame and what its opening said: the home admitted first,
// as Python resumes after a reboot before its maintenance, then swept but on a dry run or the
// overlay (orch.maintenance).  False where Go hands the screen over.
func openedFrame(none bool) (reading, []string, bool) {
	first, known := readFrame(time.Now(), seat.Home.Announce)
	if !known || first.handoff || none {
		return first, nil, known && !first.handoff
	}
	again, said, carried := swept()
	if again != nil {
		first = *again
	}
	return first, said, carried
}

// sweepBehind starts the drawn ak screen's opening sweep, but where none, behind its first frame,
// which is the records as they stand, as Python's menu starts its maintenance (Live.tidy).  It is
// a channel closed once the home the sweep left is latest, and what the sweep said, once, from
// then.  Until then no read and no act on a seat begins: the read could meet a seat the sweep is
// forgetting half gone, and the act bring back one the sweep then forgets.  What a sweep leaves to
// Python is the tick's next one, as a restart's is: it touches nothing of a seat it stops at.
func sweepBehind(none bool, latest *atomic.Pointer[reading], wake func()) (<-chan struct{}, func() []string) {
	done, said := make(chan struct{}), []string(nil)
	if none {
		close(done)
	} else {
		go func() {
			again, lines, _ := swept()
			if again != nil {
				show(latest, again)
			}
			said = lines
			close(done)
			wake()
		}()
	}
	return done, func() []string {
		select {
		case <-done:
			lines := said
			said = nil
			return lines
		default:
			return nil
		}
	}
}

// swept is the home after the ak screen's opening sweep and what the sweep said: read again where
// it said anything, as it says all it does, else nil, as where Go does not read it; false where Go
// hands the screen over.
func swept() (*reading, []string, bool) {
	var said []string
	carried, err := seat.Sweep(time.Now(), func(line string) { said = append(said, line) })
	if err != nil {
		said = append(said, "WARN could not check the sessions: "+config.PyError(err))
	}
	if len(said) == 0 {
		return nil, said, carried
	}
	found, known := readFrame(time.Now(), seat.Home.Announce)
	if !known {
		return nil, said, false
	}
	return &found, said, carried && !found.handoff
}
