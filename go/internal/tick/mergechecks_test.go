//go:build unix

package tick

import (
	"errors"
	"fmt"
	"io"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/run"
)

func TestMergeChecksKeepTheCommitOnceAndHandFailuresOver(t *testing.T) {
	for _, conclusion := range []string{"success", "neutral", "skipped", "cancelled", "failure"} {
		t.Run(conclusion, func(t *testing.T) {
			ak, _ := idleHome(t, fmt.Sprintf(`case "$*" in *mergeCommit*) echo '{"mergeCommit":{"oid":"abc"}}';; *) echo '{"check_runs":[{"status":"completed","conclusion":%q}]}';; esac`, conclusion))
			path := filepath.Join(ak, "runs", "fix-api", "run.json")
			before := fmt.Sprintf(`{"merged":true,"finished_at":%d,"pr":"https://github.com/acme/api/pull/1","health":{}, "unknown": 12345678901234567890}`, time.Now().Unix())
			put(t, path, before)
			tick := &ticking{log: newLog(io.Discard, io.Discard), clock: time.Now}
			err := tick.mergeChecks()
			if conclusion == "failure" {
				if !errors.Is(err, errLeft) || read(t, path) != before {
					t.Fatal("failed checks did not hand over without writing")
				}
				return
			}
			kept, _ := run.ReadJSON(path)
			if err != nil || kept.Str("merge_sha") != "abc" || kept.Get("unknown") != run.Number("12345678901234567890") {
				t.Fatalf("%v: %s", err, run.Line(kept))
			}
			first := read(t, path)
			if tick.mergeChecks() != nil || read(t, path) != first {
				t.Fatal("settled merge was rewritten")
			}
		})
	}
}
