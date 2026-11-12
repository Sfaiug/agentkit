package seat

import (
	"os"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
)

// seatPath is the PATH a seat's pane in the folder dir starts with: ak's shims, which guard the
// tools it calls, then its opener's PATH, unpinned.  An opener's PATH emptied so adds no entry,
// which would be the seat's folder.
func seatPath(dir string) (string, error) {
	shims, err := shims()
	return strings.Join(append([]string{shims}, unpinned(os.Getenv("PATH"), dir)...), string(os.PathListSeparator)), err
}

// unpinned is the entries of the PATH list path but those that, looked up from the folder dir,
// their links followed, lie under ~/.agentkit/versions: an `ak` found there would run that
// version.  Python's versions.unpinned drops a version's bin; Go's build lies deeper, in its
// go/bin, so every entry under the folder goes.  A relative entry is joined to dir uncleaned, as
// a `..` after a link leaves the link's target.
func unpinned(path, dir string) []string {
	versions := config.Resolve(filepath.Join(config.Home(), "versions"))
	return slices.DeleteFunc(filepath.SplitList(path), func(entry string) bool {
		if !filepath.IsAbs(entry) {
			entry = dir + string(filepath.Separator) + entry
		}
		entry = config.Resolve(entry)
		return entry == versions || strings.HasPrefix(entry, versions+string(filepath.Separator))
	})
}
