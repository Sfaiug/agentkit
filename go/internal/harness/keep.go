package harness

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
)

// Keep gives the file a seat's record names its conversation in each name ak gives it beside
// (ReadBy) that it has none of yet (Python's plugin `keep`): a hard link, the same file, so what
// the harness wrote stays once it deletes its own name, as Claude Code does a transcript nobody
// wrote to for `cleanupPeriodDays`.  Claude appends a transcript in place, so a link made once
// stays the file it writes; it is never replaced.  Nothing is kept where no link can be made, as
// with no file yet or across two filesystems; a name holding a NUL is the error Python's os.link
// raises past that.
func Keep(name string, record map[string]any) error {
	names, _ := ReadBy(name, record)
	if len(names) < 2 {
		return nil
	}
	for _, kept := range names[1:] {
		if strings.ContainsRune(names[0]+kept, 0) {
			return errors.New("embedded null byte")
		}
		os.MkdirAll(filepath.Dir(kept), 0o777)
		os.Link(names[0], kept)
	}
	return nil
}
