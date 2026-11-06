//go:build unix

package tick

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/run"
)

func TestGoneSeatsHandUntoldWaitsBackAtTheEndedWaitsRow(t *testing.T) {
	for kind, on := range map[string]string{"pr": "https://github.com/acme/api/pull/1", "run": "r-build"} {
		for _, told := range []bool{false, true} {
			t.Run(fmt.Sprintf("%s/told=%v", kind, told), func(t *testing.T) {
				ak, _ := goneHome(t)
				path := filepath.Join(ak, "state", "seat-acme.json")
				put(t, path, fmt.Sprintf(`{"wait":{"kind":%q,"on":%q,"at":1,"over":"the work finished","told":%v}}`, kind, on, told))
				before, _ := run.ReadJSON(path)
				var out, errOut bytes.Buffer
				if carried := Carry(&out, &errOut); carried != told {
					t.Fatalf("carried=%v: %s %s", carried, &out, &errOut)
				}
				file, _ := run.ReadJSON(path)
				if file.Str("word") != "idle" || !run.Equal(file.Get("wait"), before.Get("wait")) {
					t.Fatal(run.Line(file))
				}
				if !told {
					if _, err := os.Stat(filepath.Join(ak, "state", "card-acme.json")); !os.IsNotExist(err) {
						t.Fatalf("the tick passed the ended waits row: %v", err)
					}
				}
			})
		}
	}
}

func TestTheSweepRowForgetsAGoneSeatAWeekAfterItWent(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	for _, each := range []struct {
		name           string
		seen, stopped  int
		asleep, forgot bool
	}{
		{"expired crash", 8, 0, false, true},
		{"expired close", 30, 8, false, true},
		{"recent sighting", 6, 0, false, false},
		{"recent close", 30, 1, false, false},
		{"asleep", 8, 0, true, false},
	} {
		t.Run(each.name, func(t *testing.T) {
			ak, path := goneHome(t)
			// tmux's own word that no seat is there, as one with no server running says it
			bin := strings.Split(os.Getenv("PATH"), string(os.PathListSeparator))[0]
			put(t, filepath.Join(bin, "tmux"), "#!/bin/sh\necho 'no server running on /tmp/tmux-1/agentkit' >&2\nexit 1\n")
			record, _ := run.ReadJSON(path)
			seen := run.Float(float64(now.AddDate(0, 0, -each.seen).Unix()))
			record.Set("seen", seen)
			if each.asleep {
				record.Set("asleep", run.Float(2))
			}
			put(t, path, run.Line(record))
			mark := filepath.Join(ak, "state", "seat-acme.json")
			if each.stopped > 0 {
				put(t, mark, fmt.Sprintf(`{"closed_by_owner":true,"stopped_at":%d}`, now.AddDate(0, 0, -each.stopped).Unix()))
			}
			state, ok := loadState()
			if !ok {
				t.Fatal("state unread")
			}
			var out, errOut bytes.Buffer
			tick := &ticking{state: state, log: newLog(&out, &errOut), clock: func() time.Time { return now }}
			if !tick.through(table(tick)) {
				t.Fatalf("left to Python: %s %s", &out, &errOut)
			}
			record, _ = run.ReadJSON(path)
			if each.forgot != (record == nil) || !each.forgot && !run.Equal(record.Get("seen"), seen) {
				t.Fatalf("the record: %s", run.Line(record))
			}
			if each.forgot != strings.Contains(out.String(), "forgot the session acme, gone for 8d\n") {
				t.Fatal(out.String())
			}
			if file, _ := run.ReadJSON(mark); each.forgot && (each.stopped > 0) != (file != nil && file.Truthy("closed_by_owner")) {
				t.Fatalf("the stop mark: %s", run.Line(file))
			}
		})
	}
}
