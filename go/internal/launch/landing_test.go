package launch

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/host"
	"agentkit/internal/run"
)

func TestALaunchAlongsideDeliveryLeavesPossibleRivalsToPython(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	dir := filepath.Join(run.Runs(), "first")
	if err := os.MkdirAll(dir, 0o777); err != nil {
		t.Fatal(err)
	}
	record := run.Fields("state", "running", "title", "Fix api", "pid", os.Getpid(),
		"waiting_on", run.Fields("line", ".merge-acme.lock", "joined", 1, "land", "tree"))
	if born, ok := host.ReadIdentity(os.Getpid()); ok {
		record.Set("process_identity", run.Fields("boot", born.Boot, "ticks", int(born.Ticks), "started_at", born.StartedAt))
	}
	if err := run.Create(dir, record); err != nil {
		t.Fatal(err)
	}
	write := func(path, title, checks string) {
		t.Helper()
		if err := os.WriteFile(path, []byte("# "+title+"\n\n## Done when\n```bash\n"+checks+"\n```\n"), 0o666); err != nil {
			t.Fatal(err)
		}
	}
	path := filepath.Join(home, "task.md")
	for _, each := range []struct {
		title, checks, other string
		blocked              bool
	}{
		{"Fix ui", "ls *.txt", "ls *.txt", false},
		{"Fix ui", "python3 tests/test_api.py", "python3 tests/test_api.py", true},
		{"Fix ui", "python3 tests/test_ui.py", "python3 tests/test_api.py", false},
		{"Fix ui", "python3 tests/test_*.py", "python3 tests/test_*.py", false},
		{"Repair all widgets retry paths", "true", "true", true},
	} {
		write(path, each.title, each.checks)
		otherTitle := "Fix api"
		if each.blocked && each.checks == "true" {
			otherTitle = each.title
		}
		write(filepath.Join(dir, "task.md"), otherTitle, each.other)
		if err := run.Change(dir, func(r *run.Object) error { r.Set("title", otherTitle); return nil }); err != nil {
			t.Fatal(err)
		}
		if got := going(path); got != each.blocked {
			t.Fatalf("%s / %s: blocked=%v", each.title, each.checks, got)
		}
	}
	if !going("") {
		t.Fatal("seat admission skipped the rival check")
	}
	fallback := filepath.Join(home, "repair-all-widgets-retry-paths.md")
	if err := os.WriteFile(fallback, []byte("## Done when\n```bash\ntrue\n```\n"), 0o666); err != nil {
		t.Fatal(err)
	}
	if !going(fallback) {
		t.Fatal("the task's filename title was not compared")
	}
	write(path, "Fix ui", "true")
	if err := run.Change(dir, func(r *run.Object) error { r.Dict("waiting_on").Delete("land"); return nil }); err != nil {
		t.Fatal(err)
	}
	if !going(path) {
		t.Fatal("an unchecked run was allowed alongside")
	}
}
