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
)

func TestIncomingReviewsOnlyOthersOpenPRsOnOwnedCheckouts(t *testing.T) {
	for name, each := range map[string]struct {
		search, detail string
		carried        bool
	}{
		"none": {`{"items":[]}`, `{}`, true},
		"open": {`{"items":[{"number":1,"pull_request":{"html_url":"https://github.com/acme/api/pull/1"}}]}`,
			`{"state":"open","html_url":"https://github.com/acme/api/pull/1","head":{"sha":"abc"},"user":{"login":"other"}}`, false},
		"closed since search": {`{"items":[{"number":1,"pull_request":{"html_url":"https://github.com/acme/api/pull/1"}}]}`, `{"state":"closed"}`, true},
		"draft":               {`{"items":[{"number":1,"draft":true,"pull_request":{"html_url":"https://github.com/acme/api/pull/1"}}]}`, `{}`, true},
		"own":                 {`{"items":[{"number":1,"user":{"login":"ACME"},"pull_request":{"html_url":"https://github.com/acme/api/pull/1"}}]}`, `{}`, true},
		"elsewhere":           {`{"items":[{"number":1,"pull_request":{"html_url":"https://github.com/other/api/pull/1"}}]}`, `{}`, true},
	} {
		t.Run(name, func(t *testing.T) {
			ak, checkout := checkoutHome(t, "# acme\n")
			if err := exec.Command("git", "-C", checkout, "remote", "set-url", "origin", "git@github.com:acme/api.git").Run(); err != nil {
				t.Fatal(err)
			}
			bin := strings.Split(os.Getenv("PATH"), string(os.PathListSeparator))[0]
			put(t, filepath.Join(bin, "gh"), fmt.Sprintf("#!/bin/sh\ncase \"$*\" in *repos/acme/api/pulls/1*) echo '%s';; *) echo '%s';; esac\n", each.detail, each.search))
			before := files(t, ak)
			tick := &ticking{log: newLog(io.Discard, io.Discard)}
			if tick.incoming("acme") != each.carried {
				t.Fatal("wrong incoming handover")
			}
			for path, want := range before {
				if want != "" && read(t, path) != want {
					t.Fatalf("incoming rewrote %s", path)
				}
			}
		})
	}
}
