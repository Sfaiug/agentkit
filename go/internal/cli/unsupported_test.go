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
	turn := filepath.Join(home, "hand-in.jsonl")
	// a run Python's maintenance would reap leaves even an open nobody typed to Python
	if err := os.MkdirAll(filepath.Join(home, ".agentkit", "runs", "acme-1"), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(home, ".agentkit", "config.toml"), []byte(testConfig), 0600); err != nil {
		t.Fatal(err)
	}
	for path, content := range map[string]string{task: "# fix-api\n\nReturn 404 for a missing user.\n\n## Done when\n\n```bash\nmake test\n```\n", turn: `{"kind":"turn","role":"fixer","workspace":".","findings":[{"path":"task.md","line":1,"what":"x","evidence":{"run":"false"}}],"context":"` + strings.Repeat("x", 70_000) + `"}` + "\n"} {
		if err := os.WriteFile(path, []byte(content), 0600); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("AK_HAND_IN", turn)
	before := tree(t, home)
	// One call a line: milestones in flight each take theirs out, and lines apart merge.
	calls := [][]string{
		{},
		{"attach", "--client"},
		{"usage", "--json"},
		{"models", "--refresh"},
		{"worker", "acme", task},
		{"run", task, "--no-merge"},
		{"run", "gc", "--dry-run"},
		{"run", "--review-pr", "https://github.com/acme/api/pull/12"},
		{"orch", "acme", "--dry-run"},
		{"orch", "acme"},
		{"orch", "ended", "acme", "1700000000"},
		{"orch", "stop", "acme"},
		{"plan", "check", "٣", "true"},
		{"plan", "check", "²", "a\nb"},
		{"plan", "check", "1", "true \xff"},
		{"hand-in", "done"},
		{"notify", "needs", "Which branch?"},
		{"watch"},
		{"watch", "--dry-run"},
		{"doctor"},
		{"browser", "mcp-register"},
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
