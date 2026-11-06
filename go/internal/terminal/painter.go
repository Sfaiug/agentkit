package terminal

import (
	"io"
	"slices"
	"strconv"
	"strings"
	"time"
)

// Painter hides what reaches the terminal: of a frame only the rows that differ from those up go
// out, within one synchronized update, so a screen left alone writes nothing until a Tick has passed
// since every row last went out.
type Painter struct {
	out   io.Writer
	up    []string
	over  []Span
	of    Screen
	known bool
	whole time.Time // when every row last went out
}

// A Span is text written over a frame from one cell, row and column from 1: what moves between its
// draws (motion.Clock), written alone at its cells while the lines under it hold still.
type Span struct {
	Row, Column int
	Text        string
}

// NewPainter is a painter that holds nothing up yet.
func NewPainter(out io.Writer) *Painter { return &Painter{out: out} }

// Write puts lines up on that screen, then each span over them.  Only the rows that differ from those
// up go out, what is below cleared after any; every row, the screen below cleared, where what is up
// is unknown, on another screen or under spans that moved, where lines could scroll, or once a Tick
// has passed.  A span goes out where its text or the row under it changed.
func (p *Painter) Write(lines []string, screen Screen, over ...Span) {
	whole := !p.known || screen != p.of || len(lines) >= screen.Height() || time.Since(p.whole) >= Tick ||
		!slices.EqualFunc(over, p.over, func(a, b Span) bool { return a.Row == b.Row && a.Column == b.Column })
	var frame strings.Builder
	if whole {
		frame.WriteString("\x1b[H")
		for _, line := range lines {
			frame.WriteString(cleared(line, screen) + "\n")
		}
		frame.WriteString("\x1b[J")
	} else if rows := differing(lines, p.up, screen); rows != "" || len(lines) < len(p.up) {
		frame.WriteString(rows + "\x1b[" + strconv.Itoa(len(lines)+1) + ";1H\x1b[J")
	}
	for i, span := range over {
		if whole || span.Text != p.over[i].Text || !held(lines, p.up, span.Row-1) {
			frame.WriteString("\x1b[" + strconv.Itoa(span.Row) + ";" + strconv.Itoa(span.Column) + "H" + span.Text)
		}
	}
	if frame.Len() == 0 {
		return
	}
	io.WriteString(p.out, "\x1b[?2026h"+frame.String()+"\x1b[?2026l")
	if whole {
		p.whole = time.Now()
	}
	p.up, p.over, p.of, p.known = slices.Clone(lines), slices.Clone(over), screen, true
}

// Forget has the next Write go out whatever is up: a resize or a return from a stop leaves the
// terminal holding something else.
func (p *Painter) Forget() { p.known = false }
