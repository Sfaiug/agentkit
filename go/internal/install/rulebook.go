package install

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
)

// rulebook undoes what an older install linked, as install.sh's step (4) does: ak's rules reach
// its own sessions at launch, so every other Claude Code and Codex the owner runs is theirs
// again.  ~/.codex/AGENTS.md or ~/.claude/CLAUDE.md, a link into this checkout, goes, and the
// file it displaced, the newest `<file>.bak-<digits>` beside it by name, comes back: a backup
// made by `cp -p` holds the time of the file it copied.  A link is ak's only where it proves to
// be: one into a folder that is gone, or outside this checkout, stays.
func rulebook(out io.Writer) error {
	checkout := config.Resolve(config.Repo()) + string(filepath.Separator)
	home := config.UserHome()
	for _, target := range []string{filepath.Join(home, ".codex", "AGENTS.md"), filepath.Join(home, ".claude", "CLAUDE.md")} {
		link, err := os.Readlink(target)
		if err != nil {
			continue
		}
		if !filepath.IsAbs(link) {
			link = filepath.Join(filepath.Dir(target), link)
		}
		folder := filepath.Dir(link)
		info, err := os.Stat(folder)
		if err != nil || !info.IsDir() || !strings.HasPrefix(config.Resolve(folder)+string(filepath.Separator), checkout) ||
			os.Remove(target) != nil {
			continue
		}
		fmt.Fprintf(out, "unlinked %s; agentkit's rules now reach its own sessions only\n", target)
		backups := config.Glob(filepath.Dir(target), filepath.Base(target)+".bak-[0-9]*")
		for i := len(backups) - 1; i >= 0; i-- {
			if info, err := os.Stat(backups[i]); err == nil && info.Mode().IsRegular() {
				if err := os.Rename(backups[i], target); err != nil {
					return err
				}
				fmt.Fprintf(out, "restored %s from %s\n", target, backups[i])
				break
			}
		}
	}
	return nil
}
