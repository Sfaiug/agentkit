package terminal

import (
	"slices"
	"strconv"
	"strings"
	"time"
)

// Tick is the longest any row goes unwritten: a stray write, a child's, heals by then.
const Tick = 10 * time.Second

// at moves the cursor to row, column of the screen (each from 1), inset by its padding and
// painting the padding before column 1 -- the rows above it too on row 1, as Python's
// terminal._Screen does.
func (s Screen) at(row, column int) string {
	to := "\x1b[" + strconv.Itoa(row+s.pad) + ";" + strconv.Itoa(column+s.pad) + "H"
	if s.pad == 0 || column > 1 {
		return to
	}
	if row == 1 {
		return to + "\x1b[1J"
	}
	return to + "\x1b[1K"
}

// differing is those of lines, from the first row, the terminal does not hold as they are (held, of
// each from 0), each addressed and its tail cleared, so no cell that is text before and after is
// ever blank between; but the rows a line wraps onto (onto).
func differing(lines []string, held func(at int) bool, screen Screen) string {
	var out strings.Builder
	wrapped := onto(lines, screen)
	for at, line := range lines {
		if !held(at) && !wrapped[at] {
			out.WriteString(screen.at(at+1, 1) + cleared(line, screen))
		}
	}
	return out.String()
}

// cleared is a line, then its row's tail cleared.  A line ending on the last column gets no clear:
// the cursor rests on that column, and a clear there would erase it.
func cleared(line string, screen Screen) string {
	if cells := Cells(line); cells > 0 && (screen.pad+cells)%max(1, screen.Width()+2*screen.pad) == 0 {
		return line
	}
	return line + "\x1b[K"
}

// Unbroken is text, a line to paste, as the rows of a screen (Python's terminal.unbroken): on one
// line however wide, the blank rows under it left for the terminal to wrap it onto, so its
// selection copies one line where one wrapped at words would paste as several.
func (s Screen) Unbroken(text string) []string {
	return append([]string{text}, make([]string, s.wraps(text))...)
}

// wraps is how many rows under it the terminal wraps a line wider than it onto.
func (s Screen) wraps(line string) int {
	cells := Cells(line)
	if cells == 0 {
		return 0
	}
	return max(0, s.pad+cells-1) / max(1, s.Width()+2*s.pad)
}

// onto is whether each of lines is a row a line before it wraps onto, blank as Unbroken leaves
// it (Python's terminal._starts): no row of its own, so never written.
func onto(lines []string, screen Screen) []bool {
	wrapped := make([]bool, len(lines))
	for at := 0; at < len(lines); at++ {
		under := lines[at+1 : min(len(lines), at+1+screen.wraps(lines[at]))]
		if !slices.ContainsFunc(under, func(line string) bool { return line != "" }) {
			for i := range under {
				wrapped[at+1+i] = true
			}
			at += len(under)
		}
	}
	return wrapped
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
