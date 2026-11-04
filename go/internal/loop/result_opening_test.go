//go:build linux || darwin

package loop

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
)

func TestResultDecisionsAndUnchangedHeadings(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	for _, each := range []struct {
		record        *run.Object
		outcome, want string
	}{
		{run.Fields("state", "blocked", "error", "Rewrite this.", "branch", "ak/acme"), "BLOCKED",
			"# BLOCKED (0 of 3) — Acme\nWhy: Rewrite this.\nNext: rewrite the task and relaunch it with `from: ak/acme`"},
		{run.Fields("state", "error", "error", "Cannot start."), "FAIL",
			"# ERROR (0 of 3) — Acme\nWhy: Cannot start.\nNext: read the result"},
		{run.Fields("state", "pass", "no_merge", true), "PASS, not merged: --no-merge",
			"# NOT MERGED (0 of 3) — Acme\nWhy: --no-merge\nNext: read the result"},
		{run.Fields("state", "exhausted", "quota_dry", true, "error", "Every provider is spent."), "FAIL",
			"# FAIL (0 of 3) — Acme\nWhy: Every provider is spent\nNext: wait for the provider"},
		{run.Fields("state", "pass", "merged", true), "PASS, merged", "# PASS, merged — Acme"},
		{run.Fields("state", "pass", "scratch", true), "PASS, delivered", "# PASS, delivered — Acme"},
		{run.Fields("state", "not_needed"), "not needed: already done", "# not needed: already done — Acme"},
		{run.Fields("state", "stopped"), "FAIL", "# FAIL — Acme"},
	} {
		run.SetAll(each.record, "title", "Acme", "rounds", 3)
		if got := resultOpening(home, each.record, each.outcome); got != each.want {
			t.Errorf("%s: got %q, want %q", run.Line(each.record), got, each.want)
		}
	}
}

func TestResultOpeningKeepsEveryClaimAndChecksFirstDiagnostics(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("HOME", dir)
	claim := func(path string) *run.Object {
		return run.Fields("kind", "finding", "path", path, "line", 1, "what", strings.Repeat("Drops rows. ", 80),
			"why", "Data is lost.", "evidence", run.Fields("quote", "rows[:-1]"))
	}
	record := run.Fields("state", "fail", "rounds", 1, "title", "Acme", "round_summaries", []any{run.NewObject()},
		"review_records", []any{claim("parse.py"), claim("export.py"), run.Fields("kind", "done")},
		"done_when_failure", run.Fields("every", []any{[]any{"rows", "last"}, []any{"export", "last"}}),
		"final_check", run.Fields("outcome", "failed", "where", "landing", "line", "live: last"))
	whole := filepath.Join(dir, "donewhen-whole-acme.log")
	os.WriteFile(whole, []byte("rows first\nrows second\nrows third\nlast\n"), 0o600)
	os.Mkdir(filepath.Join(dir, "round-1"), 0o700)
	os.WriteFile(filepath.Join(dir, "round-1", "donewhen.log"), []byte("$ preview\n[exit 0]\nExample: $ rows\n[exit 9]\nexample diagnostic\n\n"+
		"$ rows\n[exit 1]\n"+
		"[only part of this output is shown; all of it is in "+whole+"]\nlast\n\n"+
		"$ export\n[exit 1]\nexport first\nexport second\nlast\n"), 0o600)
	os.WriteFile(filepath.Join(dir, "final-check.log"), []byte("$ preview\n[exit 0]\nExample: $ live\n[exit 9]\nexample diagnostic\n\n"+
		"$ live\n[exit 1]\nlive first\nlive second\nlast\n"), 0o600)
	lines := strings.Split(resultOpening(dir, record, "FAIL"), "\n")
	if len(lines) != 3 || lines[0] != "# FAIL (1 of 1) — Acme" || lines[2] != "Next: split the task" {
		t.Fatalf("opening: %q", lines)
	}
	for _, want := range []string{"parse.py:1 - " + strings.Repeat("Drops rows. ", 80), "export.py:1 - ",
		"Data is lost.", "Quote: rows[:-1]", "`rows` — rows first rows second rows third",
		"`export` — export first export second last", "`live` — live first live second last"} {
		if !strings.Contains(lines[1], want) {
			t.Errorf("missing %q in %q", want, lines[1])
		}
	}
}

func TestResultRebuildKeepsANewerNotLiveOpening(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("HOME", dir)
	const opening = "# NOT LIVE (1 of 3) — Acme\nWhy: Health failed.\nNext: launch the fix the result names"
	// The report's diff was read before the NOT LIVE notice was written.
	os.WriteFile(filepath.Join(dir, "result.md"), []byte(opening+"\n\nOld body"), 0o600)
	if err := save(dir, "\n\nNew body", run.Fields("merged", true), "PASS, merged"); err != nil {
		t.Fatal(err)
	}
	if saved, _ := os.ReadFile(filepath.Join(dir, "result.md")); string(saved) != opening+"\n\nNew body" {
		t.Fatalf("rebuilt: %s", saved)
	}
	if err := WriteResult(dir, run.Fields("state", "blocked", "title", "Acme", "error", "Rewrite.")); err != nil {
		t.Fatal(err)
	}
	if saved, _ := os.ReadFile(filepath.Join(dir, "result.md")); !strings.HasPrefix(string(saved),
		"# BLOCKED (0 of 0) — Acme\nWhy: Rewrite.\nNext: rewrite the task and relaunch it\n\nVERDICT: none") {
		t.Fatalf("early failure: %s", saved)
	}
}
