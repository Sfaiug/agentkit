package launch

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/run"
)

func TestATitleNamesATestFileByAWordOfItsNameOrThatWordWithAPlainEnding(t *testing.T) {
	for _, each := range []struct {
		title, file string
		named       bool
	}{{"Invoices round to cents", "tests/test_invoice_rounding.py", true}, {"Allow empty exports", "tests/test_all.py", false},
		{"Fix the test", "tests/test_x.py", false}, {"Go runner", "go/x/runner_test.go", true}} {
		if titled(each.title, each.file) != each.named {
			t.Errorf("%q names %s: %v", each.title, each.file, !each.named)
		}
	}
	got := testFiles([]string{`python3 "tests/test_a.py" go/x_test.go && bash tests/smoke.sh tests/test_*.py`})
	if len(got) != 2 || !got["tests/test_a.py"] || !got["go/x_test.go"] {
		t.Fatalf("test files: %v", got)
	}
}

func TestACheckThreeOtherJobsRanIsNoRivalryUnlessBothTitlesNameIt(t *testing.T) {
	home := config.Resolve(t.TempDir())
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("GIT_CEILING_DIRECTORIES", home) // no tip to read: every shared file counts
	write := func(id, title, state string) {
		t.Helper()
		dir := filepath.Join(run.Runs(), id)
		record := run.Fields("state", state, "title", title, "repo", home, "pid", os.Getpid())
		if born, ok := host.ReadIdentity(os.Getpid()); ok {
			record.Set("process_identity", run.Fields("boot", born.Boot, "ticks", int(born.Ticks), "started_at", born.StartedAt))
		}
		text := "# " + title + "\n\n## Done when\n```bash\npython3 tests/test_docs.py\n```\n"
		if os.MkdirAll(dir, 0o777) != nil || os.WriteFile(filepath.Join(dir, "task.md"), []byte(text), 0o666) != nil || run.Create(dir, record) != nil {
			t.Fatal("cannot write run ", id)
		}
	}
	shared := func(title string) []string {
		t.Helper()
		found, err := rivals(home, filepath.Join(home, "task.md"), title, []string{"python3 tests/test_docs.py"})
		if err != nil || len(found) > 1 {
			t.Fatalf("%v %v", found, err)
		}
		if len(found) == 0 {
			return nil
		}
		return found[0].files
	}
	write("live", "Docs list every page", "running")
	for n, title := range []string{"Add export button", "Rename billing page", "Explain the retry flag"} {
		if got := shared("Search ignores accents"); len(got) != 1 || got[0] != "tests/test_docs.py" {
			t.Fatalf("with %d other jobs: %v", n, got)
		}
		write(fmt.Sprintf("past-%d", n), title, "pass")
	}
	if got := shared("Search ignores accents"); got != nil {
		t.Fatalf("a check three other jobs ran was shared: %v", got)
	}
	if got := shared("Docs show their dates"); len(got) != 1 {
		t.Fatalf("a check both titles name was not shared: %v", got)
	}
}
