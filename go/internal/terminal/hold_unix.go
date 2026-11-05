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

// While runs work, a read the frame up waits on, answering meanwhile what ends or stops the
// program as ReadKey does, and reading no key: what is typed is ReadKey's after it, and so is a
// draw asked for.  Work that panics panics here, where the caller gives the terminal back.
func (k *Keyboard) While(work func()) {
	done, asked := make(chan any, 1), false
	go func() {
		defer func() {
			done <- recover()
			k.woken[1].Write([]byte{'.'})
		}()
		work()
	}()
	for {
		for k.answer() {
			asked = true
		}
		select {
		case broke := <-done:
			if asked {
				k.heard <- syscall.SIGWINCH // ReadKey's to answer, as if it came now
			}
			if broke != nil {
				panic(broke)
			}
			return
		default:
			k.woken[0].Read(make([]byte, 64))
		}
	}
}
