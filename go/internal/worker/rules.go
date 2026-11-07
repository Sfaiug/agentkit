package worker

import (
	"embed"
	"strings"
)

// Roles are the roles a turn takes, in Python's PREAMBLES order: rules/<role>.md opens each
// one's prompt, {workspace} where its workspace goes.
var Roles = []string{"executor", "reviewer", "fixer", "reviewer-pr", "executor-scratch", "fixer-scratch", "reviewer-scratch"}

// The rules are Python's, agentkit/worker.py's PREAMBLES by role, GATE as gate.md, a review's
// rules, and REAL_USERS as real-users.md, the rule following them where a project's users are
// real, each with a newline after it: tests/test_go_worker_rules.py refuses any difference, so
// neither copy leaves the other behind.
//
//go:generate sh -c "rm -f rules/*.md && cd ../../.. && python3 -c 'from agentkit import worker as w; [open(f\"go/internal/worker/rules/{name}.md\", \"w\").write(text + \"\\n\") for name, text in {**w.PREAMBLES, \"gate\": w.GATE, \"real-users\": w.REAL_USERS}.items()]'"
//go:embed rules
var rules embed.FS

func rule(name string) string {
	text, _ := rules.ReadFile("rules/" + name + ".md")
	return strings.TrimSuffix(string(text), "\n")
}

// opening is the opening of a turn of that role in workspace, before its task, as the turn was
// given it: a review's rules carry the real-users rule where the workspace's AGENTS.md says
// `users: real` at the target the work lands on (UsersDeclared).
func opening(role, workspace string, given Given) string {
	prompt := strings.ReplaceAll(rule(role), "{workspace}", workspace)
	if UsersDeclared(workspace, given.UsersAt) == "real" {
		gate := rule("gate")
		prompt = strings.ReplaceAll(prompt, gate, gate+"\n"+rule("real-users"))
	}
	return prompt
}
