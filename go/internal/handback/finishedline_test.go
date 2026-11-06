package handback

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"unicode/utf8"

	"agentkit/internal/run"
)

func TestEveryEndingUsesPythonsHandbackLine(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	os.MkdirAll(filepath.Join(home, ".agentkit"), 0o700)
	os.WriteFile(filepath.Join(home, ".agentkit", "config.toml"), []byte("[models.opus]\nharness='claude'\nmodel='claude-opus'\neffort='xhigh'\nprovider='test'\n[models.astra]\nharness='codex'\nmodel='gpt'\neffort='xhigh'\nprovider='test'\n[providers.test]\nmode='subscription'\n"), 0o600)
	dir := filepath.Join(home, "acme")
	os.Mkdir(dir, 0o700)
	base := run.Fields("run_id", "acme", "state", "pass", "verdict", "PASS", "rounds", 3,
		"round_summaries", []any{run.NewObject()}, "executor", "opus", "reviewer", "astra",
		"review", run.Fields("executor", "opus", "reviewer", "astra", "executor_provider", "test", "reviewer_provider", "test",
			"verdict", "PASS", "returncode", 0, "done_when", true, "head_sha", "abc", "tree_sha", "def"))
	for _, each := range []struct {
		name   string
		fields *run.Object
		want   string
	}{
		{"merged", run.Fields("merged", true, "pr", "https://github.com/acme/api/pull/1"),
			"finished PASS merged: https://github.com/acme/api/pull/1. Result: {result}. Decide the next step."},
		{"scratch", run.Fields("scratch", true, "worktree", "/workspace"),
			"finished PASS delivered: delivered. Result: {result}. Workspace: /workspace. Decide the next step."},
		{"not merged", run.Fields("no_merge", true),
			"NOT MERGED (1 of 3): --no-merge. Next: read the result. Result: ~/acme/result.md"},
		{"refused", run.Fields("merge_failed", true, "repo", dir, "merge_note", "GitHub refused the merge"),
			"NOT MERGED (1 of 3): GitHub refused the merge. Next: launch the fix the result names, `ak run merge acme`. Result: ~/acme/result.md"},
		{"review failed", run.Fields("state", "fail", "rounds", 1, "review_records", []any{
			run.Fields("kind", "finding", "path", "api.go", "line", 8, "what", "Drops rows"), run.Fields("kind", "done")}),
			"FAIL (1 of 1): api.go:8 - Drops rows. Next: split the task. Result: ~/acme/result.md"},
		{"check failed", run.Fields("state", "fail", "done_when_failure", run.Fields("every", []any{[]any{"check", "rows missing"}})),
			"FAIL (1 of 3): the done-when failed: `check` — rows missing. Next: rewrite the task and relaunch it. Result: ~/acme/result.md"},
		{"final check failed", run.Fields("state", "fail", "final_check", run.Fields("outcome", "failed", "where", "round", "round", 1)),
			"FAIL (1 of 3): the final check failed in round 1: see round-1/once.log. Next: rewrite the task and relaunch it. Result: ~/acme/result.md"},
		{"overridden", run.Fields("state", "fail", "review", run.Fields("overridden", "The reviewer exited 1")),
			"FAIL (1 of 3): The reviewer exited 1. Next: read the result. Result: ~/acme/result.md"},
		{"error", run.Fields("state", "error", "error", "Cannot start"),
			"ERROR (1 of 3): Cannot start. Next: read the result. Result: ~/acme/result.md"},
		{"blocked", run.Fields("state", "blocked", "error", "Cannot do this", "branch", "ak/api"),
			"BLOCKED (1 of 3): Cannot do this. Next: rewrite the task and relaunch it with `from: ak/api`. Result: ~/acme/result.md"},
		{"not needed", run.Fields("state", "not_needed", "not_needed", "Already done"),
			"finished DONE: not needed: Already done. Result: {result}. Decide the next step."},
	} {
		t.Run(each.name, func(t *testing.T) {
			record := base.Copy()
			for _, key := range each.fields.Keys() {
				record.Set(key, each.fields.Get(key))
			}
			want := "run acme " + strings.ReplaceAll(each.want, "{result}", filepath.Join(dir, "result.md"))
			if got := handbackLine(record, dir, true, false); got != want {
				t.Fatalf("got  %q\nwant %q", got, want)
			}
		})
	}
	// A delivered ending's compact form keeps its full notice and follow-ups on disk.
	run.SetAll(base, "merged", true, "pr", strings.Repeat("界", 3000), "followups", []any{"Keep every row"})
	got := handbackLine(base, dir, true, false)
	if got != "run acme finished PASS merged. Result: ~/acme/result.md. 1 review follow-ups in full in result.md. Decide the next step." {
		t.Fatal(got)
	}
	saved, _ := os.ReadFile(filepath.Join(dir, "result.md"))
	if !strings.Contains(string(saved), base.Str("pr")) || !strings.Contains(string(saved), "## Follow-ups\n\n- Keep every row") {
		t.Fatal("the compact notice lost its full news")
	}
}

func TestDecisionsShortenBySentencesThenDropDetailThenNameTheResult(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	dir := filepath.Join(home, "acme")
	os.Mkdir(dir, 0o700)
	for _, each := range []struct{ why, branch, said, move string }{
		{"The API is down. " + strings.Repeat("界", 400), "ak/api", "The API is down.", " with `from: ak/api`"},
		{"The API is down.", strings.Repeat("branch", 100), "The API is down.", ""},
		{strings.Repeat("word ", 400), "ak/api", "The result says why.", ""},
	} {
		record := blocked(each.why)
		record.Set("branch", each.branch)
		want := "run acme BLOCKED (0 of 3): " + each.said + " Next: rewrite the task and relaunch it" + each.move + ". Result: ~/acme/result.md"
		if got := handbackLine(record, dir, true, false); got != want || utf8.RuneCountInString(got) > decisionMost {
			t.Fatalf("got %q, want %q", got, want)
		}
		saved, _ := os.ReadFile(filepath.Join(dir, "result.md"))
		if !strings.Contains(string(saved), strings.TrimSpace(each.why)) || !strings.Contains(string(saved), each.branch) {
			t.Fatal("the shortened decision lost its full reason or next move")
		}
		if handbackLine(record, dir, true, false) != want {
			t.Fatal("a saved notice changed the line")
		}
	}
	// Never type a shortened reason if its full notice cannot be saved.
	other := t.TempDir()
	os.Mkdir(filepath.Join(other, "result.md"), 0o700)
	if got := handbackLine(blocked(strings.Repeat("word ", 400)), other, true, false); got != "" {
		t.Fatal("typed without saving the full reason", got)
	}
}
