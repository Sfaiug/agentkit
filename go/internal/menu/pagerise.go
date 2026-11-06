package menu

import (
	"math"
	"strings"

	"agentkit/internal/terminal"
)

// comeUp is a page's lines, `agentkit · <name>` over them, as it comes up, risen 0 to 1
// (motion.Clock.Risen): its name writing itself out in the header and all under the rule out of
// the background (motion.Clock.rise).
func comeUp(s terminal.Screen, lines []string, name string, risen float64) []string {
	lines[0] = written(lines[0], name, risen)
	for i := 2; i < len(lines); i++ {
		lines[i] = s.Fade(lines[i], 1-risen)
	}
	return lines
}

// written is a page's header with its name written out to x of it, 0 to 1, as the page opens: the
// cells after it blank (motion.titled).
func written(header, name string, x float64) string {
	rest, whole := strings.CutPrefix(header, "agentkit · "+name)
	if !whole || x >= 1 {
		return header
	}
	all := []rune(" · " + name)
	shown := string(all[:int(math.RoundToEven(float64(len(all))*max(0, x)))])
	return "agentkit" + shown + strings.Repeat(" ", terminal.Cells(string(all))-terminal.Cells(shown)) + rest
}
