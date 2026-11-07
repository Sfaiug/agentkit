package launch

import (
	"os"
	"regexp"

	"agentkit/internal/gitcall"
	"agentkit/internal/task"
	"agentkit/internal/worker"
)

// answered is a task naming the owner's `users:` answer, which it adds to AGENTS.md.
var answered = regexp.MustCompile(`\busers: (none|real)\b`)

// UsersRefusal is why a seat's launch of the task at path waits for its owner, "" for none, as
// Python's main asks users_refusal once the rounds are read: a task naming neither answer, into a
// checkout whose AGENTS.md on its default branch (gitcall.RulesTip) has none.  A launch outside a
// seat never waits, nor one with no checkout to read, a refused one or one Python finds, whose
// launch Python asks.
func UsersRefusal(path string) string {
	if seat, _, _ := Seat(); seat == "" {
		return ""
	}
	text, err := os.ReadFile(path)
	if err != nil || answered.Match(text) {
		return ""
	}
	meta, _, err := task.Read(path)
	if err != nil {
		return ""
	}
	repo, refused, err := checkout(meta, path, path)
	if err != nil || refused != "" || repo == "" {
		return ""
	}
	return worker.UsersRefusal(repo, gitcall.RulesTip(repo), "Put the chosen line in the task, which adds it to AGENTS.md.")
}
