package cli

import (
	"bytes"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

// Whose PR a run or a seat reviews stays with Python, which decides so before anything is written.
func TestAReviewUnderARunLeavesNoState(t *testing.T) {
	home := t.TempDir()
	for key, value := range map[string]string{
		"HOME": home, "USERPROFILE": home, "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": filepath.Join(home, "acme-1"),
		"AK_RUN_DEPTH": "0", "AK_RUN_ROLE": "", "AK_MAX_RUNS": "0", "AK_NOTIFY_SINK": "dry-run",
	} {
		t.Setenv(key, value)
	}
	if err := os.MkdirAll(filepath.Join(home, ".agentkit"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(home, ".agentkit", "config.toml"), []byte(testConfig), 0o600); err != nil {
		t.Fatal(err)
	}
	before := tree(t, home)
	var out, errOut bytes.Buffer
	if code := Main([]string{"run", "--review-pr", "https://github.com/acme/api/pull/12"}, &out, &errOut); code != 3 {
		t.Fatalf("exit=%d stdout=%q stderr=%q", code, out.String(), errOut.String())
	}
	if after := tree(t, home); !reflect.DeepEqual(before, after) {
		t.Fatalf("changed HOME: %v", after)
	}
}
