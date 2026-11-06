// Package features reaches a production project's feature switches, live data in the project,
// through the one command its AGENTS.md names under `features:` (Python's menu.switches): `list`
// prints every feature, each `you` and `everyone`.
package features

import (
	"bytes"
	"cmp"
	"context"
	"encoding/json"
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

// Landed is told once a list has landed since it was last read from: what draws the switches
// draws again.
func Landed() <-chan struct{} { return landed }

func list(checkout string, found *entry) {
	answer, why := run(checkout, "list")
	rows, listed := switches(answer)
	held.Lock()
	found.Asking = time.Time{}
	if listed {
		found.Rows, found.Why = rows, "" // a new list, never the old one changed: a reading keeps its own
	} else {
		found.Why = cmp.Or(why, "list answered no list")
	}
	held.Unlock()
	select {
	case landed <- struct{}{}:
	default:
	}
}

// switches is the rows a `list` answered, each with an id; false for no list.
func switches(answer any) ([]Switch, bool) {
	listed, ok := answer.([]any)
	if !ok {
		return nil, false
	}
	rows := []Switch{}
	for _, each := range listed {
		row, ok := each.(map[string]any)
		id, named := row["id"]
		if !ok || !named {
			continue
		}
		name, _ := row["name"].(string)
		you, _ := row["you"].(bool)
		everyone, _ := row["everyone"].(bool)
		rows = append(rows, Switch{ID: fmt.Sprint(id), Name: cmp.Or(name, fmt.Sprint(id)), You: you, Everyone: everyone,
			Fixed: row["you_switchable"] == false})
	}
	return rows, true
}

// run is the project's features command with words after it, as Python's gitcall.project_answer
// runs a project's own command: its JSON answer, or nil and the one line saying why.  It runs in
// the checkout, reading nothing, in a session of its own, without the seat's name (owner_env): an
// ssh in it never reads the keys, nor is it a seat reaching the live host.  One past the wait is
// killed with everything it started, so a `set` said to have failed never lands after.
func run(checkout string, words ...string) (any, string) {
	what, command := words[0], gitcall.Declared(checkout, "features")
	if command == "" {
		return nil, "AGENTS.md names no features command"
	}
	env, err := config.ChildEnv()
	if err != nil {
		return nil, what + ": " + config.PyError(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), wait)
	defer cancel()
	cmd := exec.CommandContext(ctx, "/bin/sh", "-c", command+" "+commandhelp.ShellJoin(words))
	cmd.Dir, cmd.WaitDelay = checkout, wait // one gone to a session of its own is let go of then
	cmd.Env = slices.DeleteFunc(env, func(pair string) bool { return strings.HasPrefix(pair, "AGENTKIT_SESSION=") })
	var out, said bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &said
	// past the wait its session goes, even once the shell is gone: what it started may still hold
	// the output open, and exec stops watching the deadline when the shell exits
	defer context.AfterFunc(ctx, host.Group(cmd))()
	err = cmd.Run()
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
	var answer any
	if json.Unmarshal(out.Bytes(), &answer) != nil {
		return nil, what + " answered no JSON"
	}
	return answer, ""
}
