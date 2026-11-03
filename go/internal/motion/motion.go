// Package motion is the screens' one animation clock (agentkit/motion.py): what moves is a pure
// function of how long ago it began, so any moment can be drawn without a terminal, and every
// cell animated alike moves in one phase.
package motion

import (
	"math"
	"time"
)

const (
	Frame   = time.Second / 20       // at most twenty frames a second
	Grow    = 450 * time.Millisecond // a seat's progress line takes to grow to its length as ak opens
	Stagger = 40 * time.Millisecond  // ... and each row after the one above it
)

// Eased is 0 to 1 as x goes from 0 to 1, slow out of the one and into the other.
func Eased(x float64) float64 {
	return (1 - math.Cos(math.Pi*min(1, max(0, x)))) / 2
}

// Grown is how far the nth progress line of a screen up that long has grown to its length.
func Grown(up time.Duration, nth int) float64 {
	return Eased(float64(up-time.Duration(nth)*Stagger) / float64(Grow))
}

// Growing is whether any of a screen's first lines lines still grows once it has been up that long.
func Growing(up time.Duration, lines int) bool {
	return lines > 0 && up < Grow+time.Duration(lines-1)*Stagger
}
