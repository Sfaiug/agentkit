package seat

import (
	"path/filepath"
	"sync"

	"agentkit/internal/config"
)

// Project is the project a seat opened in cwd is filed under, as orch.cwd_project files it: that
// of the first checkout cwd, or a folder above it, is; "" for none.
func Project(cwd string) string {
	stands := sync.OnceValue(listed)
	for dir := config.Resolve(cwd); ; dir = filepath.Dir(dir) {
		if project := checkoutOf(dir, stands); project != "" || filepath.Dir(dir) == dir {
			return project
		}
	}
}
