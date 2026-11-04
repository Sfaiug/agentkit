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
	for _, file := range []string{`{"state":"working"}`, `{"holds":["background work"]}`, `{"reopened_at":[1]}`} {
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
