package cli

import (
	"sync"
	"sync/atomic"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/seat"
)

// openedFrame is the piped ak screen's frame and what its opening said: the home admitted first,
// as Python resumes after a reboot before its maintenance, then swept but on a dry run or the
// overlay (orch.maintenance).  False where Go hands the screen over.
func openedFrame(none bool) (reading, []string, bool) {
	first, known := readFrame(time.Now())
	if !known || first.handoff || none {
		return first, nil, known && !first.handoff
	}
	again, said, carried := swept()
	if again != nil {
		first = *again
	}
	return first, said, carried
}

// sweepBehind starts the drawn ak screen's opening sweep behind its first frame, which is the
// records as they stand, as Python's menu starts its maintenance (Live.tidy), and is what the sweep
// said, once, from when the home it left is latest.  A read holding reads waits for it.  What it
// leaves to Python is the tick's next sweep, as a restart's is: it touches nothing of a seat it
// stops at.
func sweepBehind(latest *atomic.Pointer[reading], reads *sync.RWMutex, wake func()) func() []string {
	heard := make(chan []string, 1)
	go func() {
		reads.Lock()
		again, said, _ := swept()
		if again != nil {
			latest.Store(again)
		}
		reads.Unlock()
		heard <- said
		wake()
	}()
	return func() []string {
		select {
		case said := <-heard:
			return said
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
	found, known := readFrame(time.Now())
	if !known {
		return nil, said, false
	}
	return &found, said, carried && !found.handoff
}
