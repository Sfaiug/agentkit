package seat

import "agentkit/internal/gitcall"

func reopenProject(record map[string]any, dry bool) error {
	if repo, _ := record["repo"].(string); repo != "" && !dry {
		return gitcall.Refresh(repo)
	}
	return nil
}
