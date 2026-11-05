//go:build linux || darwin

package terminal

import (
	"strings"
	"syscall"
)

// GiveHeld gives the terminal back to the program start execs in place of this one, under a
// synchronized-output hold: a terminal that has it goes on showing this frame until that program
// ends the hold (Painter.Restore, else its first frame).  A start that returns has failed, and the
// hold ends with it, so what is said of that shows.
func (k *Keyboard) GiveHeld(start func() error) error {
	k.give("\x1b[?2026h" + strings.TrimSuffix(giveModes, "\x1b[?2026l"))
	defer syscall.Write(outFD, []byte("\x1b[?2026l"))
	return start()
}
