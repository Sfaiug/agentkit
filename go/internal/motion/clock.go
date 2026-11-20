package motion

import (
	"math"
	"os"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/terminal"
)

// A Clock is one screen's motion: the moment of the draw it is in, counted from the screen's first,
// what its draws showed, and until when what this draw holds moves.  The screen asks it how far
// each thing that moves has got and when its next frame is due, and times nothing itself.  A nil
// Clock draws everything still, where it ends.
type Clock struct {
	opened time.Time
	at     time.Duration
	seen   map[string]shown
	still  time.Duration // when all this draw holds is still; forever while something breathes
	grown  bool          // the opening lines reached their lengths, or a key finished them
}

// shown is a value a draw showed, what it showed before and since when, where it changed while
// the screen was up.
type shown struct {
	value, before any
	since         time.Duration
}

const forever = time.Duration(math.MaxInt64)

// Now is the time a screen's motion is drawn at (motion.moment). An answer key names its clock in
// AK_MOTION_CLOCK, a file of seconds read anew each time, so it reaches the program the key runs and
// moves only as the key moves it; unset or unread, the real clock. Frames still come on real time.
func Now() time.Time {
	if clock := os.Getenv("AK_MOTION_CLOCK"); clock != "" {
		if data, err := os.ReadFile(clock); err == nil {
			if seconds, err := strconv.ParseFloat(strings.TrimSpace(string(data)), 64); err == nil {
				return time.UnixMicro(int64(seconds * 1e6))
			}
		}
	}
	return time.Now()
}

// Draw begins a draw at now, the first one the screen opening.
func (c *Clock) Draw(now time.Time) {
	if c.seen == nil {
		c.opened, c.seen = now, map[string]shown{}
	}
	c.at, c.still = now.Sub(c.opened), 0
}

// Next is how long until the next frame, and whether one is due: none once all the draw holds is
// still.
func (c *Clock) Next() (time.Duration, bool) {
	return Frame, c.at < c.still
}

func (c *Clock) until(end time.Duration) {
	c.still = max(c.still, end)
}

// Grown is how far the nth progress line down the screen has grown to its length as it opened,
// 0 to 1, each Stagger after the one above it.
func (c *Clock) Grown(nth int) float64 {
	if c == nil || c.grown {
		return 1
	}
	began := time.Duration(nth) * Stagger
	c.until(began + Grow)
	return Eased(float64(c.at-began) / float64(Grow))
}

// Moved is how far value, drawn for key, has moved to it, 0 to 1 eased over took, and what was
// drawn before, where it changed while the screen was up; nil and 1 for a value as the screen
// first drew it.  A value is comparable.
func (c *Clock) Moved(key string, value any, took time.Duration) (before any, moved float64) {
	if c == nil {
		return nil, 1
	}
	was, drawn := c.seen[key]
	if !drawn {
		was = shown{value: value}
	} else if was.value != value {
		was = shown{value, was.value, c.at}
	}
	c.seen[key] = was
	if was.before == nil {
		return nil, 1
	}
	c.until(was.since + took)
	return was.before, Eased(float64(c.at-was.since) / float64(took))
}

// Breathing is glyph in word's colour as a breathing cell shows it now: out to Dimmer of the way
// to the background and back once every Breath, eased into every turn, every one in one phase;
// still where colour cannot move.
func (c *Clock) Breathing(s terminal.Screen, glyph, word string) string {
	if c == nil || !s.Moves() {
		return s.Styled(glyph, word)
	}
	c.still = forever
	return s.Tinted(glyph, word, Dimmer*(1-math.Cos(2*math.Pi*float64(c.at%Breath)/float64(Breath)))/2)
}
