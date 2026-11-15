package handback

import (
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
)

// JobLine is Python's seat_line: a job's line as its seat can be handed it (config.TooLong), cut
// as a run's notice is (seatNotice).  One that fits is as it is; one too long is written whole to
// ending.txt in the job's directory, and its front up to ". Result: " is cut back a word at a time
// until it fits before a tail naming that file as its result.
func JobLine(dir, line string) (string, error) {
	if fits(line) {
		return line, nil
	}
	whole := filepath.Join(dir, "ending.txt")
	if err := os.WriteFile(whole, []byte(line+"\n"), 0o666); err != nil {
		return "", err
	}
	tail := "… Result: " + shortPath(whole) + ". Decide the next step."
	said := []rune(line[:max(strings.LastIndex(line, ". Result: "), 0)])
	front := string(said[:min(len(said), int(config.Longest()))]) // no word past it can fit
	for front != "" && !fits(front+tail) {
		front = front[:max(strings.LastIndex(front, " "), 0)]
	}
	return front + tail, nil
}
