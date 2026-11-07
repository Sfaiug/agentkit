//go:build unix

package tick

import (
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/run"
)

func waiter(t *testing.T) (string, *run.Object, *ticking) {
	t.Helper()
	ak, _ := idleHome(t, answers)
	put(t, filepath.Join(ak, "state", "session-acme.json"), `{}`)
	dir := filepath.Join(ak, "runs", "fix-api")
	put(t, filepath.Join(dir, "log.txt"), "WARN not merged: the rebase of origin/main conflicted\n")
	git := filepath.Join(t.TempDir(), "git")
	put(t, git, "#!/bin/sh\ncase \" $* \" in *' --git-common-dir '*) printf '%s\\n' \"$REF_DIRECTORY\";; *' fetch '*) exit \"${FETCH_CODE:-0}\";; *' rev-parse '*) printf '%s\\n' \"$REF_ANSWER\"; exit \"${REF_CODE:-0}\";; esac\n")
	if err := os.Chmod(git, 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", filepath.Dir(git)+string(os.PathListSeparator)+os.Getenv("PATH"))
	t.Setenv("REF_ANSWER", strings.Repeat("a", 40))
	t.Setenv("REF_DIRECTORY", t.TempDir())
	record := run.Fields("state", "fail", "run_id", "fix-api", "repo", t.TempDir(), "worktree", t.TempDir(),
		"branch", "ak/fix-api", "base", "main", "base_sha", "base", "rounds", 3, "round_summaries", []any{run.Fields("round", 1)},
		"merge_note", "the rebase of origin/main conflicted", "launched_session", "acme", "finished_at", epoch(time.Now()),
		"handback_pending", true, "handback_wait_reason", "busy", "recovery_pending", true)
	return dir, record, &ticking{log: newLog(io.Discard, io.Discard), clock: time.Now}
}

func TestWaitingReadsAtItsTurnThenStandsStillByteForByte(t *testing.T) {
	dir, record, tick := waiter(t)
	if !tick.through([]pass{
		{"before", false, nil, func() error { return run.Create(dir, record) }},
		{"waiting resume", true, nil, tick.waiting},
	}) {
		t.Fatal("did not carry the new wait at its own row")
	}
	after, _ := run.Read(dir)
	if after.Str("state") != "waiting" || after.Str("error") != record.Str("merge_note") ||
		after.Dict("waiting_on").Str("sha") != strings.Repeat("a", 40) || after.Has("handback_pending") || after.Has("recovery_pending") ||
		!run.Equal(after.Get("round_summaries"), record.Get("round_summaries")) {
		t.Fatal(run.Line(after))
	}
	before := read(t, filepath.Join(dir, "run.json"))
	if err := tick.waiting(); err != nil || before != read(t, filepath.Join(dir, "run.json")) {
		t.Fatalf("unchanged upstream rewrote its wait: %v", err)
	}
}

func TestWaitingDoesNotInventAMoveOrTakeAnUnadmittedEnding(t *testing.T) {
	for _, scenario := range []string{"fetch failed", "ref failed", "ref unresolved", "spent", "told", "old", "job", "no integration log", "dry", "dry wait"} {
		t.Run(scenario, func(t *testing.T) {
			dir, record, tick := waiter(t)
			switch scenario {
			case "fetch failed":
				t.Setenv("FETCH_CODE", "1")
			case "ref failed":
				t.Setenv("REF_CODE", "1")
			case "ref unresolved":
				t.Setenv("REF_ANSWER", "origin/main^{commit}")
			case "spent":
				record.Set("rounds", 1)
			case "told":
				record.Set("handed_back", true)
			case "old":
				record.Set("finished_at", epoch(time.Now().Add(-25*time.Hour)))
			case "job":
				record.Set("job_id", "batch")
			case "no integration log":
				put(t, filepath.Join(dir, "log.txt"), "review failed\n")
			case "dry", "dry wait":
				// a fetch that ran would fail the row's fetch-free promise
				t.Setenv("FETCH_CODE", "1")
				tick.dry = true
				var said strings.Builder
				tick.log = newLog(&said, io.Discard)
				defer func() {
					want := map[string]string{"dry": "would park fix-api waiting on origin/main",
						"dry wait": "would resume fix-api after the next merge to origin/main"}[scenario]
					if !strings.HasSuffix(said.String(), want+"\n") {
						t.Fatalf("a dry tick said %q", said.String())
					}
				}()
			}
			if scenario == "dry wait" {
				record.Set("state", "waiting")
				record.Set("waiting_on", run.Fields("ref", "origin/main", "sha", "base"))
			}
			if err := run.Create(dir, record); err != nil {
				t.Fatal(err)
			}
			before := read(t, filepath.Join(dir, "run.json"))
			if err := tick.waiting(); err != nil {
				t.Fatal(err)
			}
			if after := read(t, filepath.Join(dir, "run.json")); after != before {
				t.Fatal("row rewrote the ending")
			}
		})
	}
}

func TestWaitingDoesNotOverwriteAStopDuringItsFetch(t *testing.T) {
	dir, record, tick := waiter(t)
	if err := run.Create(dir, record); err != nil {
		t.Fatal(err)
	}
	git := filepath.Join(strings.Split(os.Getenv("PATH"), string(os.PathListSeparator))[0], "git")
	put(t, git, "#!/bin/sh\ncase \" $* \" in *' --git-common-dir '*) printf '%s\\n' \"$REF_DIRECTORY\";; *' fetch '*) printf '%s' '{\"state\":\"stopped\"}' >\"$STOP_RECORD\";; *) printf '%s\\n' \"$REF_ANSWER\";; esac\n")
	os.Chmod(git, 0o700)
	t.Setenv("STOP_RECORD", filepath.Join(dir, "run.json"))
	if err := tick.waiting(); err != nil || read(t, filepath.Join(dir, "run.json")) != `{"state":"stopped"}` {
		t.Fatalf("stop lost: %v", err)
	}
}
