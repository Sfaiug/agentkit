package cli

import (
	"time"

	"agentkit/internal/config"
	"agentkit/internal/seat"
)

// openedFrame is the ak screen's first frame and what its opening said: the home admitted first,
// as Python resumes after a reboot before its maintenance, then swept but on a dry run or the
// overlay (orch.maintenance), and read again where the sweep said anything, as it says all it
// does.  False where Go hands the screen over.
func openedFrame(none bool) (reading, []string, bool) {
	first, known := readFrame(time.Now())
	if !known || first.handoff || none {
		return first, nil, known && !first.handoff
	}
	var said []string
	carried, err := seat.Sweep(time.Now(), func(line string) { said = append(said, line) })
	if err != nil {
		said = append(said, "WARN could not check the sessions: "+config.PyError(err))
	}
	if len(said) > 0 {
		first, known = readFrame(time.Now())
	}
	return first, said, carried && known && !first.handoff
}
