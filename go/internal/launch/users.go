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

// SeatTasksRefusal checks the project's users answer and the seat's plan before queuing any task.
func SeatTasksRefusal(seat, path string, flags map[string]bool, job bool, taken map[string]string) string {
	if seat == "" || taken == nil {
		return ""
	}
	text, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	meta, cmds, err := task.Parse(path, task.Text(text))
	if err != nil {
		return ""
	}
	repo, refused, err := checkout(meta, path, path)
	if err == nil && refused == "" && repo != "" && !answered.Match(text) {
		if why := worker.UsersRefusal(repo, gitcall.RulesTip(repo), "Put the chosen line in the task, which adds it to AGENTS.md."); why != "" {
			return why
		}
	}
	line, err := servedLine(seat, path, cmds, taken)
	if why, ok := err.(*refusedOutright); ok {
		return why.why
	}
	if err != nil || line != nil {
		return ""
	}
	if every, _ := task.Group(cmds); task.ChecksRefusal(every) != "" {
		if !job {
			return "" // preflight counts the checks once it knows the landing suite
		}
		every, _, _, err := laterRefusal(repo, path, meta, cmds, flags)
		if err != nil {
			return err.Error()
		}
		if why := task.ChecksRefusal(every); why != "" {
			return why
		}
	}
	return missingPlanLine(path)
}
