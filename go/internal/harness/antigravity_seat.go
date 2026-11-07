package harness

import (
	"path"
	"path/filepath"
	"slices"
)

// antigravitySeat is the adapter's line with Go's wrapper where tools/idle-compact.py is, which
// Python runs it under: the words after its `--` run by `ak adapter <root> antigravity seat`;
// false where the line runs under no such wrapper.
func antigravitySeat(root string, line []string) ([]string, bool) {
	at := slices.Index(line, "--")
	if at < 2 || path.Base(line[1]) != "idle-compact.py" {
		return nil, false
	}
	return slices.Concat([]string{filepath.Join(root, "bin", "ak"), "adapter", root, "antigravity", "seat"}, line[at:]), true
}
