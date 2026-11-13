//go:build linux && (amd64 || arm64)

package update

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestGoLiveProtectsWorkAfterItsFirstSwap(t *testing.T) {
	for _, change := range []string{"clean", "edited", "untracked-hidden", "branch"} {
		t.Run(change, func(t *testing.T) {
			home, checkout, git := liveHome(t)
			origin := t.TempDir()
			git(origin, "clone", "-q", checkout, ".")
			write := func(path, text string) {
				t.Helper()
				if err := os.WriteFile(path, []byte(text), 0o700); err != nil {
					t.Fatal(err)
				}
			}
			advance := func(text string) string {
				t.Helper()
				write(filepath.Join(origin, "notes"), text)
				git(origin, "add", ".")
				git(origin, "-c", "user.name=acme", "-c", "user.email=acme@example.com", "commit", "-qm", text)
				return git(origin, "rev-parse", "HEAD")
			}
			write(filepath.Join(origin, "install.sh"), "#!/bin/sh\n[ \"$1\" != --prepare ] || exit 0\necho ran >>\"$HOME/install-runs\"\n")
			first := advance("first update")
			git(checkout, "remote", "add", "origin", origin)
			tick := func() []string {
				t.Helper()
				var said []string
				if err := GoLive(checkout, func(line string) { said = append(said, line) }); err != nil {
					t.Fatal(err)
				}
				return said
			}
			if got := tick(); !reflect.DeepEqual(got, []string{"agentkit is live at " + short(first)}) || owned(checkout) == "" {
				t.Fatalf("first swap: said=%q, owned=%q", got, owned(checkout))
			}
			why, file := "dirty", filepath.Join(checkout, "notes")
			switch change {
			case "edited":
				write(file, "somebody's work\n")
			case "untracked-hidden":
				git(checkout, "config", "status.showUntrackedFiles", "no")
				file = filepath.Join(checkout, "scratch")
				write(file, "somebody's work\n")
			case "branch":
				git(checkout, "checkout", "-qb", "fix-api")
				why = "on fix-api, not main"
			}
			for _, text := range []string{"second update", "third update"} {
				tip := advance(text)
				want := []string{"WARN agentkit did not go live at " + short(tip) + ":",
					"  update: agentkit: left as it is: " + checkout + " is " + why}
				if change == "clean" {
					// the move before made final, as a tick of the version it put live makes it
					if err := os.Remove(filepath.Join(home, ".agentkit", "tmp", "keep", "ak")); err != nil {
						t.Fatal(err)
					}
					want = []string{"agentkit is live at " + short(tip)}
				}
				if got := tick(); !reflect.DeepEqual(got, want) {
					t.Fatalf("said=%q, want=%q", got, want)
				}
				if got := tick(); len(got) != 0 {
					t.Fatalf("repeat tick said %q", got)
				}
				if change != "clean" {
					if git(checkout, "rev-parse", "HEAD") != first {
						t.Fatal("moved somebody's checkout")
					}
					record, err := os.ReadFile(filepath.Join(home, ".agentkit", "state", "agentkit-said-watch"))
					if err != nil || string(record) != tip+"\n" {
						t.Fatalf("warning record=%q, err=%v", record, err)
					}
				}
			}
			if change == "clean" {
				return
			}
			ran, err := os.ReadFile(filepath.Join(home, "install-runs"))
			if err != nil || string(ran) != "ran\n" {
				t.Fatalf("reinstalled somebody's checkout: ran=%q, err=%v", ran, err)
			}
			if change == "branch" {
				if git(checkout, "symbolic-ref", "--short", "HEAD") != "fix-api" {
					t.Fatal("changed somebody's branch")
				}
			} else if data, err := os.ReadFile(file); err != nil || string(data) != "somebody's work\n" {
				t.Fatalf("lost somebody's work: data=%q, err=%v", data, err)
			}
		})
	}
}
