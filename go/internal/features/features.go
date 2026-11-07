// Package features reaches a production project's feature switches, live data in the project,
// through the one command its AGENTS.md names under `features:` (Python's menu.switches): `list`
// prints every feature, each `you` and `everyone`, and `set <id> you|everyone on|off` flips one.
package features

import (
	"bytes"
	"cmp"
	"context"
	"errors"
	"fmt"
	"os/exec"
	"slices"
	"strings"
	"sync"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/host"
	record "agentkit/internal/run"
)

// Every is how old a project's last `list` grows before the menu asks again.
const Every = time.Minute

// wait is the longest the project's command is waited for: a variable, so a test waits less.
var wait = 20 * time.Second

// A Switch is one feature as the project's `list` answers it.
type Switch struct {
	ID, Name      string
	You, Everyone bool
	Fixed         bool // the project does not let you switch it for yourself
}

// A Reading is a project's switches as they stand: the rows its `list` last answered, nil before
// any; why the last one answered none, "" where it did; and since when the list now going was
// asked, zero where none is.
type Reading struct {
	Rows   []Switch
	Why    string
	Asking time.Time
}

// Hidden is how many of its features are hidden: off for everyone.
func (r Reading) Hidden() int {
	hidden := 0
	for _, row := range r.Rows {
		if !row.Everyone {
			hidden++
		}
	}
	return hidden
}

var (
	held   sync.Mutex
	known  = map[string]*entry{}
	landed = make(chan struct{}, 1)
)

type entry struct {
	Reading
	asked time.Time
	set   time.Time      // when a flip's answer last stood in the rows
	flips map[string]int // each feature's flips asked, the last of them the one drawn
}

// Named is whether the checkout's AGENTS.md names a features command.
func Named(checkout string) bool { return gitcall.Declared(checkout, "features") != "" }

// Read is the checkout's switches as they stand, and never waits: once its last `list` was asked
// every ago and none is going, it is asked again behind, and Landed says when that lands.
func Read(checkout string, every time.Duration) Reading {
	held.Lock()
	defer held.Unlock()
	found := known[checkout]
	if found == nil {
		found = &entry{}
		known[checkout] = found
	}
	if now := time.Now(); found.Asking.IsZero() && (found.asked.IsZero() || now.Sub(found.asked) >= every) {
		found.asked, found.Asking = now, now
		go list(checkout, found)
	}
	return found.Reading
}

// Landed is told once a list or a flip has landed since it was last read from: what draws the
// switches draws again.
func Landed() <-chan struct{} { return landed }

func land() {
	select {
	case landed <- struct{}{}:
	default:
	}
}

func list(checkout string, found *entry) {
	answer, why := own(checkout, "list")
	rows, listed := switches(answer)
	held.Lock()
	switch {
	case found.set.After(found.Asking): // a flip answered while this was asked: this list is older than it
	case listed:
		found.Rows, found.Why = rows, "" // a new list, never the old one changed: a reading keeps its own
	default:
		found.Why = cmp.Or(why, "list answered no list")
	}
	found.Asking = time.Time{}
	held.Unlock()
	land()
}

// objects is the rows a `list` answered, each an object with an id, as Python's
// menu.switch_rows keeps them; false for no list.
func objects(answer any) ([]*record.Object, bool) {
	listed, ok := answer.([]any)
	if !ok {
		return nil, false
	}
	rows := []*record.Object{}
	for _, each := range listed {
		if row, ok := each.(*record.Object); ok && row.Has("id") {
			rows = append(rows, row)
		}
	}
	return rows, true
}

// switches is the rows a `list` answered, each with an id; false for no list.
func switches(answer any) ([]Switch, bool) {
	listed, ok := objects(answer)
	if !ok {
		return nil, false
	}
	rows := []Switch{}
	for _, row := range listed {
		id := record.Text(row.Get("id"))
		you, _ := row.Get("you").(bool)
		everyone, _ := row.Get("everyone").(bool)
		rows = append(rows, Switch{ID: id, Name: cmp.Or(row.Str("name"), id), You: you, Everyone: everyone,
			Fixed: row.Get("you_switchable") == false})
	}
	return rows, true
}

// own is the project's features command run in ak's own environment, as the menu and the tick
// run it.
func own(checkout string, words ...string) (any, string) {
	env, err := config.ChildEnv()
	if err != nil {
		return nil, words[0] + ": " + config.PyError(err)
	}
	return run(checkout, env, words...)
}

// run is the project's features command with words after it, in env, as Python's
// gitcall.project_answer runs a project's own command: its JSON answer, or nil and the one line
// saying why.  It runs in the checkout, reading nothing, in a session of its own, without the
// seat's name (owner_env): an ssh in it never reads the keys, nor is it a seat reaching the live
// host.  One past the wait is killed with everything it started, so a `set` said to have failed
// never lands after.
func run(checkout string, env []string, words ...string) (any, string) {
	what, command := words[0], gitcall.Declared(checkout, "features")
	if command == "" {
		return nil, "AGENTS.md names no features command"
	}
	ctx, cancel := context.WithTimeout(context.Background(), wait)
	defer cancel()
	cmd := exec.CommandContext(ctx, "/bin/sh", "-c", command+" "+commandhelp.ShellJoin(words))
	cmd.Dir, cmd.WaitDelay = checkout, wait // one gone to a session of its own is let go of then
	cmd.Env = slices.DeleteFunc(slices.Clone(env), func(pair string) bool { return strings.HasPrefix(pair, "AGENTKIT_SESSION=") })
	var out, said bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &said
	stop := host.Group(cmd)
	err := cmd.Start()
	if err == nil {
		// past the wait its session goes, even once the shell is gone: what it started may still
		// hold the output open, and exec stops watching the deadline when the shell exits
		defer context.AfterFunc(ctx, stop)()
		err = cmd.Wait()
	}
	var exit *exec.ExitError
	switch {
	case ctx.Err() != nil:
		return nil, fmt.Sprintf("%s: no answer in %d s", what, wait/time.Second)
	case errors.As(err, &exit):
		if lines := config.SplitLines(gitcall.Strip(said.String())); len(lines) > 0 {
			return nil, lines[len(lines)-1]
		}
		return nil, fmt.Sprintf("%s exited %d", what, exit.ExitCode())
	case err != nil:
		return nil, what + ": " + config.PyError(err)
	}
	// read as Python reads it, so an id is the text Python's str() makes of it
	answer, err := record.Decode([]byte(gitcall.Decoded(out.String())))
	if err != nil {
		return nil, what + " answered no JSON"
	}
	return answer, ""
}
