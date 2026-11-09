//go:build linux

package tick

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/loop"
	"agentkit/internal/run"
)

func TestADeclinedResumeLeavesPythonAnUnthrottledWait(t *testing.T) {
	dir, record, tick := waiter(t)
	ak := filepath.Dir(filepath.Dir(dir))
	put(t, filepath.Join(ak, "config.toml"), "[defaults]\nworkers=['opus','astra']\n[models.opus]\nharness='claude'\nmodel='opus'\neffort='high'\nprovider='anthropic'\n[models.astra]\nharness='codex'\nmodel='astra'\neffort='high'\nprovider='openai'\n[providers.anthropic]\nmode='subscription'\n[providers.openai]\nmode='subscription'\n[google_cloud]\nactive=true\n")
	t.Setenv("AK_MAX_RUNS", "0")
	t.Setenv("AK_RUN_DEPTH", "0")
	t.Setenv("AGENTKIT_RUN_DIR", "")
	bin := strings.Split(os.Getenv("PATH"), string(os.PathListSeparator))[0]
	adapters := t.TempDir()
	for _, name := range []string{"claude", "codex", "bwrap"} {
		put(t, filepath.Join(bin, name), "#!/bin/sh\nexit 0\n")
		if err := os.Chmod(filepath.Join(bin, name), 0o700); err != nil {
			t.Fatal(err)
		}
	}
	for _, name := range []string{"claude", "codex"} {
		put(t, filepath.Join(adapters, name+".sh"), "#!/bin/sh\nprintf 'ready\\n'\n")
		if err := os.Chmod(filepath.Join(adapters, name+".sh"), 0o700); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
	put(t, filepath.Join(ak, "state", "usage.json"), run.Line(run.Fields("fetched_at", epoch(time.Now()), "providers",
		run.Fields("anthropic", run.Fields("resets", 0), "openai", run.Fields("resets", 0)))))
	oid := os.Getenv("REF_ANSWER")
	review := run.Fields("executor", "opus", "reviewer", "astra", "executor_provider", "anthropic", "reviewer_provider", "openai",
		"verdict", "PASS", "done_when", true, "returncode", 0, "head_sha", oid, "tree_sha", oid)
	run.SetAll(record, "state", "waiting", "base_sha", oid, "review", review, "round_summaries", []any{review.Copy()},
		"verdict", "FAIL", "executor", "opus", "reviewer", "astra", "waiting_on", run.Fields("ref", "origin/main", "sha", "baseline"))
	put(t, filepath.Join(dir, "run.json"), run.Line(record))
	put(t, filepath.Join(dir, "task.md"), "# Add retry\n\n## Done when\n```bash\ntrue\n```\n")
	if !loop.Pickup(dir, record) {
		t.Fatal("the merge wait must be eligible before launch checks its machines")
	}
	before := read(t, filepath.Join(dir, "run.json"))
	start := time.Now()
	for attempt := range 3 {
		now := start.Add(time.Duration(attempt) * 601 * time.Second)
		tick.clock = func() time.Time { return now }
		if err := tick.waiting(); !errors.Is(err, errLeft) {
			t.Fatalf("did not hand the rentable machine's resume to Python: %v", err)
		}
		if read(t, filepath.Join(dir, "run.json")) != before {
			t.Fatal("declined resume rewrote or throttled Python's wait")
		}
	}
}
