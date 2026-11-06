package terminal

import (
	"strconv"
	"strings"
	"time"
)

// Tick is the longest any row goes unwritten: a stray write, a child's, heals by then.
const Tick = 10 * time.Second

// differing is those of lines, from the first row, that up does not hold as they are, each addressed
// and its tail cleared, so no cell that is text before and after is ever blank between.
func differing(lines, up []string, screen Screen) string {
	var out strings.Builder
	for at, line := range lines {
		if !held(lines, up, at) {
			out.WriteString("\x1b[" + strconv.Itoa(at+1) + ";1H" + cleared(line, screen))
		}
	}
	return out.String()
}

// held is whether up holds that row of lines, from 0, as it is.
func held(lines, up []string, at int) bool {
	return at < len(lines) && at < len(up) && lines[at] == up[at]
}

// cleared is a line, then its row's tail cleared.  A line filling the last column gets no clear: the
// cursor rests on that column, and a clear there would erase it.
func cleared(line string, screen Screen) string {
	if Cells(line) >= screen.Width() {
		return line
	}
	return line + "\x1b[K"
}
