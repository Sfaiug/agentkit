package loop

import (
	"bytes"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"agentkit/internal/run"
)

func TestSelectedTestsRequireRunAndFailureNames(t *testing.T) {
	out := t.TempDir()
	for name, text := range map[string]string{"AK_FAILED": "a\nb\nother\n", "AK_RAN": "a\n"} {
		if err := os.WriteFile(filepath.Join(out, name), []byte(text), 0o666); err != nil {
			t.Fatal(err)
		}
	}
	result := reportedTests(ran{code: 1}, out, [][]string{{"a", "b"}}, io.Discard)
	if !reflect.DeepEqual(result.confirmed, []string{"a"}) {
		t.Fatalf("confirmed a test not both requested, run and failed: %v", result.confirmed)
	}
	var output bytes.Buffer
	result = reportedTests(ran{}, out, [][]string{{"a", "missing"}}, &output)
	if result.code == 0 || len(result.confirmed) != 0 || output.Len() == 0 {
		t.Fatalf("a runner skipping a requested test proved green: %+v, %q", result, output.String())
	}
}

// A report file the check linked elsewhere names nothing: read outside the box, it could reach a
// file the box masked.
func TestReportLinksNameNoTests(t *testing.T) {
	out := t.TempDir()
	secret := filepath.Join(t.TempDir(), ".git-credentials")
	if err := os.WriteFile(secret, []byte("https://acme:invented@example.invalid\n"), 0o666); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"AK_FAILED", "AK_FLAKY", "AK_RAN"} {
		if err := os.Symlink(secret, filepath.Join(out, name)); err != nil {
			t.Skip(err)
		}
	}
	result := reportedTests(ran{code: 1}, out, nil, io.Discard)
	if result.failed != nil || result.flaky != nil {
		t.Fatalf("a linked report was read: %+v", result)
	}
}

func TestPieceRetryConfirmsNamesOrReturnsToTheWholePiece(t *testing.T) {
	for _, each := range []struct {
		name  string
		alone ran
		whole bool
		flaky []string
	}{
		{"confirmed", ran{code: 1, testReport: testReport{confirmed: []string{"a"}}}, false, nil},
		{"unconfirmed", ran{code: 1}, true, nil},
		{"passed alone", ran{}, true, []string{"a"}},
	} {
		t.Run(each.name, func(t *testing.T) {
			at := &piece{ended: ran{code: 1, testReport: testReport{failed: []string{"a"}}}}
			var calls [][]string
			err := retryTests(at, func(at *piece, _ string, only []string) error {
				calls = append(calls, only)
				flaky := at.ended.flaky // each go keeps the names of those before it, as pieces' attempt does
				at.ended = each.alone
				if only == nil {
					at.ended = ran{code: 1}
				}
				at.ended.flaky = append(flaky, at.ended.flaky...)
				return nil
			})
			want := [][]string{{"a"}}
			if each.whole {
				want = append(want, nil)
			}
			if err != nil || !reflect.DeepEqual(calls, want) || !reflect.DeepEqual(at.ended.flaky, each.flaky) {
				t.Fatalf("retries=%v, flaky=%v, err=%v", calls, at.ended.flaky, err)
			}
		})
	}
}

func TestLocalPieceRedReachesTheLandingFixerAfterItsPrefixLeaves(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	wait := run.Fields("fix", run.Fields("command", "suite", "piece", "1/2", "tests", []any{"a"}))
	if road := landingFixHandoff(wait); road != "" {
		t.Fatal(road)
	}
	wait.Set("after", run.Fields("first", "tree"))
	if road := landingFixHandoff(wait); road != "" {
		t.Fatal("a stack red is Go's fixer's once its prefix leaves: " + road)
	}
	if !redBehind(wait, []member{{dir: filepath.Join(home, "first")}}) || redBehind(wait, nil) {
		t.Fatal("the fix must wait for exactly its prefix's deliveries")
	}
	wait.Delete("after")
	wait.Dict("fix").Set("moved", true)
	if landingFixHandoff(wait) == "" {
		t.Fatal("a moved PR was handed to Go's fixer")
	}
	wait.Dict("fix").Delete("moved")
	if err := os.MkdirAll(filepath.Join(home, ".agentkit"), 0o777); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(home, ".agentkit", "config.toml"), []byte("suite_helper = 'acme'\n"), 0o666); err != nil {
		t.Fatal(err)
	}
	if landingFixHandoff(wait) == "" {
		t.Fatal("helper work was handed to Go's fixer")
	}
}
