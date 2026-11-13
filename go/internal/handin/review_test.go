package handin

import (
	"os"
	"path/filepath"
	"testing"
)

func TestARecordFileIsReadAsPythonReadsIt(t *testing.T) {
	turn := func(role string) string {
		return `{"kind": "turn", "workspace": "/w", "role": "` + role + `", "findings": []}` + "\n"
	}
	finding := `{"kind": "finding", "path": "a", "line": 1, "what": "w", "why": "y", "evidence": {"quote": "q"}}` + "\n"
	for name, each := range map[string]struct {
		text    string
		closed  bool
		records int
	}{
		"done":              {turn("reviewer") + finding + `{"kind": "done"}` + "\n", true, 2},
		"unclosed":          {turn("reviewer") + finding, false, 1},
		"another role's":    {turn("executor") + finding + `{"kind": "done"}` + "\n", false, 0},
		"no turn":           {`{"kind": "done"}` + "\n", false, 0},
		"closing before":    {turn("executor") + `{"kind": "done"}` + "\n" + `{"kind": "done"}` + "\n", false, 0},
		"blocked with why":  {turn("executor") + `{"kind": "blocked", "why": "x"}` + "\n", true, 1},
		"blocked without":   {turn("executor") + `{"kind": "blocked", "why": " "}` + "\n", false, 0},
		"a row of no words": {turn("reviewer") + `{"kind": "finding", "path": "a", "line": 1}` + "\n", false, 0},
		"not JSON":          {turn("reviewer") + "{\n", false, 0},
	} {
		path := filepath.Join(t.TempDir(), File)
		if err := os.WriteFile(path, []byte(each.text), 0o666); err != nil {
			t.Fatal(err)
		}
		review, there := Read(path)
		if !there || len(review.Records) != each.records || (review.Closing() != nil) != each.closed {
			t.Errorf("%s: there=%v records=%d closing=%v", name, there, len(review.Records), review.Closing())
		}
	}
	if _, there := Read(filepath.Join(t.TempDir(), File)); there {
		t.Error("no file is no review")
	}
}

func TestAReviewSaysItsVerdictAndItsText(t *testing.T) {
	path := filepath.Join(t.TempDir(), File)
	os.WriteFile(path, []byte(`{"kind": "turn", "workspace": "/w", "role": "reviewer-scratch"}
{"kind": "finding", "path": "a", "line": 2, "what": "w", "why": "y", "evidence": {"run": "false", "commit": "workspace", "returncode": 1, "output": "said"}}
{"kind": "done"}
`), 0o666)
	review, _ := Read(path)
	if want := "VERDICT: FAIL\n\n## Findings\n- a:2 - w - y\n  $ false\n  Commit workspace:\n  [exit 1]\n  said\n"; review.Verdict() != "FAIL" || review.Text() != want {
		t.Fatalf("verdict %s, text %q, want %q", review.Verdict(), review.Text(), want)
	}
}

func TestAFollowUpsCheckRunsWithoutItsReviewersBound(t *testing.T) {
	const check = "tools/test.sh tests/test_api.py::test_cleanup -q"
	for proof, each := range map[string]struct {
		code string
		want string
	}{
		"timeout 120 " + check: {"1", check},
		"timeout 15s " + check: {"1", check},
		"timeout 20 " + check:  {"124", "timeout 20 " + check},
	} {
		path := filepath.Join(t.TempDir(), File)
		text := `{"kind": "turn", "workspace": "/w", "role": "reviewer", "findings": []}` + "\n" +
			`{"kind": "follow-up", "path": "api.py", "line": 2, "what": "expired rows stay", "why": "cleanup lags", "evidence": {"run": "` +
			proof + `", "returncode": ` + each.code + `, "output": ""}}` + "\n" + `{"kind": "done"}` + "\n"
		if err := os.WriteFile(path, []byte(text), 0o666); err != nil {
			t.Fatal(err)
		}
		review, _ := Read(path)
		checks, _, _ := review.FollowupRecords()
		if got := checks.Str(review.Followups()[0].(string)); got != each.want {
			t.Errorf("%s ending in %s: check %q, want %q", proof, each.code, got, each.want)
		}
	}
}
