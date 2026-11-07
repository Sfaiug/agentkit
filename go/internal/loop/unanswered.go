package loop

import "agentkit/internal/worker"

// unanswered is why no round of a seat's own pull request starts on head, "" for none, Python's
// unanswered_head: its AGENTS.md there has no `users:` answer (worker.UsersRefusal).  Asked of
// every round's head, not only a first review's: a head moves while a launch waits, and with a
// push, a fix or a resume, and the seat hears the question before any turn is spent on one.
func unanswered(repo, head string) string {
	return worker.UsersRefusal(repo, head, "Add the chosen line to AGENTS.md's front matter on the PR's branch.")
}
