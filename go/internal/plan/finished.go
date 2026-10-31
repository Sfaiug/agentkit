package plan

import (
	"regexp"
	"strings"

	"agentkit/internal/config"
)

var (
	// a box line, by hand or by `ak plan`, as plan.BOX reads one
	boxLine = regexp.MustCompile(`^\s*(?:[-*+]|\p{Nd}+[.)])\s*\[[^\]\n]*\]`)
	// what marks a line `ak plan` wrote, however its spacing was changed by hand since
	planned = regexp.MustCompile(`(?i)\bcheck\s*:|·\s*written\b|·\s*your\s+eye\b|·\s*done\b`)
)

// boxed is whether the line is a box line: never a link, `[text](url)`, which Go's regexp
// cannot look ahead for.
func boxed(line string) bool {
	at := boxLine.FindStringIndex(line)
	return at != nil && !strings.HasPrefix(line[at[1]:], "(")
}

// open is a box line that does not read as done: done is a check line ticked with the commit
// its check passed on, an eye line however it is ticked, or a hand-kept line ticked with none
// of `ak plan`'s fields; every other box is open, since nothing proved it.
func open(line string) bool {
	if entry, ok := parse(line); ok {
		return entry.Check != "" && !entry.proven()
	}
	line = strings.TrimFunc(line, config.Space)
	return boxed(line) && !(strings.HasPrefix(line, "- [x] ") && !planned.MatchString(line))
}

// Finished is whether the seat's plan holds done work and owes none, as plan.finished reads it:
// the seat's work is done, which ak reads and nobody declares.  No plan, one nothing can read
// and one owing an open line are not; ErrUnread where only open deferred lines stand in the way,
// which Python owes only while no run has them (`taken`).
func Finished(name string) (bool, error) {
	lines, err := read(name)
	if err != nil {
		return false, nil
	}
	done, deferred := false, false
	for _, line := range lines {
		entry, ok := parse(line)
		switch {
		case !open(line):
			done = done || boxed(line)
		case !ok || !entry.Deferred:
			return false, nil
		default:
			deferred = true
		}
	}
	if done && deferred {
		return false, ErrUnread
	}
	return done, nil
}
