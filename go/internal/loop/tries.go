package loop

import (
	"os"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/box"
)

// latestTurn is a role's last call in a round, "" before any, Python's latest_turn: its last
// attempt, or a `-retry<N>` the call made of it beside it, whichever was written last, a tie to
// the later name.
func latestTurn(round, name string) string {
	attempt := lastAttempt(round, name)
	if attempt == "" {
		return ""
	}
	latest, at := attempt, modTime(attempt)
	entries, _ := os.ReadDir(round) // by name, so a later one takes a tie
	for _, entry := range entries {
		try := filepath.Join(round, entry.Name())
		if strings.HasPrefix(entry.Name(), filepath.Base(attempt)+"-retry") && !modTime(try).Before(at) {
			latest, at = try, modTime(try)
		}
	}
	return latest
}

// modTime is when the path was last written, the zero time where nothing stands.
func modTime(path string) time.Time {
	info, err := os.Stat(path)
	if err != nil {
		return time.Time{}
	}
	return info.ModTime()
}

// spoke is whether the call at out answered, Python's open_turn on a kill: it wrote its final.md
// and no signal ended it, which its box recorded.
func spoke(out string) bool {
	return exists(filepath.Join(out, "final.md")) && killedWord(box.Exit(out)) == ""
}
