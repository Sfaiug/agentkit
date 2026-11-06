//go:build unix

package tick

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/run"
)

// checking is a tick at its merge checks, on watch.json as it stands, saying what it says into said.
func checking(t *testing.T, said io.Writer) *ticking {
	t.Helper()
	state, ok := loadState()
	if !ok {
		t.Fatal("watch.json unread")
	}
	return &ticking{state: state, log: newLog(said, io.Discard), clock: time.Now}
}

// A merge's commit is kept on its run once, the record otherwise as it stood.
func TestMergeChecksKeepTheCommitOnce(t *testing.T) {
	ak, _ := idleHome(t, `case "$*" in *mergeCommit*) echo '{"mergeCommit":{"oid":"abc"}}';; esac`)
	path := filepath.Join(ak, "runs", "fix-api", "run.json")
	put(t, path, fmt.Sprintf(`{"merged":true,"finished_at":%d,"pr":"https://github.com/acme/api/pull/1","health":{},"deployed":null,"unknown": 12345678901234567890}`, time.Now().Unix()))
	if err := checking(t, io.Discard).mergeChecks(); err != nil {
		t.Fatal(err)
	}
	kept, _ := run.ReadJSON(path)
	if kept.Str("merge_sha") != "abc" || kept.Get("unknown") != run.Number("12345678901234567890") {
		t.Fatalf("kept %s", run.Line(kept))
	}
	first := read(t, path)
	if checking(t, io.Discard).mergeChecks() != nil || read(t, path) != first {
		t.Fatal("a kept commit was written again")
	}
}

// A deployment, a declaration to read at the merge's commit, a probe due and a pass still to tell
// are Python's, left before anything is written.
func TestMergeChecksLeaveWhatGoDoesNotRead(t *testing.T) {
	for name, fields := range map[string]string{
		"deployment":  `"health": {}, "deployed": "true"`,
		"declaration": `"repo": "/srv/acme"`,
		"probe":       `"health": {"command": "true"}, "deployed": null`,
		"untold pass": `"live_at": 1, "health": {}, "deployed": null`,
	} {
		t.Run(name, func(t *testing.T) {
			ak, _ := idleHome(t, answers)
			path := filepath.Join(ak, "runs", "fix-api", "run.json")
			before := fmt.Sprintf(`{"merged": true, "finished_at": %d, "pr": "https://github.com/acme/api/pull/1", "merge_sha": "abc", %s}`, time.Now().Unix(), fields)
			put(t, path, before)
			if err := checking(t, io.Discard).mergeChecks(); !errors.Is(err, errLeft) || read(t, path) != before {
				t.Fatalf("%v: %s", err, read(t, path))
			}
		})
	}
}

// A break found past its window is kept until a seat takes it, its run no longer followed and its
// result opening on the NOT LIVE decision; a later merge going green ends it.  One watch.json
// cannot keep yet waits a tick, its run's failure in place.
func TestABreakIsKeptUntilToldOrGreen(t *testing.T) {
	ak, _ := idleHome(t, answers)
	broke := filepath.Join(ak, "runs", "broke")
	put(t, filepath.Join(broke, "run.json"), fmt.Sprintf(`{"merged": true, "finished_at": %d, "pr": "https://github.com/acme/api/pull/2",
		"merge_sha": "b2", "launched_session": "acme", "health": {"command": "false", "output": "down\n\nstill down"}}`, time.Now().Unix()-4*3600))
	unsaved := filepath.Join(ak, "state", "watch.tmp")
	if err := os.MkdirAll(unsaved, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := checking(t, io.Discard).mergeChecks(); err != nil {
		t.Fatal(err)
	}
	if record, _ := run.Read(broke); !record.Has("health") {
		t.Fatal("a break nothing keeps lost its run's failure")
	}
	if _, err := os.Stat(filepath.Join(broke, "result.md")); err == nil {
		t.Fatal("a break nothing keeps was told")
	}
	if err := os.Remove(unsaved); err != nil {
		t.Fatal(err)
	}
	var said bytes.Buffer
	if err := checking(t, &said).mergeChecks(); err != nil {
		t.Fatal(err)
	}
	told := "health: false failed on main after this merge. https://github.com/acme/api/pull/2; down; still down. Fix the target."
	pending := watched(t, ak)["after_merge"].(map[string]any)["github.com/acme/api"].(map[string]any)["pending"].(map[string]any)
	if pending["line"] != told || pending["session"] != "acme" || pending["run"] != "broke" || pending["sha"] != "b2" {
		t.Fatalf("kept %v", pending)
	}
	if record, _ := run.Read(broke); record.Has("health") {
		t.Error("an expired probe is still followed")
	}
	if result := read(t, filepath.Join(broke, "result.md")); !strings.HasPrefix(result, "# NOT LIVE (0 of 0) — broke\nWhy: "+told) ||
		!strings.HasSuffix(result, "\n## Seat notice\n\n"+told+"\n") {
		t.Errorf("result.md holds %s", result)
	}
	if said.String() != "run broke's after-merge notice waits for a live seat at its prompt\n" {
		t.Errorf("said %q", said.String())
	}
	put(t, filepath.Join(ak, "runs", "green", "run.json"), fmt.Sprintf(`{"merged": true, "finished_at": %d, "pr": "https://github.com/acme/api/pull/3",
		"merge_sha": "g3", "live_at": 1, "live_notified": 1, "health": {}, "deployed": null}`, time.Now().Unix()-60))
	said.Reset()
	tick := checking(t, &said)
	if err := tick.mergeChecks(); err != nil || tick.state.Dict("after_merge").Has("github.com/acme/api") {
		t.Fatalf("%v: %s", err, run.Line(tick.state))
	}
	if said.String() != "run broke's after-merge notice is over: github.com/acme/api went green\n" {
		t.Errorf("said %q", said.String())
	}
}
