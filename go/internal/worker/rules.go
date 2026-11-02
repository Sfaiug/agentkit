package worker

import (
	"embed"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/task"
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

// sizeRule is what a builder is told of the first review's ceiling, in the words of Python's
// size_rule.
const sizeRule = "its first review would read more than %d added lines"

// comment is a YAML comment closing a front matter value.
var comment = regexp.MustCompile(`(^|` + config.SpaceClass + `)#.*`)

// Prompt is the opening of a turn of that role in workspace, before its task: a review's rules
// carry the real-users rule where the workspace's AGENTS.md says `users: real`, read as the YAML
// word it is, its comment and quotes aside.
func Prompt(role, workspace string) string {
	return opening(role, workspace, Given{})
}

// opening is that as the turn was given it: `users:` read at the target the work lands on, as a
// branch cannot switch off the rule its own review is held to, and the first review's ceiling the
// number in force, the host's where the run holds none.
func opening(role, workspace string, given Given) string {
	prompt := strings.ReplaceAll(rule(role), "{workspace}", workspace)
	declared := ""
	if given.UsersAt != "" {
		declared = gitcall.DeclaredAt(workspace, given.UsersAt, "users")
	} else if data, err := os.ReadFile(filepath.Join(workspace, "AGENTS.md")); err == nil {
		declared = task.FrontValue(task.Text(data), "users")
	}
	users := strings.TrimFunc(comment.ReplaceAllString(declared, ""), config.Space)
	if len(users) >= 2 && users[0] == users[len(users)-1] && strings.ContainsRune(`'"`, rune(users[0])) {
		users = strings.TrimFunc(users[1:len(users)-1], config.Space)
	}
	if users == "real" {
		gate := rule("gate")
		prompt = strings.ReplaceAll(prompt, gate, gate+"\n"+rule("real-users"))
	}
	lines := given.ReviewLines
	if lines == 0 {
		numbers, err := config.HostNumbers()
		if err != nil {
			return prompt
		}
		lines = numbers.ReviewLines
	}
	return strings.ReplaceAll(prompt, fmt.Sprintf(sizeRule, config.DefaultReviewLines), fmt.Sprintf(sizeRule, lines))
}
