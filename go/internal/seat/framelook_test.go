//go:build unix

package seat

import (
	"context"
	"errors"
	"maps"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/lock"
)

// framed is a fake tmux holding those seats live, each showing $HOME/screen-<name> (the prompt
// until a test draws another), on the test's own server, and the log of every call made to it.
func framed(t *testing.T, home string, seats ...string) func() []string {
	t.Helper()
	bin, log := t.TempDir(), filepath.Join(t.TempDir(), "tmux.log")
	listed, panes := "", ""
	for _, name := range seats {
		write(t, filepath.Join(home, "screen-"+name), prompting)
		listed += name + `\t1\n`
		panes += name + `\t0\n`
	}
	// each seat's pane is named after it, so a capture says whose screen it took
	write(t, filepath.Join(bin, "tmux"), "#!/bin/sh\nprintf '%s\\n' \"$*\" >> "+log+"\n"+
		"case \"$*\" in *'-L seat-test'*) ;; *) exit 1;; esac\ncase \"$*\" in\n"+
		"*list-sessions*) printf '"+listed+"';;\n*list-panes*-a*) printf '"+panes+"';;\n"+
		"*list-panes*) name=${*#*=}; printf '0 1 %%%s 0\\n' \"${name%%:*}\";;\n"+
		"*capture-pane*display-message*) pane=${*#*-t %}; cat \"$HOME/screen-${pane%% *}\"; printf '\\n0\\n';;\n"+
		"*capture-pane*) cat \"$HOME/screen-${*##*%}\";;\n"+
		"*display-message*'#{session_attached}'*) printf '0\\n';;\n*) exit 0;;\nesac\n")
	os.Chmod(filepath.Join(bin, "tmux"), 0o700)
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	return func() []string {
		data, _ := os.ReadFile(log)
		os.Remove(log)
		return strings.Split(strings.TrimSpace(string(data)), "\n")
	}
}

// filed is a seat's record filed under a project, as no filing reads the home again for it.
func filed(t *testing.T, home string, names ...string) {
	t.Helper()
	for _, name := range names {
		record(t, home, name, map[string]any{"repo": filepath.Join(home, "code", "acme")})
	}
}

func TestAFrameLooksAtEachLiveSeatOnce(t *testing.T) {
	home := sandbox(t)
	seats := []string{"acme", "beta", "gamma"}
	calls := framed(t, home, seats...)
	filed(t, home, seats...)
	for _, frame := range []string{"first", "behind it"} { // as readFrame reads each
		read := Menu
		if frame != "first" {
			read = MenuRead
		}
		found, known := read(time.Now())
		if known && frame != "first" {
			known = found.Announce(time.Now()) == nil
		}
		if !known || len(found.Seats) != len(seats) {
			t.Fatalf("%s frame: known %v: %+v", frame, known, found.Seats)
		}
		reads, captures := 0, map[string]int{}
		for _, call := range calls() {
			if strings.HasPrefix(call, "-L seat-test list-sessions -F #{session_name}\t") {
				reads++ // a reading asks ak's server for its sessions once (holdings)
			}
			if _, pane, captured := strings.Cut(call, "capture-pane -p -e -J -t %"); captured {
				pane, _, _ = strings.Cut(pane, " ")
				captures[pane]++
			}
		}
		if reads != 1 {
			t.Errorf("the %s frame read the home %d times", frame, reads)
		}
		for at, name := range seats {
			if captures[name] != 1 {
				t.Errorf("the %s frame captured %s %d times", frame, name, captures[name])
			}
			if found.Seats[at].Word != "idle" || found.Seats[at].seen.rule != "prompt.composer" {
				t.Errorf("the %s frame did not decide %s from its look: %+v", frame, name, found.Seats[at])
			}
		}
	}
	for _, name := range seats {
		if file := stateFiles(t, home)["seat-"+name+".json"]; !strings.Contains(file, `"word": "idle"`) || !strings.Contains(file, `"rule": "prompt.composer"`) {
			t.Errorf("%s was not published from its look: %s", name, file)
		}
	}
}

func TestAFramesLookIsTakenUnderTheAnnounceLock(t *testing.T) {
	home := sandbox(t)
	framed(t, home, "acme")
	filed(t, home, "acme")
	held, err := lock.Wait(context.Background(), stateFile(home, "seat-acme.announce"))
	if err != nil {
		t.Fatal(err)
	}
	found, known := MenuRead(time.Now())
	if !known {
		t.Fatal("Go did not read the seat")
	}
	// another announcer, holding the lock, sees a question and publishes it
	write(t, filepath.Join(home, "screen-acme"), asked)
	write(t, stateFile(home, "seat-acme.json"), `{"state": "asking", "rule": "asking.question", "word": "needs you", "reason": "Which one?", "word_since": 2}`)
	held.Close()
	if err := found.Announce(time.Now()); err != nil {
		t.Fatal(err)
	}
	if file := stateFiles(t, home)["seat-acme.json"]; !strings.Contains(file, `"word": "needs you"`) || !strings.Contains(file, `"state": "asking"`) {
		t.Fatalf("a look from before the lock landed over a newer one: %s", file)
	}
}

func TestWhatCameWhileAFramesLookWaitedWritesNothing(t *testing.T) {
	for name, each := range map[string]struct{ seat, file string }{
		"the owner's stop mark":             {"beta", `{"stopped_at": 1, "closed_by_owner": true}`},
		"a usage refusal kept with no wait": {"beta", `{"usage_refusal": {"line": "spent", "at": 1}}`},
		"a field Go never read":             {"beta", `{"acme_only": true}`},
		"a bare seat's kept question":       {"bare", `{"unasked": {"questions": [{"id": "q", "text": "Which one?", "at": 1}]}}`},
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			framed(t, home, "acme", "bare", "beta")
			filed(t, home, "acme", "beta")
			found, known := MenuRead(time.Now())
			if !known || len(found.Seats) != 3 {
				t.Fatalf("known %v: %+v", known, found.Seats)
			}
			write(t, stateFile(home, "seat-"+each.seat+".json"), each.file)
			before := stateFiles(t, home)
			if err := found.Announce(time.Now()); !errors.Is(err, ErrUnread) {
				t.Fatalf("what came during the wait was looked past: %v", err)
			}
			after := stateFiles(t, home)
			maps.DeleteFunc(after, func(file, _ string) bool { return strings.HasSuffix(file, ".announce") }) // the locks it waited on
			if !maps.Equal(before, after) {
				t.Fatalf("refusing wrote: %v, then %v", before, after)
			}
		})
	}
}
