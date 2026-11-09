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
// up go out, with the rows a span left or came to, and what is below is cleared after any; every
// row, the screen below cleared, where what is up is unknown or on another screen, or once a Tick
// has passed.  Each row is addressed, so a frame filling the screen never scrolls.  A frame taller
// than it goes out whole, each row ended by a newline, so the screen scrolls and keeps its last rows,
// which addressing would stack on the last; what is up after it is unknown.  A span goes out where
// it is not up as it is, or the row under it went out.
func (p *Painter) Write(lines []string, screen Screen, over ...Span) {
	tall := len(lines) > screen.Height()
	whole := !p.known || screen != p.of || tall || time.Since(p.whole) >= Tick
	left := moved(p.over, over)
	held := func(at int) bool {
		return !whole && at < len(lines) && at < len(p.up) && lines[at] == p.up[at] && !left[at+1]
	}
	var frame strings.Builder
	if tall {
		frame.WriteString("\x1b[H")
		for _, line := range lines {
			frame.WriteString(cleared(line, screen) + "\n")
		}
		frame.WriteString("\x1b[J")
	} else if rows := differing(lines, held, screen); whole || rows != "" || len(lines) < len(p.up) {
		frame.WriteString(rows)
		// Addressing a row past the last lands on the last, where a clear would erase it.
		if len(lines) < screen.Height() {
			frame.WriteString("\x1b[" + strconv.Itoa(len(lines)+1) + ";1H\x1b[J")
		}
	}
	for _, span := range over {
		if !held(span.Row-1) || !slices.Contains(p.over, span) {
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
	p.up, p.over, p.of, p.known = slices.Clone(lines), slices.Clone(over), screen, !tall
}

// Forget has the next Write go out whatever is up: a resize or a return from a stop leaves the
// terminal holding something else.
func (p *Painter) Forget() { p.known = false }
