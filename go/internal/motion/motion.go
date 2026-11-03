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
	Glide   = 700 * time.Millisecond // ... and to glide to a new length as its plan moves
	Breath  = 2 * time.Second        // a breathing cell takes out to its dimmer tone and back
	Dimmer  = 0.5                    // ... that tone: half way from its colour to the background
)

// Eased is 0 to 1 as x goes from 0 to 1, slow out of the one and into the other.
func Eased(x float64) float64 {
	return (1 - math.Cos(math.Pi*min(1, max(0, x)))) / 2
}
