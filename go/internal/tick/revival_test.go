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
)

func TestRevivalFilesProjectlessSeatsBeforeHandingOverTheirOtherWork(t *testing.T) {
	ak, recordPath := goneHome(t)
	project := filepath.Join(os.Getenv("HOME"), "code", "acme")
	if err := os.MkdirAll(filepath.Join(project, ".git"), 0o700); err != nil {
		t.Fatal(err)
	}
	put(t, filepath.Join(ak, "state", "seat-acme.json"), `{"state":"working"}`)
	path := filepath.Join(ak, "runs", "r-build", "run.json")
	record := run.Line(run.Fields("run_id", "r-build", "state", "pass", "merged", true,
		"handed_back", true, "repo", project, "project", project, "launched_session", "acme"))
	tick := &ticking{log: newLog(io.Discard, io.Discard), clock: time.Now}
	var revival pass
	for _, row := range table(tick) {
		if row.name == "seat revival" {
			revival = row
		}
	}
	after := false
	if tick.through([]pass{
		{"before", false, nil, func() error { put(t, path, record); return nil }}, revival,
		{"after", false, nil, func() error { after = true; return nil }},
	}) || after {
		t.Fatal("the seat's interrupted work was not handed to Python")
	}
	filed, _ := run.ReadJSON(recordPath)
	if filed.Str("repo") != project || read(t, path) != record {
		t.Fatal("revival did not keep the run's project filing before handing over")
	}
}

func TestADeadPaneWithOtherWorkReachesRevivalAfterTheEarlierRows(t *testing.T) {
	ak, _ := goneHome(t)
	bin := strings.Split(os.Getenv("PATH"), string(os.PathListSeparator))[0]
	put(t, filepath.Join(bin, "tmux"), `#!/bin/sh
case "$*" in '-L tick-test '*) ;; *) exit 1 ;; esac
case "$*" in
  *list-sessions*|*list-panes*) printf 'acme\t1\n' ;;
esac
`)
	repo, err := filepath.Abs("../../..")
	if err != nil {
		t.Fatal(err)
	}
	put(t, filepath.Join(bin, "git"), fmt.Sprintf("#!/bin/sh\nprintf '%%s\\n' %q\n", repo))
	if err := os.Chmod(filepath.Join(bin, "git"), 0o700); err != nil {
		t.Fatal(err)
	}
	put(t, filepath.Join(ak, "state", "seat-acme.json"), `{"state":"working"}`)
	state, known := loadState()
	if !known {
		t.Fatal("watch state not readable")
	}
	tick := &ticking{state: state, log: newLog(io.Discard, io.Discard), clock: time.Now}
	rows, reached := table(tick), false
	for at, row := range rows {
		if row.name == "seat revival" {
			rows[at].step = func() error { reached = true; return row.step() }
		}
	}
	if tick.through(rows) || !reached {
		t.Fatal("a dead pane's recovery was decided before its row")
	}
}

func TestUnportedGoneSeatWorkHandsOverAtTheRevivalRow(t *testing.T) {
	for _, file := range []string{`{"state":"working"}`, `{"holds":["background work"]}`} {
		t.Run(file, func(t *testing.T) {
			ak, _ := goneHome(t)
			path := filepath.Join(ak, "state", "seat-acme.json")
			tick := &ticking{log: newLog(io.Discard, io.Discard), clock: time.Now}
			var revival pass
			for _, row := range table(tick) {
				if row.name == "seat revival" {
					revival = row
				}
			}
			after := false
			if tick.through([]pass{
				{"before", false, nil, func() error { put(t, path, file); return nil }}, revival,
				{"after", false, nil, func() error { after = true; return nil }},
			}) || after || read(t, path) != file {
				t.Fatal("the revival row failed to read the new work, or changed it before handing over")
			}
		})
	}
}

func revivalHome(t *testing.T) string {
	t.Helper()
	ak, path := goneHome(t)
	cwd := filepath.Join(os.Getenv("HOME"), "work", "acme")
	if err := os.MkdirAll(cwd, 0o700); err != nil {
		t.Fatal(err)
	}
	record, _ := run.ReadJSON(path)
	record.Set("cwd", cwd)
	put(t, path, run.Line(record))
	put(t, filepath.Join(ak, "runs", "r-build", "run.json"), `{"state":"running","run_id":"r-build","launched_session":"acme"}`)
	t.Setenv("AGENTKIT_ADAPTER_DIR", t.TempDir())
	t.Setenv("AGENTKIT_DISCORD_USER_ID", "")
	t.Setenv("AK_NOTIFY_SINK_LOG", filepath.Join(t.TempDir(), "pages"))
	return ak
}

func revivalAt(t *testing.T, now time.Time) {
	t.Helper()
	tick := &ticking{state: run.NewObject(), log: newLog(io.Discard, io.Discard), clock: func() time.Time { return now }}
	for _, row := range table(tick) {
		if row.name == "seat revival" {
			if row.idle != nil && !row.idle() {
				t.Fatal("revival row refused its reads")
			}
			if err := row.step(); err != nil {
				t.Fatal(err)
			}
			return
		}
	}
	t.Fatal("revival row missing")
}

func TestAPendingContinuationDoesNotBlockClaimingTheNextDeath(t *testing.T) {
	ak := revivalHome(t)
	path := filepath.Join(ak, "state", "seat-acme.json")
	owed := []any{run.Fields("id", "old-death", "line", "continue: your run r-build is still going")}
	put(t, path, run.Line(run.Fields("state", "at_prompt", "rule", "none", "owed_lines", owed)))
	revivalAt(t, time.Now())
	file, _ := run.ReadJSON(path)
	if len(file.List("reopened_at")) != 1 || !run.Equal(file.Get("owed_lines"), owed) {
		t.Fatalf("next death was not claimed with its continuation intact: %s", run.Line(file))
	}
}

func TestAPagedFailureStaysHandledPastTheRevivalBackoff(t *testing.T) {
	ak := revivalHome(t)
	death := time.Unix(1_800_000_000, 0)
	path := filepath.Join(ak, "state", "seat-acme.json")
	file := run.Fields("reopened_at", []any{run.Float(epoch(death))})
	noticePath := filepath.Join(ak, "state", "notify-acme.json")
	notice := run.Fields("session", "acme", "kind", "needs", "text", "the seat could not reopen",
		"source", "revive:acme:r-build:1000", "watcher", true, "time", run.Float(epoch(death)))
	put(t, path, run.Line(file))
	put(t, noticePath, run.Line(notice))
	for _, age := range []time.Duration{601 * time.Second, 24 * time.Hour} {
		revivalAt(t, death.Add(age))
		if read(t, path) != run.Line(file) || read(t, noticePath) != run.Line(notice) {
			t.Fatal("a handled death was attempted or paged again")
		}
	}
}
