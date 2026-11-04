package tick

import (
	"slices"

	"agentkit/internal/run"
)

func runRepositories(paths *[]string) bool {
	return run.Every(func(_ string, record *run.Object) bool {
		if repo := record.Str("repo"); repo != "" && !slices.Contains(*paths, repo) {
			*paths = append(*paths, repo)
		}
		return true
	})
}

// A writer holds its repository and checkout even between commands. Landing-line writers,
// whose process is kept on a separate receipt, still need Python's git_busy_paths reader.
func runBusyPaths(paths *[]string) bool {
	return run.Every(func(_ string, record *run.Object) bool {
		if wait := record.Dict("waiting_on"); wait != nil && wait.Truthy("line") {
			return false
		}
		if run.WriterActive(record) {
			for _, key := range []string{"repo", "worktree"} {
				if path := record.Str(key); path != "" {
					*paths = append(*paths, path)
				}
			}
		}
		return true
	})
}
