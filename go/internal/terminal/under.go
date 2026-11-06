package terminal

import (
	"cmp"

	"agentkit/internal/config"
)

// Under is what a column, counted from 1 as the terminal counts, is on of line as drawn
// (terminal.under), so what the pointer lights there is what a click there acts on: of cells, each
// its first and last column, the one whose drawn stretch holds it, from 0; else -1, on the row,
// where ink reaches it both ways before any cell's columns or the line's end.  Blank beside a thing
// -- a cell's padding, the gap before a cell, the line's empty rest -- is on nothing.
func Under(line string, column int, cells ...[2]int) (cell int, on bool) {
	inked := ink(line)
	for at, each := range cells {
		if first, last := stretch(inked, each[0], each[1]); first > 0 && first <= column && column <= last {
			return at, true
		}
	}
	reaches := func(step int) bool {
		for at := column; at > 0 && at < len(inked); at += step {
			if inked[at] {
				return true
			}
			for _, each := range cells {
				if each[0] <= at && at <= each[1] {
					return false
				}
			}
		}
		return false
	}
	return -1, reaches(-1) && reaches(1)
}

// Drawn is the stretch of line's columns first to last that is drawn: its first inked column to its
// last, 0, 0 where all are blank.
func Drawn(line string, first, last int) (int, int) {
	return stretch(ink(line), first, last)
}

// ink is whether each column of line holds a drawn character, from 1; 0 is none.
func ink(line string) []bool {
	inked := []bool{false}
	for _, r := range ansi.ReplaceAllString(line, "") {
		for range cell(r) {
			inked = append(inked, !config.Space(r))
		}
	}
	return inked
}

func stretch(inked []bool, first, last int) (from, to int) {
	for at := max(first, 1); at <= last && at < len(inked); at++ {
		if inked[at] {
			from, to = cmp.Or(from, at), at
		}
	}
	return from, to
}
