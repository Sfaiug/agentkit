package loop

import (
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/handback"
	"agentkit/internal/run"
)

// NotLive is the line a merge its target's `health:` broke is told in, its NOT LIVE decision, with
// result.md opening on that decision and keeping `told` whole (handback.not_live_line): a run
// cleaned up since gets its directory back.  Its caller holds the run's delivery lock.
func NotLive(dir, told string) (string, error) {
	if err := os.MkdirAll(dir, 0o777); err != nil {
		return "", err
	}
	record, _ := run.Read(dir)
	if record == nil {
		record = run.NewObject()
	}
	path, heading := filepath.Join(dir, "result.md"), "\n## Seat notice\n\n"
	saved, err := os.ReadFile(path)
	if err != nil && !os.IsNotExist(err) {
		return "", err
	}
	rest := string(saved)
	if !strings.HasPrefix(rest, heading) {
		_, rest, _ = strings.Cut(rest, "\n\n")
	}
	text := decisionReport(dir, record, "NOT LIVE", told, handback.ResultNames) + "\n\n" + rest
	if _, kept, _ := strings.Cut(text, heading); told != "" && !strings.Contains(kept, told) {
		text += heading + told + "\n"
	}
	if err := os.WriteFile(path, []byte(text), 0o666); err != nil {
		return "", err
	}
	return handback.DecisionLine(record, dir, "NOT LIVE", told, handback.ResultNames, "")
}
