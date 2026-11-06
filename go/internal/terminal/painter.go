package terminal

import (
	"io"
	"slices"
	"strconv"
	"strings"
)

// Painter hides what reaches the terminal: a frame goes out whole, within one synchronized update,
// and only when it differs from the frame up, so a screen left alone writes nothing.
type Painter struct {
	out   io.Writer
	up    []string
	over  []Span
	of    Screen
	known bool
}

// A Span is text written over a frame from one cell, row and column from 1: what moves between its
// draws (motion.Clock), written alone at its cells while the lines under it hold still.
type Span struct {
	Row, Column int
	Text        string
}

// NewPainter is a painter that holds nothing up yet.
func NewPainter(out io.Writer) *Painter { return &Painter{out: out} }

// Write puts lines up on that screen, then each span over them.  A row filling the last column gets
// no clear of its tail: the cursor rests on that column, and a clear there would erase it.  Where
// only what spans hold changed, only those spans go out.
func (p *Painter) Write(lines []string, screen Screen, over ...Span) {
	still := p.known && screen == p.of && slices.Equal(lines, p.up) && slices.EqualFunc(over, p.over, func(a, b Span) bool {
		return a.Row == b.Row && a.Column == b.Column
	})
	var frame strings.Builder
	if !still {
		frame.WriteString("\x1b[H")
		for _, line := range lines {
			frame.WriteString(line)
			if Cells(line) < screen.Width() {
				frame.WriteString("\x1b[K")
			}
			frame.WriteString("\n")
		}
		frame.WriteString("\x1b[J")
	}
	for i, span := range over {
		if !still || span.Text != p.over[i].Text {
			frame.WriteString("\x1b[" + strconv.Itoa(span.Row) + ";" + strconv.Itoa(span.Column) + "H" + span.Text)
		}
	}
	if frame.Len() == 0 {
		return
	}
	io.WriteString(p.out, "\x1b[?2026h"+frame.String()+"\x1b[?2026l")
	p.up, p.over, p.of, p.known = slices.Clone(lines), slices.Clone(over), screen, true
}

// Forget has the next Write go out whatever is up: a resize or a return from a stop leaves the
// terminal holding something else.
func (p *Painter) Forget() { p.known = false }
