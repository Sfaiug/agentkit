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

func TestPieceRetryConfirmsNamesOrReturnsToTheWholePiece(t *testing.T) {
	for _, each := range []struct {
		name  string
		alone ran
		whole bool
		flaky bool
	}{
		{"confirmed", ran{code: 1, testReport: testReport{confirmed: []string{"a"}}}, false, false},
		{"unconfirmed", ran{code: 1}, true, false},
		{"passed alone", ran{}, true, true},
	} {
		t.Run(each.name, func(t *testing.T) {
			at := &piece{ended: ran{code: 1, testReport: testReport{failed: []string{"a"}}}}
			var calls [][]string
			err := retryTests(at, func(at *piece, _ string, only []string) error {
				calls = append(calls, only)
				at.ended = each.alone
				if only == nil {
					at.ended = ran{code: 1}
				}
				return nil
			})
			want := [][]string{{"a"}}
			if each.whole {
				want = append(want, nil)
			}
			if err != nil || !reflect.DeepEqual(calls, want) || at.ended.flaky != each.flaky {
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
