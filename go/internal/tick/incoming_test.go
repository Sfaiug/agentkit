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
