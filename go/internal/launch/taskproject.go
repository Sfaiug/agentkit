package launch

import (
	"path/filepath"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/seat"
)

// taskProject is the checkout a task belongs to, Python's handback.task_project: the one the
// repository it works in is, else the one its resolved task file's folder is named for, in any
// case, since an orchestrator files a project's tasks under ~/.agentkit/tasks/<project>/ whatever
// they work in; "" for none, ErrPython where a look at the checkouts fails.
func taskProject(repo, path string) (string, error) {
	if repo != "" {
		return seat.CheckoutOf(repo), nil
	}
	tasks := config.Resolve(filepath.Join(config.Home(), "tasks")) + string(filepath.Separator)
	rest, under := strings.CutPrefix(path, tasks)
	folder, _, filed := strings.Cut(rest, string(filepath.Separator))
	if !under || !filed {
		return "", nil
	}
	checkouts, seen := seat.Checkouts()
	if !seen {
		return "", ErrPython
	}
	for _, checkout := range checkouts {
		if strings.ToLower(filepath.Base(checkout)) == strings.ToLower(folder) {
			return checkout, nil
		}
	}
	return "", nil
}
