package harness

import (
	"os"
	"path/filepath"
)

// Keep gives the file a seat's record names its conversation in each name ak gives it beside
// (ReadBy) that it has none of yet (Python's plugin `keep`): a hard link, the same file, so what
// the harness wrote stays once it deletes its own name, as Claude Code does a transcript nobody
// wrote to for `cleanupPeriodDays`.  Claude appends a transcript in place, so a link made once
// stays the file it writes; it is never replaced.  Nothing is kept where no link can be made, as
// with no file yet or across two filesystems.
func Keep(name string, record map[string]any) {
	names, _ := ReadBy(name, record)
	if len(names) < 2 {
		return
	}
	for _, kept := range names[1:] {
		os.MkdirAll(filepath.Dir(kept), 0o777)
		os.Link(names[0], kept)
	}
}
