package terminal

import (
	"fmt"
	"io"
	"strings"
)

// Up is the frame up as it crosses an exec, in Python's form: what it was drawn for (drawnFor), then
// its rows.  Nil where what the terminal holds is not known: a resize or a return from a stop asked
// for a draw not made yet.
func (p *Painter) Up() []byte {
	if !p.known {
		return nil
	}
	return []byte(strings.Join(append([]string{p.of.drawnFor()}, p.up...), "\n"))
}

// Restore writes the rows a frame crossed an exec with (Up) as the terminal is taken again, and ends
// the hold the program before this one gave it back under; only on a terminal still the one they
// were drawn for, where else the first frame ends it.  Each row is addressed, so none can scroll.
// The painter still knows nothing up, so that frame goes out whole.
func (p *Painter) Restore(frame []byte, screen Screen) {
	rows := strings.Split(string(frame), "\n")
	if rows[0] != screen.drawnFor() {
		return
	}
	io.WriteString(p.out, screen.paint(differing(rows[1:], func(int) bool { return false }, screen))+"\x1b[?2026l")
}

// drawnFor is the terminal's size and its answer, which picked the shades a frame's rows are in, as
// Python's terminal._drawn_for: a frame the release before this handed on, under its size alone,
// never goes up.
func (s Screen) drawnFor() string { return fmt.Sprintf("%d %d %s", s.width, s.height, s.background) }
