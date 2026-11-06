package cli

import (
	"bytes"
	"io/fs"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"
)

func TestUnimplementedOperationsLeaveNoState(t *testing.T) {
	home := t.TempDir()
	for key, value := range map[string]string{
		"HOME": home, "USERPROFILE": home, "AGENTKIT_SESSION": "acme", "AGENTKIT_RUN_DIR": "",
		"AK_RUN_DEPTH": "0", "AK_RUN_ROLE": "",
	} {
		t.Setenv(key, value)
	}
	task := filepath.Join(home, "task.md")
	// A run without its record keeps maintenance in shadow.
	if err := os.MkdirAll(filepath.Join(home, ".agentkit", "runs", "acme-1"), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(home, ".agentkit", "config.toml"), []byte(testConfig), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(task, []byte("# fix-api\n\nReturn 404 for a missing user.\n\n## Done when\n\n```bash\nmake test\n```\n"), 0600); err != nil {
		t.Fatal(err)
	}
	before := tree(t, home)
	// One call a line: milestones in flight each take theirs out, and lines apart merge.
	calls := [][]string{
		{"usage", "--json"},
		{"worker", "acme", task},
		{"run", task},
		{"run", "--review-pr", "https://github.com/acme/api/pull/12"},
		{"orch", "acme"},
		{"orch", "ended", "acme", "1700000000"},
		{"orch", "ended", "--model"},
		{"plan", "check", "٣", "true"},
		{"plan", "check", "²", "a\nb"},
		{"plan", "check", "1", "true \xff"},
		{"notify", "needs", "Which branch?"},
		{"watch", "--dry-run"},
	}
	if runtime.GOOS == "darwin" {
		calls = append(calls, []string{"macbridge", "--reader"})
	}
	for _, args := range calls {
		t.Run(strings.Join(args, " "), func(t *testing.T) {
			var out, errOut bytes.Buffer
			if code := Main(args, &out, &errOut); code != 3 || out.Len() != 0 || strings.Count(errOut.String(), "\n") != 1 || !strings.Contains(errOut.String(), "not implemented") {
				t.Fatalf("exit=%d stdout=%q stderr=%q", code, out.String(), errOut.String())
			}
			if after := tree(t, home); !reflect.DeepEqual(before, after) {
				t.Fatalf("unimplemented operation changed HOME: %v", after)
			}
		})
	}
}

func tree(t *testing.T, root string) map[string]string {
	t.Helper()
	files := map[string]string{}
	err := filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.IsDir() {
			files[path] = "directory"
		} else {
			data, err := os.ReadFile(path)
			if err != nil {
				return err
			}
			files[path] = string(data)
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return files
}
