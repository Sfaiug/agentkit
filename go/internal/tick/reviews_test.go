//go:build unix

package tick

import (
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

// TestMain answers this test program started as `ak run`, as the tick starts its own program for
// a review: each start's words kept in $HOME/launches, and run `review` printed as `--bg` prints it.
func TestMain(m *testing.M) {
	if len(os.Args) > 1 && os.Args[1] == "run" {
		kept, err := os.OpenFile(filepath.Join(os.Getenv("HOME"), "launches"), os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0o600)
		if err == nil {
			fmt.Fprintln(kept, strings.Join(os.Args[1:], " "))
			kept.Close()
		}
		fmt.Printf("review\n%s\n", filepath.Join(os.Getenv("HOME"), ".agentkit", "runs", "review", "result.md"))
		os.Exit(0)
	}
	os.Exit(m.Run())
}

// launches is each review the tick started.
func launches(t *testing.T) []string {
	data, err := os.ReadFile(filepath.Join(os.Getenv("HOME"), "launches"))
	if err != nil && !os.IsNotExist(err) {
		t.Fatal(err)
	}
	return strings.Fields(strings.ReplaceAll(string(data), " ", "_"))
}

// A head is reviewed once. A review that never reached GitHub is started again only once its wait
// is over, longer each time, and one GitHub holds settles a head whose note was lost.
func TestAHeadIsReviewedOnceAndTriedAgainLaterEachTime(t *testing.T) {
	ak, checkout := checkoutHome(t, "# acme\n")
	if err := exec.Command("git", "-C", checkout, "remote", "set-url", "origin", "git@github.com:acme/api.git").Run(); err != nil {
		t.Fatal(err)
	}
	url, reviews := "https://github.com/acme/api/pull/1", filepath.Join(t.TempDir(), "reviews.json")
	put(t, reviews, `{"reviews": []}`)
	bin := strings.Split(os.Getenv("PATH"), string(os.PathListSeparator))[0]
	put(t, filepath.Join(bin, "gh"), fmt.Sprintf("#!/bin/sh\ncase \"$*\" in\n\"pr view %s --json reviews\") cat %s;;\n"+
		"*repos/acme/api/pulls/1*) echo '{\"state\":\"open\",\"number\":1,\"html_url\":\"%s\",\"head\":{\"sha\":\"abc\"},\"user\":{\"login\":\"beta\"}}';;\n"+
		"*) echo '{\"items\":[{\"number\":1,\"pull_request\":{\"html_url\":\"%s\"}}]}';;\nesac\n", url, reviews, url, url))
	state, _ := loadState()
	now := time.Unix(1_800_000_000, 0)
	tick := &ticking{state: state, log: newLog(io.Discard, io.Discard), clock: func() time.Time { return now }}
	pass := func(started int) *run.Object {
		t.Helper()
		if !tick.incoming("acme") || len(launches(t)) != started {
			t.Fatalf("started %v, not %d", launches(t), started)
		}
		return state.Dict("reviewed").Dict(url)
	}
	if note := pass(1); note.Str("sha") != "abc" || note.Str("run") != "review" || run.Text(note.Get("attempts")) != "1" {
		t.Fatalf("noted %s", run.Line(note))
	}
	for tried, wait := range []float64{600, 1800, 3600, 3600} {
		// the run ended without its review on GitHub: absent, then failed to post
		if tried > 0 {
			put(t, filepath.Join(ak, "runs", "review", "run.json"), `{"state": "fail", "review_posted": false, "head_sha": "abc"}`)
		}
		if at, _ := pass(tried + 1).Num("retry_at"); at != epoch(now)+wait {
			t.Fatalf("try %d waits until %v", tried+2, at)
		}
		now = now.Add(time.Duration(wait) * time.Second)
		if note := pass(tried + 2); run.Text(note.Get("attempts")) != fmt.Sprint(tried+2) {
			t.Fatalf("noted %s", run.Line(note))
		}
	}
	put(t, filepath.Join(ak, "runs", "review", "run.json"), `{"state": "pass", "review_posted": true, "head_sha": "abc"}`)
	pass(5)
	state.Dict("reviewed").Delete(url)
	put(t, reviews, `{"reviews": [{"author": {"login": "acme"}, "body": "agentkit review of abc: PASS", "commit": {"oid": "abc"}}]}`)
	if note := pass(5); note.Get("run") != nil || note.Str("sha") != "abc" {
		t.Fatalf("noted %s", run.Line(note))
	}
}
