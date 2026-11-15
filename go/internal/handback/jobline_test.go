package handback

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/config"
)

func TestAJobsLineIsCutAtAWordOnlyWhereItDoesNotFit(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	dir := filepath.Join(home, ".agentkit", "jobs", "acme")
	os.MkdirAll(dir, 0o700)
	short := "job acme: a.md: BLOCKED: no room. Result: " + filepath.Join(dir, "log.txt") + ". Decide the next step."
	if line, err := JobLine(dir, short); line != short || err != nil {
		t.Fatalf("a line that fits became %q, %v", line, err)
	}
	if _, err := os.Stat(filepath.Join(dir, "ending.txt")); !os.IsNotExist(err) {
		t.Fatalf("a line that fits wrote ending.txt: %v", err)
	}
	long := "job acme: a.md: BLOCKED: " + strings.Repeat("fixtures/api.json is never named ", 100) + short[len("job acme: a.md: BLOCKED: no room"):]
	line, err := JobLine(dir, long)
	tail := "… Result: ~/.agentkit/jobs/acme/ending.txt. Decide the next step."
	front, cut := strings.CutSuffix(line, tail)
	if err != nil || !cut || config.TooLong(line) || !strings.HasPrefix(long, front+" ") {
		t.Fatalf("a long line became %q, %v", line, err)
	}
	if whole, _ := os.ReadFile(filepath.Join(dir, "ending.txt")); string(whole) != long+"\n" {
		t.Fatalf("ending.txt holds %q", whole)
	}
}
