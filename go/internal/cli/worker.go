package cli

import (
	"fmt"
	"strings"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
)

func validateWorker(args []string) string {
	usage := commandhelp.Usage("worker")
	parsed, problem := parse(args, []string{"--workspace", "--out", "--session", "--role"}, nil, usage)
	if problem != "" {
		return problem
	}
	if len(parsed.words) != 2 {
		return usage
	}
	roles := []string{"executor", "reviewer", "fixer", "reviewer-pr", "executor-scratch", "fixer-scratch", "reviewer-scratch"}
	if role, ok := parsed.values["--role"]; ok && !contains(roles, role) {
		return fmt.Sprintf("--role must be one of %s (got %s)", strings.Join(roles, ", "), repr(role))
	}
	task := config.Expand(parsed.words[1])
	if !isFile(task) {
		return "no such task file: " + task
	}
	workspace := parsed.values["--workspace"]
	if workspace == "" {
		workspace = "."
	}
	workspace = config.Absolute(workspace)
	if !isDir(workspace) {
		return "no such workspace: " + workspace
	}
	return ""
}
