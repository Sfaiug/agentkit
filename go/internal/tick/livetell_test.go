//go:build unix

package tick

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/run"
)

const liveLine = "run fix-api is live: https://github.com/acme/api/pull/1."

// liveOwed is run fix-api's record of the seat lead, up at its prompt and owing work: merged, its
// ending read at its look, no other run of the seat going, and its `health:` passing when probed.
func liveOwed(t *testing.T) (path, home string) {
	t.Helper()
	ak, home := forkSeat(t)
	put(t, filepath.Join(ak, "state", "plan-lead.md"), "- [ ] The work is done · check: `false` · lead · written 2026-10-23 09:00\n")
	path = filepath.Join(ak, "runs", "fix-api", "run.json")
	put(t, path, fmt.Sprintf(`{"run_id": "fix-api", "state": "pass", "merged": true, "finished_at": %d, "pr": "https://github.com/acme/api/pull/1",
		"merge_sha": "abc", "repo": "/", "health": {"command": "true"}, "deployed": null, "launched_session": "lead",
		"handed_back": %[1]d, "reported": true, "handback_note": "read by its seat's own ak run status or ak wait: printed there, not typed"}`,
		time.Now().Unix()))
	return path, home
}

// typed is every key the seat was sent.
func typed(home string) string {
	keys, _ := os.ReadFile(filepath.Join(home, "keys"))
	return string(keys)
}

// A seat its merge's going live ends the wait of is typed it alone, once, when a tick finds the
// pass, and the run is marked told: a second tick types nothing.  So is a seat tmux holds without
// ak's mark, which Python finds by its record.
func TestALiveNoticeItsSeatWaitsOnIsTypedAloneOnce(t *testing.T) {
	for _, marked := range []bool{true, false} {
		t.Run(fmt.Sprint("marked ", marked), func(t *testing.T) {
			path, home := liveOwed(t)
			if !marked {
				fake, _ := exec.LookPath("tmux")
				put(t, fake, strings.ReplaceAll(read(t, fake), `lead\t1`, `lead\t`))
			}
			for tick := range 2 {
				var said bytes.Buffer
				if err := checking(t, &said).mergeChecks(); err != nil {
					t.Fatalf("tick %d: %v", tick, err)
				}
				record, _ := run.ReadJSON(path)
				if typed(home) != liveLine+"\nEnter\n" || !record.Truthy("live_at") || !record.Truthy("live_notified") || record.Has("live_typed") {
					t.Fatalf("tick %d typed %q, recording %s", tick, typed(home), run.Line(record))
				}
				if told := strings.Contains(said.String(), "told the lead seat: "+liveLine+"\n"); told != (tick == 0) {
					t.Fatalf("tick %d said %q", tick, said.String())
				}
			}
		})
	}
}

// A live notice for a seat whose harness Go does not type into is Python's, left before its probe
// keeps anything.
func TestALiveNoticeGoDoesNotTypeIsLeftUnwritten(t *testing.T) {
	path, home := liveOwed(t)
	ak := filepath.Join(home, ".agentkit")
	put(t, filepath.Join(ak, "config.toml"), "[audit]\non = false\n[models.opus]\nharness = 'acme'\nmodel = 'vela'\n"+
		"effort = 'high'\nprovider = 'test'\n[providers.test]\nmode = 'subscription'\n")
	older(t, "PRAGMA user_version")
	before, schema := read(t, path), tables(t)
	if err := checking(t, io.Discard).mergeChecks(); !errors.Is(err, errLeft) || read(t, path) != before || tables(t) != schema || typed(home) != "" {
		t.Fatalf("%v, typing %q: %s", err, typed(home), read(t, path))
	}
}

// A live notice whose receipt cannot be kept gets no Enter: its line stays in the composer, and
// no later tick types a second copy past it.
func TestALiveNoticeWithoutItsReceiptIsNotSent(t *testing.T) {
	path, home := liveOwed(t)
	jam := filepath.Join(filepath.Dir(path), "delivery.tmp")
	if err := os.Mkdir(jam, 0o700); err != nil {
		t.Fatal(err)
	}
	for tick := range 2 {
		var said bytes.Buffer
		if err := checking(t, &said).mergeChecks(); err != nil {
			t.Fatalf("tick %d: %v", tick, err)
		}
		if record, _ := run.ReadJSON(path); typed(home) != liveLine+"\n" || record.Has("live_notified") || strings.Contains(said.String(), "told") {
			t.Fatalf("tick %d typed %q, saying %q: %s", tick, typed(home), said.String(), run.Line(record))
		}
		if err := os.Remove(jam); err != nil && tick == 0 {
			t.Fatal(err)
		}
	}
}
