//go:build unix

package tick

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/run"
	"agentkit/internal/seat"
)

func TestRevivalBackoffKeepsPythonRecoveryBoundaries(t *testing.T) {
	for _, each := range []struct {
		name    string
		death   int
		carried bool
	}{
		{"warmup", 5, true}, {"warmup ended", 10, false}, {"late death", 15, false}, {"antigravity", 0, false},
	} {
		t.Run(each.name, func(t *testing.T) {
			ak := revivalHome(t)
			now := time.Unix(1_800_000_000, 0)
			path := filepath.Join(ak, "state", "session-acme.json")
			record, _ := run.ReadJSON(path)
			record.Set("launched", run.Float(epoch(now)-180))
			if each.name == "antigravity" {
				config := filepath.Join(ak, "config.toml")
				put(t, config, read(t, config)+"[models.gemini]\nharness='antigravity'\nmodel='gemini-flash'\neffort='low'\nprovider='test'\n")
				record.Set("orchestrator", "gemini")
				record.Set("workers", []any{"gemini"})
			} else {
				bin := strings.Split(os.Getenv("PATH"), string(os.PathListSeparator))[0]
				put(t, filepath.Join(bin, "tmux"), fmt.Sprintf(`#!/bin/sh
case "$*" in '-L tick-test '*) ;; *) exit 1 ;; esac
case "$*" in
  *list-sessions*|*list-panes*) printf 'acme\t1\n' ;;
  *show-options*) echo %%1 ;;
  *'#{pane_dead_time}'*) echo %d ;;
  *'#{session_name}'*) echo acme ;;
esac
`, now.Unix()-180+int64(each.death)))
			}
			put(t, path, run.Line(record))
			file := run.Line(run.Fields("state", "at_prompt", "rule", "prompt.composer",
				"reopened_at", []any{run.Float(epoch(now) - 180)}))
			seatPath := filepath.Join(ak, "state", "seat-acme.json")
			put(t, seatPath, file)
			if home, known := seat.Looking(now); !known || len(home.Seats) != 1 {
				t.Fatal("seat was not readable")
			}
			tick := &ticking{log: newLog(io.Discard, io.Discard), clock: func() time.Time { return now }}
			for _, row := range table(tick) {
				if row.name == "seat revival" {
					if got := tick.through([]pass{row}); got != each.carried || read(t, seatPath) != file {
						t.Fatalf("carried=%v, want %v; seat=%s", got, each.carried, read(t, seatPath))
					}
					return
				}
			}
			t.Fatal("revival row missing")
		})
	}
}
