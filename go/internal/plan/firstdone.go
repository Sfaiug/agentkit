package plan

import (
	"strings"

	"agentkit/internal/config"
)

// FirstDone is the first done line's words, what a past seat set out to do and did.
func (look Look) FirstDone(name string) string {
	lines, _ := look.read(name)
	for _, line := range lines {
		if boxed(line) && !open(line) {
			return doneWords(line)
		}
	}
	return ""
}

func doneWords(line string) string {
	line = strings.TrimFunc(line, config.Space)
	if entry, ok := parse(line); ok {
		return entry.What
	}
	_, words, _ := strings.Cut(line, "] ")
	return words
}
