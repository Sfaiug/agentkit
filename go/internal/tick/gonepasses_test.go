//go:build unix

package tick

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
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

func TestGoneSeatsHandExpiredRecordsBackAtTheSweepRow(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	for _, each := range []struct {
		name            string
		seen, stopped   int
		asleep, carried bool
	}{
		{"expired crash", 8, 0, false, false},
		{"expired close", 8, 8, false, false},
		{"recent sighting", 6, 0, false, true},
		{"recent close", 8, 1, false, true},
		{"asleep", 8, 0, true, true},
	} {
		t.Run(each.name, func(t *testing.T) {
			ak, path := goneHome(t)
			record, _ := run.ReadJSON(path)
			seen := run.Float(float64(now.AddDate(0, 0, -each.seen).Unix()))
			record.Set("seen", seen)
			if each.asleep {
				record.Set("asleep", run.Float(2))
			}
			put(t, path, run.Line(record))
			if each.stopped > 0 {
				put(t, filepath.Join(ak, "state", "seat-acme.json"), fmt.Sprintf(`{"closed_by_owner":true,"stopped_at":%d}`, now.AddDate(0, 0, -each.stopped).Unix()))
			}
			state, ok := loadState()
			if !ok {
				t.Fatal("state unread")
			}
			var out, errOut bytes.Buffer
			tick := &ticking{state: state, log: newLog(&out, &errOut), clock: func() time.Time { return now }}
			if carried := tick.through(table(tick)); carried != each.carried {
				t.Fatalf("carried=%v: %s %s", carried, &out, &errOut)
			}
			record, _ = run.ReadJSON(path)
			if record == nil || !run.Equal(record.Get("seen"), seen) {
				t.Fatalf("the retention clock changed: %s", run.Line(record))
			}
			if _, err := os.Stat(filepath.Join(ak, "state", "card-acme.json")); err != nil {
				t.Fatalf("the tick stopped before the sweep row: %v", err)
			}
		})
	}
}
