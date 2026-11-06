package terminal

import (
	"slices"
	"strconv"
	"strings"
	"time"
)

// Tick is the longest any row goes unwritten: a stray write, a child's, heals by then.
const Tick = 10 * time.Second

// differing is those of lines, from the first row, the terminal does not hold as they are (held, of
// each from 0), each addressed and its tail cleared, so no cell that is text before and after is
// ever blank between.
func differing(lines []string, held func(at int) bool, screen Screen) string {
	var out strings.Builder
	for at, line := range lines {
		if !held(at) {
			out.WriteString("\x1b[" + strconv.Itoa(at+1) + ";1H" + cleared(line, screen))
		}
	}
	return out.String()
}

// cleared is a line, then its row's tail cleared.  A line filling the last column gets no clear: the
// cursor rests on that column, and a clear there would erase it.
func cleared(line string, screen Screen) string {
	if Cells(line) >= screen.Width() {
		return line
	}
	return line + "\x1b[K"
}

// moved is each row, from 1, a span left or came to between was and now: what is under a span is
// only known where one starts on the same cell after as before.
func moved(was, now []Span) map[int]bool {
	rows := map[int]bool{}
	for _, pair := range [][2][]Span{{was, now}, {now, was}} {
		for _, span := range pair[0] {
			rows[span.Row] = rows[span.Row] || !slices.ContainsFunc(pair[1], span.on)
		}
	}
	return rows
}

// on is whether two spans start on the same cell.
func (s Span) on(other Span) bool { return s.Row == other.Row && s.Column == other.Column }
