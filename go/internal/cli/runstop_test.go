package cli

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/host"
)

// A resume refuses in Python's words what no one resumes, and leaves any other it cannot pick up.
func TestRunResumeRefusals(t *testing.T) {
	id := "20261020-0900-fix-api"
	born, _ := host.ReadIdentity(os.Getpid())
	live := fmt.Sprintf(`{"state":"running","pid":%d,"process_identity":{"boot":%q,"ticks":%d,"started_at":%f}}`, os.Getpid(), born.Boot, born.Ticks, born.StartedAt)
	for name, setup := range map[string]struct {
		record string
		code   int
		said   string
	}{
		"going":   {live, 2, fmt.Sprintf("ak run: %s is still running as pid %d\n", id, os.Getpid())},
		"blocked": {`{"state":"blocked"}`, 2, "ak run: blocked runs are not resumed; the orchestrator writes a new task\n"},
		"stopped": {`{"state":"stopped"}`, 2, "ak run: stopped runs are not resumed; start a new task from its branch\n"},
		"a FAIL":  {`{"state":"fail"}`, 3, "ak run resume: not implemented in Go yet\n"},
	} {
		t.Run(name, func(t *testing.T) {
			home := t.TempDir()
			for key, value := range map[string]string{"HOME": home, "USERPROFILE": home, "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
				"AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AK_NOTIFY_SINK": "dry-run", "TZ": "UTC"} {
				t.Setenv(key, value)
			}
			path := filepath.Join(home, ".agentkit", "runs", id, "run.json")
			if err := os.MkdirAll(filepath.Dir(path), 0o777); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(path, []byte(setup.record), 0o666); err != nil {
				t.Fatal(err)
			}
			var out, errOut bytes.Buffer
			if code := runResume([]string{id}, &out, &errOut); code != setup.code || errOut.String() != setup.said || out.Len() != 0 {
				t.Fatalf("exit %d, out %q, err %q", code, out.String(), errOut.String())
			}
			if after, _ := os.ReadFile(path); string(after) != setup.record {
				t.Fatalf("record %s", after)
			}
		})
	}
}
