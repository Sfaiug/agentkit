package terminal

import (
	"fmt"
	"math"
	"strconv"
)

// Whether ak's one look reads on a terminal's own background, and its colours there, as Python's
// agentkit/reads.py: the one place that knows what reading means -- reads, shows and how far the
// highlight moves, k -- so a screen asks only for a role (Screen.colour).  The owner, 20 Nov 2026:
// ak "just sits on top of" the terminal's own background; of the highlight there, 22 Nov: "Follow
// the terminal".  Where the look reads a screen sets no background of its own (paint), and
// elsewhere it is painted in its theme, as before.

// reads is the contrast text needs, where its theme gives it more: WCAG's for large text.
const reads = 3

var textRoles = []string{"text", "muted", "dim", "accent", "success", "warning", "error", "info", "special"}

// shows is what a highlight needs with what it is on, where its theme gives it more: what the
// white theme's has with white, the least the owner drew.
var shows = contrast(roles["selection"][white], roles["background"][white])

// luminance is WCAG's relative luminance of rgb, rrggbb.
func luminance(rgb string) float64 {
	sum := 0.0
	for i, part := range channels(rgb) {
		value, _ := strconv.Atoi(part)
		c := float64(value) / 255
		if c <= 0.04045 {
			c /= 12.92
		} else {
			c = math.Pow((c+0.055)/1.055, 2.4)
		}
		sum += [3]float64{0.2126, 0.7152, 0.0722}[i] * c
	}
	return sum
}

// contrast is WCAG's contrast of two colours, rrggbb: 1 to 21.
func contrast(one, other string) float64 {
	a, b := luminance(one), luminance(other)
	return (max(a, b) + 0.05) / (min(a, b) + 0.05)
}

// own is what a screen takes from its terminal's own background where the look reads on it, each
// rrggbb, every other role its theme's; none of it where it does not.
type own struct{ background, selection, border string }

// shifted is background moved, channel by channel, k times what role is from the theme's own.
func shifted(background, role string, in theme, k float64) string {
	out, to, base := "", channels(roles[role][in]), channels(roles["background"][in])
	for i, part := range channels(background) {
		at, _ := strconv.Atoi(part)
		end, _ := strconv.Atoi(to[i])
		start, _ := strconv.Atoi(base[i])
		out += fmt.Sprintf("%02x", max(0, min(255, int(math.RoundToEven(float64(at)+k*float64(end-start))))))
	}
	return out
}

// lookOn is the look on a terminal whose own background is background, rrggbb, in the theme it
// fits, and whether it reads there, as Python's reads.look: each text role, in the theme's shade,
// has with that background the contrast it has with the theme's own, or reads where that is less,
// and there is a highlight, the background moved k times what the theme's selection is from its
// background, at the largest k up to 1, in hundredths, where each text role has with it what it
// has with the theme's selection, or reads, and it has with the background what the theme's
// selection has with the theme's, or shows.  The border moves whole, as the highlight does at 1.
func lookOn(background string, in theme) (own, bool) {
	keeps := func(on, theirs string) bool {
		for _, role := range textRoles {
			if contrast(roles[role][in], on) < min(contrast(roles[role][in], theirs), reads) {
				return false
			}
		}
		return true
	}
	least := min(contrast(roles["selection"][in], roles["background"][in]), shows)
	if keeps(background, roles["background"][in]) {
		for n := 100; n > 0; n-- {
			lit := shifted(background, "selection", in, float64(n)/100)
			if contrast(lit, background) >= least && keeps(lit, roles["selection"][in]) {
				return own{background, lit, shifted(background, "border", in, 1)}, true
			}
		}
	}
	return own{}, false
}

// colour is a word's colour on this screen, as Python's terminal.colour: its theme's, as the
// terminal's own background has it where the look reads there (lookOn).
func (s Screen) colour(word string) string {
	switch role := roleOf(word); {
	case s.own == own{}:
	case role == "background":
		return s.own.background
	case role == "selection":
		return s.own.selection
	case role == "border":
		return s.own.border
	}
	return colourOf(word, s.theme)
}
