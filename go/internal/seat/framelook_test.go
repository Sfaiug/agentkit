//go:build unix

package seat

import (
	"errors"
	"maps"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// framed is a fake tmux holding those seats live at their prompts, on the test's own server, and the
// log of every call made to it.
func framed(t *testing.T, home string, seats ...string) func() []string {
	t.Helper()
	bin, log := t.TempDir(), filepath.Join(t.TempDir(), "tmux.log")
	listed, panes := "", ""
	for _, name := range seats {
		record(t, home, name, map[string]any{"repo": filepath.Join(home, "code", "acme")}) // filed: no filing reads the home again
		listed += name + `\t1\n`
		panes += name + `\t0\n`
	}
	// each seat's pane is named after it, so a capture says whose screen it took
	write(t, filepath.Join(bin, "tmux"), "#!/bin/sh\nprintf '%s\\n' \"$*\" >> "+log+"\n"+
		"case \"$*\" in *'-L seat-test'*) ;; *) exit 1;; esac\ncase \"$*\" in\n"+
		"*list-sessions*) printf '"+listed+"';;\n*list-panes*-a*) printf '"+panes+"';;\n"+
		"*list-panes*) name=${*#*=}; printf '%%%s 0\\n' \"${name%%:*}\";;\n"+
		"*capture-pane*) printf '────────\\n❯\\n────────\\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\\n';;\n"+
		"*display-message*'#{session_attached}'*) printf '0\\n';;\n*) exit 0;;\nesac\n")
	os.Chmod(filepath.Join(bin, "tmux"), 0o700)
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	return func() []string {
		data, _ := os.ReadFile(log)
		os.Remove(log)
		return strings.Split(strings.TrimSpace(string(data)), "\n")
	}
}

func TestAFrameLooksAtEachLiveSeatOnce(t *testing.T) {
	home := sandbox(t)
	seats := []string{"acme", "beta", "gamma"}
	calls := framed(t, home, seats...)
	found, known := Menu(time.Now())
	if !known || len(found.Seats) != len(seats) {
		t.Fatalf("known %v: %+v", known, found.Seats)
	}
	if err := found.Announce(time.Now()); err != nil {
		t.Fatal(err)
	}
	reads, captures := 0, map[string]int{}
	for _, call := range calls() {
		if strings.HasPrefix(call, "-L seat-test list-sessions -F #{session_name}\t") {
			reads++ // a reading asks ak's server for its sessions once (holdings)
		}
		if _, pane, captured := strings.Cut(call, "capture-pane -p -e -J -t %"); captured {
			captures[pane]++
		}
	}
	if reads != 1 {
		t.Errorf("the frame read the home %d times", reads)
	}
	for _, name := range seats {
		if captures[name] != 1 {
			t.Errorf("%s was captured %d times: %v", name, captures[name], captures)
		}
		if file := stateFiles(t, home)["seat-"+name+".json"]; !strings.Contains(file, `"word": "idle"`) || !strings.Contains(file, `"rule": "prompt.composer"`) {
			t.Errorf("%s was not published from its look: %s", name, file)
		}
	}
}

func TestWhatCameWhileAFramesLookWaitedWritesNothing(t *testing.T) {
	for name, file := range map[string]string{
		"the owner's stop mark": `{"stopped_at": 1, "closed_by_owner": true}`,
		"a wait on its usage":   `{"usage_wait": {"reason": "spent", "since": 1}}`,
		"a field Go never read": `{"acme_only": true}`,
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			framed(t, home, "acme")
			found, known := Menu(time.Now())
			if !known {
				t.Fatal("Go did not read the seat")
			}
			write(t, stateFile(home, "seat-acme.json"), file)
			before := stateFiles(t, home)
			if err := found.Announce(time.Now()); !errors.Is(err, ErrUnread) {
				t.Fatalf("what came during the wait was looked past: %v", err)
			}
			after := stateFiles(t, home)
			delete(after, "seat-acme.announce") // the lock it waited on, which holds nothing
			if !maps.Equal(before, after) {
				t.Fatalf("refusing wrote: %v, then %v", before, after)
			}
		})
	}
}
