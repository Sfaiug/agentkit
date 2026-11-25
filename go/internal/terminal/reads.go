package terminal

import (
	"cmp"
	"fmt"
	"math"
	"slices"
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

// shifted is background moved, channel by channel, k times what role is from the theme's own, k
// n/d, each channel rounded as Python rounds, a half to the even whole number.
func shifted(background, role string, in theme, k [2]int) string {
	out, to, base := "", channels(roles[role][in]), channels(roles["background"][in])
	for i, part := range channels(background) {
		at, _ := strconv.Atoi(part)
		end, _ := strconv.Atoi(to[i])
		start, _ := strconv.Atoi(base[i])
		n, d := at*k[1]+k[0]*(end-start), k[1]
		whole, left := n/d, n%d
		if left < 0 {
			whole, left = whole-1, left+d
		}
		if 2*left > d || 2*left == d && whole%2 != 0 {
			whole++
		}
		out += fmt.Sprintf("%02x", max(0, min(255, whole)))
	}
	return out
}

// tried is each k, n/d, from 1 down that the highlight is tried at, exact, as Python's reads._ks:
// 1, each where a channel turns, half way between two of its values, and half way on to the next,
// so every colour the move passes through is tried, a turn's own too, where two channels turn at
// once.
func tried(in theme) [][2]int {
	turns := [][2]int{{1, 1}, {0, 1}}
	to, base := channels(roles["selection"][in]), channels(roles["background"][in])
	for i := range to {
		end, _ := strconv.Atoi(to[i])
		start, _ := strconv.Atoi(base[i])
		for n, far := 0, max(end-start, start-end); n < far; n++ {
			turns = append(turns, [2]int{2*n + 1, 2 * far})
		}
	}
	slices.SortFunc(turns, func(a, b [2]int) int { return cmp.Compare(b[0]*a[1], a[0]*b[1]) })
	turns = slices.CompactFunc(turns, func(a, b [2]int) bool { return a[0]*b[1] == b[0]*a[1] })
	var out [][2]int
	for i := 1; i < len(turns); i++ {
		high, low := turns[i-1], turns[i]
		out = append(out, high, [2]int{high[0]*low[1] + low[0]*high[1], 2 * high[1] * low[1]})
	}
	return out
}

// lookOn is the look on a terminal whose own background is background, rrggbb, in the theme it
// fits, as Python's reads.look, none where it does not read there: each text role, in the theme's
// shade, has with that background the contrast it has with the theme's own, or reads where that is
// less, and there is a highlight, the background moved k times what the theme's selection is from
// its background, at the largest k up to 1 (tried), where each text role has with it what it has
// with the theme's selection, or reads, and it has with the background what the theme's selection
// has with the theme's, or shows.  The border moves whole, as the highlight does at 1.
func lookOn(background string, in theme) own {
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
		for _, k := range tried(in) {
			lit := shifted(background, "selection", in, k)
			if contrast(lit, background) >= least && keeps(lit, roles["selection"][in]) {
				return own{background, lit, shifted(background, "border", in, [2]int{1, 1})}
			}
		}
	}
	return own{}
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
