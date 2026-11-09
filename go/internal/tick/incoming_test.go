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
)

func TestIncomingReviewsOnlyOthersOpenPRsOnOwnedCheckouts(t *testing.T) {
	for name, each := range map[string]struct {
		search, detail string
		launched       int
	}{
		"none": {`{"items":[]}`, `{}`, 0},
		"open": {`{"items":[{"number":1,"pull_request":{"html_url":"https://github.com/acme/api/pull/1"}}]}`,
			`{"state":"open","html_url":"https://github.com/acme/api/pull/1","head":{"sha":"abc"},"user":{"login":"other"}}`, 1},
		"closed since search": {`{"items":[{"number":1,"pull_request":{"html_url":"https://github.com/acme/api/pull/1"}}]}`, `{"state":"closed"}`, 0},
		"draft":               {`{"items":[{"number":1,"draft":true,"pull_request":{"html_url":"https://github.com/acme/api/pull/1"}}]}`, `{}`, 0},
		"own":                 {`{"items":[{"number":1,"user":{"login":"ACME"},"pull_request":{"html_url":"https://github.com/acme/api/pull/1"}}]}`, `{}`, 0},
		"elsewhere":           {`{"items":[{"number":1,"pull_request":{"html_url":"https://github.com/other/api/pull/1"}}]}`, `{}`, 0},
	} {
		t.Run(name, func(t *testing.T) {
			ak, checkout := checkoutHome(t, "# acme\n")
			if err := exec.Command("git", "-C", checkout, "remote", "set-url", "origin", "git@github.com:acme/api.git").Run(); err != nil {
				t.Fatal(err)
			}
			bin := strings.Split(os.Getenv("PATH"), string(os.PathListSeparator))[0]
			put(t, filepath.Join(bin, "gh"), fmt.Sprintf("#!/bin/sh\ncase \"$*\" in *repos/acme/api/pulls/1*) echo '%s';; *) echo '%s';; esac\n", each.detail, each.search))
			before := files(t, ak)
			state, _ := loadState()
			tick := &ticking{state: state, log: newLog(io.Discard, io.Discard), clock: time.Now}
			if !tick.incoming("acme") || len(launches(t)) != each.launched {
				t.Fatalf("launched %v", launches(t))
			}
			for path, want := range before {
				if want != "" && read(t, path) != want {
					t.Fatalf("incoming rewrote %s", path)
				}
			}
		})
	}
}

// A dry incoming pass decides each head as the real one does, on the same answers: it says which
// head it would review and starts none, and where gh's word on a head's reviews cannot be read as
// Python reads it, it hands the review over to Python as the real one does.
func TestDryIncomingPreservesRealReviewHandover(t *testing.T) {
	const url = "https://github.com/acme/api/pull/1"
	what := url + " (#1 by beta: Fix parser) at abc"
	for name, each := range map[string]struct {
		reviews       string
		owed, carried bool
	}{
		"new head":   {`echo '{"reviews": []}'`, true, true},
		"reviewed":   {`echo '{"reviews": [{"author": {"login": "acme"}, "body": "agentkit review of abc", "commit": {"oid": "abc"}}]}'`, false, true},
		"unreadable": {`printf '\377'`, false, false},
	} {
		t.Run(name, func(t *testing.T) {
			_, checkout := checkoutHome(t, "# acme\n")
			if err := exec.Command("git", "-C", checkout, "remote", "set-url", "origin", "git@github.com:acme/api.git").Run(); err != nil {
				t.Fatal(err)
			}
			bin := strings.Split(os.Getenv("PATH"), string(os.PathListSeparator))[0]
			put(t, filepath.Join(bin, "gh"), fmt.Sprintf("#!/bin/sh\ncase \"$*\" in\n\"pr view %s --json reviews\") %s;;\n"+
				"*repos/acme/api/pulls/1*) echo '{\"state\":\"open\",\"number\":1,\"title\":\"Fix parser\",\"html_url\":\"%s\",\"head\":{\"sha\":\"abc\"},\"user\":{\"login\":\"beta\"}}';;\n"+
				"*) echo '{\"items\":[{\"number\":1,\"pull_request\":{\"html_url\":\"%s\"}}]}';;\nesac\n", url, each.reviews, url, url))
			for _, dry := range []bool{true, false} {
				want, started := "", 0
				if each.owed && dry {
					want = "would review " + what + "\n"
				} else if each.owed {
					want, started = "review "+what+" -> review\n", 1
				}
				state, _ := loadState()
				var said strings.Builder
				tick := &ticking{state: state, log: newLog(&said, io.Discard), clock: time.Now, dry: dry}
				if tick.incoming("acme") != each.carried || said.String() != want || len(launches(t)) != started {
					t.Fatalf("dry %v: carried %v, saying %q, starting %v", dry, !each.carried, said.String(), launches(t))
				}
			}
		})
	}
}
