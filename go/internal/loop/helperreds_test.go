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

// Of four pieces red on the helper, each naming its test, the first passes alone, the second fails
// again alone and settles the suite, and the fourth named none: only the first then runs whole.
func TestOneHelperRedConfirmedSettlesTheSuiteAndTheRestKeepWhatTheyPrintedThere(t *testing.T) {
	dir := t.TempDir()
	l := &loop{dir: dir, voice: io.Discard}
	there := &helper.Away{Alias: "acme-mac"}
	var all []*piece
	for k, test := range []string{"a.sh", "b.sh", "c.sh", ""} {
		out, err := os.CreateTemp(dir, "piece-*.log")
		if err != nil {
			t.Fatal(err)
		}
		defer out.Close()
		out.WriteString("FAIL there\n")
		at := &piece{shard: string(rune('1'+k)) + "/4", out: out, there: there, ended: ran{code: 1}}
		if test != "" {
			at.ended.failed = []string{test}
		}
		all = append(all, at)
	}
	var runs []string
	rerun := func(at *piece, _ string, only []string) error {
		runs = append(runs, at.shard+" "+map[bool]string{true: "alone", false: "whole"}[only != nil])
		at.ended = ran{}
		if at.shard == "2/4" && only != nil {
			at.ended = ran{code: 1, testReport: testReport{confirmed: only}}
		}
		return nil
	}
	if err := l.helperReds(context.Background(), all, filepath.Join(dir, "lander.log"), rerun); err != nil {
		t.Fatal(err)
	}
	if want := []string{"1/4 alone", "2/4 alone", "1/4 whole"}; !reflect.DeepEqual(runs, want) {
		t.Fatalf("runs %v, want %v", runs, want)
	}
	if all[2].there == nil || all[2].ended.code != 1 || string(all[2].failed) != "FAIL there\n" {
		t.Fatalf("a settled piece lost what it printed there: %+v", all[2])
	}
	if all[3].failed != nil || all[3].there == nil {
		t.Fatalf("a piece that named no tests is the suite's to run whole: %+v", all[3])
	}
	if all[0].how != "failed on the suite helper acme-mac" || string(all[0].failed) != "FAIL there\n" || all[0].ended.code != 0 {
		t.Fatalf("a piece passing whole here is a flake of the helper: %+v", all[0])
	}
}
