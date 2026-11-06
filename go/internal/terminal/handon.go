package terminal

import (
	"fmt"
	"io"
	"strings"
)

// Up is the frame up as it crosses an exec, in Python's form: the size it was laid out for, then its
// rows.  Nil where what the terminal holds is not known: a resize or a return from a stop asked for
// a draw not made yet.
func (p *Painter) Up() []byte {
	if !p.known {
		return nil
	}
	return []byte(strings.Join(append([]string{p.of.size()}, p.up...), "\n"))
}

// Restore writes the rows a frame crossed an exec with (Up) as the terminal is taken again, and ends
// the hold the program before this one gave it back under; only on a terminal the size they were
// laid out for, where else the first frame ends it.  Each row is addressed, so none can scroll.  The
// painter still knows nothing up, so that frame goes out whole.
func (p *Painter) Restore(frame []byte, screen Screen) {
	rows := strings.Split(string(frame), "\n")
	if rows[0] != screen.size() {
		return
	}
	io.WriteString(p.out, differing(rows[1:], func(int) bool { return false }, screen)+"\x1b[?2026l")
}

func (s Screen) size() string { return fmt.Sprintf("%d %d", s.width, s.height) }
