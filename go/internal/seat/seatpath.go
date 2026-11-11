package seat

import (
	"os"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
)

// seatPath is the PATH a seat's pane in the folder dir starts with: ak's shims, which guard the
// tools it calls, then its opener's PATH, unpinned.
func seatPath(dir string) (string, error) {
	shims, err := shims()
	return shims + string(os.PathListSeparator) + unpinned(os.Getenv("PATH"), dir), err
}

// unpinned is the PATH list path without an entry that, looked up from the folder dir, its links
// followed, lies under ~/.agentkit/versions: an `ak` found there would run that version.  Python's
// versions.unpinned drops a version's bin; Go's build lies deeper, in its go/bin, so every entry
// under the folder goes.
func unpinned(path, dir string) string {
	versions := config.Resolve(filepath.Join(config.Home(), "versions"))
	kept := slices.DeleteFunc(filepath.SplitList(path), func(entry string) bool {
		if !filepath.IsAbs(entry) {
			entry = filepath.Join(dir, entry)
		}
		entry = config.Resolve(entry)
		return entry == versions || strings.HasPrefix(entry, versions+string(filepath.Separator))
	})
	return strings.Join(kept, string(os.PathListSeparator))
}
