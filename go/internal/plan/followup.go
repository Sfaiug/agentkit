package plan

import (
	"context"
	"fmt"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/notify"
)

// Deferred is whether a plan line carries work assigned to a fix run.
func Deferred(text string) bool {
	line, ok := parse(text)
	return ok && line.Deferred
}

// AddProven writes a review follow-up whose command already failed on proven. It does not
// test the default branch again: that may already hold a fix of its own.
func AddProven(ctx context.Context, name, repo, what, check, proven string, deferred bool) (string, error) {
	if err := holdsCheckout(check, repo); err != nil {
		return "", err
	}
	env, err := environ()
	if err != nil {
		return "", err
	}
	found := rootOf(env, repo, proven)
	if found == "" {
		return "", fmt.Errorf("%s does not hold %s, the commit this check failed on", repo, proven)
	}
	var line string
	err = notify.Held(ctx, name, func(current string) error {
		line, err = addLine(current, repo, config.Fold(what), check, found, proven[:min(12, len(proven))], "", deferred)
		return err
	})
	return line, err
}

// addLine is the one write of a check line, keeping any open line already holding its check.
func addLine(current, repo, what, check, found, base, done string, deferred bool) (string, error) {
	where := named(repo, found)
	if strings.Contains(where, "·") {
		return "", fmt.Errorf("%s: a project a line names holds no `·`", where)
	}
	lines, err := read(current)
	if err != nil {
		return "", err
	}
	marked := where
	if deferred {
		marked += " · deferred"
	}
	for i, text := range lines {
		if old, ok := parse(text); ok && old.Check == check && old.Project == where && old.proven() && base != "" && old.Base == base {
			// Repeating the same proof keeps the line's completed work.
			return strings.TrimFunc(text, config.Space), nil
		}
		if old, ok := parse(text); ok && old.Check == check && old.Project == where && !old.proven() {
			// Keep the original outcome and proof, with the mark this handoff asks for.
			line := added(old.What, check, marked, old.When, old.Base).ticked(done)
			if line == strings.TrimFunc(text, config.Space) {
				return line, nil
			}
			return line, write(current, slices.Replace(lines, i, i+1, line))
		}
	}
	line := added(what, check, marked, time.Now().Format("2006-01-02 15:04"), base).ticked(done)
	return line, write(current, append(lines, line))
}
