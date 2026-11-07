package loop

import (
	"context"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"agentkit/internal/helper"
)

// Of five pieces red on the helper, the first passes alone, the second is killed for memory alone,
// the third fails again alone and settles the suite, the fourth keeps what it printed there, and
// the fifth named no test: the first two then run whole, and passing, their tests failed, then passed;
// the fifth keeps what it printed there for the suite to run it whole.
func TestOneHelperRedConfirmedSettlesTheSuiteAndTheRestKeepWhatTheyPrintedThere(t *testing.T) {
	dir := t.TempDir()
	l := &loop{dir: dir, voice: io.Discard}
	there := &helper.Away{Alias: "acme-mac"}
	var all []*piece
	for k, test := range []string{"a.sh", "s.sh", "b.sh", "c.sh", ""} {
		out, err := os.CreateTemp(dir, "piece-*.log")
		if err != nil {
			t.Fatal(err)
		}
		defer out.Close()
		out.WriteString("FAIL there\n")
		at := &piece{shard: string(rune('1'+k)) + "/5", out: out, there: there, ended: ran{code: 1}}
		if test != "" {
			at.ended.failed = []string{test}
		}
		all = append(all, at)
	}
	var runs []string
	rerun := func(at *piece, _ string, only []string) error {
		runs = append(runs, at.shard+" "+map[bool]string{true: "alone", false: "whole"}[only != nil])
		at.ended = ran{testReport: testReport{flaky: at.ended.flaky}} // each go keeps the names before it
		if only != nil && at.shard == "2/5" {
			at.ended.code, at.ended.starved = 137, true
		}
		if only != nil && at.shard == "3/5" {
			at.ended = ran{code: 1, testReport: testReport{confirmed: only}}
		}
		return nil
	}
	if err := l.helperReds(context.Background(), all, filepath.Join(dir, "lander.log"), rerun); err != nil {
		t.Fatal(err)
	}
	if want := []string{"1/5 alone", "2/5 alone", "3/5 alone", "1/5 whole", "2/5 whole"}; !reflect.DeepEqual(runs, want) {
		t.Fatalf("runs %v, want %v", runs, want)
	}
	if all[3].there != nil || all[3].ended.code != 1 || string(all[3].failed) != "FAIL there\n" {
		t.Fatalf("a settled piece lost what it printed there: %+v", all[3])
	}
	if all[4].how != "failed on the suite helper acme-mac" || string(all[4].failed) != "FAIL there\n" || all[4].there == nil {
		t.Fatalf("a piece that named no tests is the suite's to run whole, a pass a flake of the helper: %+v", all[4])
	}
	if all[0].how != "failed on the suite helper acme-mac" || string(all[0].failed) != "FAIL there\n" || all[0].ended.code != 0 {
		t.Fatalf("a piece passing whole here is a flake of the helper: %+v", all[0])
	}
	for k, test := range []string{"a.sh", "s.sh"} {
		if !reflect.DeepEqual(all[k].ended.flaky, []string{test}) {
			t.Fatalf("%s failed there, then passed here, yet the piece names %v", test, all[k].ended.flaky)
		}
	}
}
