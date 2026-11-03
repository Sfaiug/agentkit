package terminal

import (
	"io"
	"slices"
	"strings"
)

// Painter hides what reaches the terminal: a frame goes out whole, within one synchronized update,
// and only when it differs from the frame up, so a screen left alone writes nothing.
type Painter struct {
	out   io.Writer
	up    []string
	of    Screen
	known bool
}

// NewPainter is a painter that holds nothing up yet.
func NewPainter(out io.Writer) *Painter { return &Painter{out: out} }

// Write puts lines up on that screen.  A row filling the last column gets no clear of its tail: the
// cursor rests on that column, and a clear there would erase it.
func (p *Painter) Write(lines []string, screen Screen) {
	if p.known && screen == p.of && slices.Equal(lines, p.up) {
		return
	}
	var frame strings.Builder
	frame.WriteString("\x1b[?2026h\x1b[H")
	for _, line := range lines {
		frame.WriteString(line)
		if Cells(line) < screen.Width() {
			frame.WriteString("\x1b[K")
		}
		frame.WriteString("\n")
	}
	frame.WriteString("\x1b[J\x1b[?2026l")
	io.WriteString(p.out, frame.String())
	p.up, p.of, p.known = slices.Clone(lines), screen, true
}

// Forget has the next Write go out whatever is up: a resize or a return from a stop leaves the
// terminal holding something else.
func (p *Painter) Forget() { p.known = false }
