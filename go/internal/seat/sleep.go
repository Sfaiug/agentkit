package seat

import (
	"context"
	"io"
	"math"
	"math/big"
	"os"
	"path"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/agent"
	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/hookfact"
	"agentkit/internal/host"
	"agentkit/internal/lifecycle"
	"agentkit/internal/notify"
	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

// A seat rested past its harness's prompt cache sleeps, and wakes when its work comes back, as
// Python's sleep.py has it: one rests from its turn's end while nothing but what it waits on moves
// it; sleeping ends its tmux session, its harness with it, marking its record asleep until it
// launches again; waking is Reopen's launch, on its own conversation.  Work beside its harness,
// held lines, an owner attached, any text in its composer or a second pane keeps it awake.

const (
	// alone is tmux's own check as it kills: nobody attached since, and the harness's pane the
	// only one (sleep.ALONE)
	alone = "#{&&:#{==:#{session_attached},0},#{&&:#{==:#{session_windows},1},#{==:#{window_panes},1}}}"
	// scopeEnds is the companion Python's launch starts in a seat's scope, which ends with the
	// seat, so it is no work of its own (orch.SCOPE_ENDS)
	scopeEnds = "import os, subprocess, sys, time\nos.setsid()\nwhile os.getppid() == int(sys.argv[1]):\n    time.sleep(1)\nsubprocess.run(sys.argv[2:])\n"
)

// shells are what tmux and a launch start a harness through (sleep.SHELLS).
var shells = []string{"sh", "bash", "dash", "zsh", "ksh", "fish"}

// A Rest is a seat at rest that may sleep: since when, and how long its harness's prompt cache
// lives, an endless one where its adapter says none.
type Rest struct {
	Name         string
	Since, Cache float64
}

// Resting is each seat at rest that may sleep (sleep._resting), and each whose rest hangs on what
// Go does not read, by when it would rest from; false where the home is one Go does not read.
func Resting(now time.Time) (rests, unread []Rest, known bool) {
	home, known := seated(now)
	if !known {
		return nil, nil, false
	}
	state := filepath.Join(config.Home(), "state")
	var table map[int]proc // one reading of the process table for every seat, as sleep._resting's
	for _, each := range home.Seats {
		rest, resting, read := each.rest(state, now, func() map[int]proc {
			if table == nil {
				table = processes()
			}
			return table
		})
		switch {
		case !read:
			unread = append(unread, rest)
		case resting:
			rests = append(rests, rest)
		}
	}
	return rests, unread, true
}

// rest is sleep._idle_since: since when the seat has rested, from its turn's end or its harness's
// launch where that came later, and whether it may sleep: on a conversation of its own, on ak's
// server, nobody in it, at its prompt with nothing but what it waits on moving it, nothing cut off,
// no work beside its harness and its composer read whole and empty.  read is false where that
// hangs on what Go does not read; Rest is still dated then, where it would be.
func (seat Seat) rest(state string, now time.Time, table func() map[int]proc) (Rest, bool, bool) {
	file := revivalFile(seat.Name)
	_, record, err := config.ResolveSession(seat.Name)
	began, _ := number(file.Get("began"))
	if !seat.looked() || seat.legacy || err != nil || record == nil || file.Str("state") != "at_prompt" || began == 0 {
		return Rest{}, false, true
	}
	launched, _ := number(record["launched"])
	block, _ := config.Section(seat.own, "sleep")
	rest := Rest{Name: seat.Name, Since: max(began, launched), Cache: math.Inf(1)}
	switch seconds := block["cache"].(type) {
	case *big.Int:
		rest.Cache, _ = new(big.Float).SetInt(seconds).Float64()
	case float64:
		rest.Cache = seconds
	}
	if attached, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", "="+seat.Name+":", "#{session_attached}"); err != nil || attached != "0" {
		return Rest{}, false, true
	}
	conversation, owned := harness.Owned(seat.own, record)
	rests, err := climbingOf(state, seat, keptSight(file), seconds(now)).rests()
	owes, readOwed := seat.owes(file)
	switch {
	case owned && conversation == "" || err == nil && !rests || owes:
		return Rest{}, false, true
	case !owned || err != nil || !readOwed:
		return rest, false, false
	}
	busy, read := seat.busy(table())
	if busy || !read {
		return rest, false, read
	}
	// The owner, 5 Nov 2026: "the text in the input field should never be deleted".  Only a
	// composer read whole and empty sleeps, read last.
	pane, exited := harnessScreen(seat.Name)
	draft, drawn := eyeOf(seat.own).rules.ComposerDraft(pane)
	return rest, !exited && drawn && draft == "", true
}

// rests is sleep._rests: the seat's word is idle or done, or working on what it waits on alone,
// nothing else ak moves moving it (watch.session_state's `waits`): no turn, usage wait, retry or
// line to type.
func (facts climbing) rests() (bool, error) {
	said, err := facts.climb()
	if err != nil || said.word == "idle" || said.word == "done" || !said.waits {
		return err == nil && (said.word == "idle" || said.word == "done"), err
	}
	for _, moves := range []rung{turnRunning, usageWait, retrying, telling} {
		if moving, err := moves(facts); err != nil || moving != nil {
			return false, err
		}
	}
	return true, nil
}

// waitedOn marks an answer one only what the seat waits on gives it: its runs, its `ak wait` or a
// live check.
func waitedOn(said *answer, err error) (*answer, error) {
	if said != nil {
		said.waits = true
	}
	return said, err
}

// owes is watch.cut_off's first answer: whether the seat would owe something once back, having
// asked, by its last look or a hook heard since, or the owner a question of its own, or being in a
// turn.  read is false where it held background work, whose kinds only its harness says.
func (seat Seat) owes(file *run.Object) (owes, read bool) {
	fact := seat.reader.HookFact(seat.Name)
	if hooked, event, err := lifecycle.State(seat.own, fact); err == nil {
		looked := keptSight(file)
		if hooked != "" && fact.At != 0 && fact.At != at(file.Get("hooked_at")) {
			looked = sight{state: hooked, hooked: hooked, hookedEvent: event, hookedAt: fact.At}
		}
		flight, _ := looked.turnInFlight(seat.own)
		if looked.state == "asking" || notify.OwnerQuestion(notify.Last(seat.Name)) || flight {
			return true, true
		}
	}
	return false, len(hookfact.Standing(seat.Name).Holds) == 0 && !file.Truthy("holds")
}

// A proc is a process as watch._proc_table reads it: its parent and its command's words.
type proc struct {
	parent int
	words  []string
}

// processes is the process table off /proc; a process it cannot read is left out.
func processes() map[int]proc {
	table := map[int]proc{}
	entries, _ := os.ReadDir("/proc")
	for _, entry := range entries {
		pid, err := strconv.Atoi(entry.Name())
		stat, ok := host.ReadStat(pid)
		if err != nil || !ok {
			continue
		}
		said, _ := os.ReadFile("/proc/" + entry.Name() + "/cmdline")
		table[pid] = proc{stat.Parent, slices.DeleteFunc(strings.Split(string(said), "\x00"), func(word string) bool { return word == "" })}
	}
	return table
}

// busy is sleep._busy: work runs beside the seat's harness.  Under the pane's first program and
// the shells tmux and the launch start it through above it, that is any process but the harness
// ak's wrapper runs, the scope's companion, the desktop server, which ends and starts again with
// its seat, and one its adapter names as the harness's own (`[sleep] own`); or, in a scope of its
// own, a process the tree lost.  A harness whose adapter names none is never known idle.  read is
// false for a name Go's patterns do not read as Python's.
func (seat Seat) busy(table map[int]proc) (bool, bool) {
	block, _ := config.Section(seat.own, "sleep")
	listed, named := block["own"].([]any)
	var own []*regexp.Regexp
	for _, each := range listed {
		text, _ := each.(string)
		pattern, err := regexp.Compile(text)
		if err != nil {
			return false, false
		}
		own = append(own, pattern)
	}
	said, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", harnessPane(seat.Name), "#{pane_pid}")
	root, unread := strconv.Atoi(said)
	if !named || err != nil || unread != nil || strings.Trim(said, "0123456789") != "" {
		return true, true
	}
	desktop := filepath.Join(config.Repo(), "tools", "desktop-mcp.py")
	children := map[int][]int{}
	for child, each := range table {
		children[each.parent] = append(children[each.parent], child)
	}
	type step struct {
		pid           int
		below, framed bool
	}
	reached, stack := map[int]bool{}, []step{{root, false, false}}
	for len(stack) > 0 {
		at := stack[len(stack)-1]
		stack = stack[:len(stack)-1]
		if reached[at.pid] {
			continue
		}
		words := table[at.pid].words
		line := strings.Join(words, " ")
		if at.below && !at.framed && !slices.Contains(words, scopeEnds) && agent.Program(words, true) != desktop &&
			!slices.ContainsFunc(own, func(pattern *regexp.Regexp) bool { return pattern.MatchString(line) }) {
			return true, true
		}
		reached[at.pid] = true
		shell := len(words) > 0 && slices.Contains(shells, strings.TrimLeft(path.Base(words[0]), "-"))
		wrapper := agent.Program(words, false) == "idle-compact.py"
		for _, child := range children[at.pid] {
			stack = append(stack, step{child, at.below || !shell, wrapper})
		}
	}
	scope, scoped := host.SeatScope(root)
	return scoped && (scope == nil || slices.ContainsFunc(scope, func(pid int) bool { return !reached[pid] })), true
}

// Sleep puts the seat at that rest to sleep (sleep.tick), under its typing lock: its rest read
// again, since the same, its session ended by tmux itself while nobody is attached and its
// harness's pane is its only one, and its record marked asleep.  Whether it sleeps.
func Sleep(rest Rest) (bool, error) {
	slept := false
	err := notify.Held(context.Background(), rest.Name, func(string) error {
		now := time.Now()
		home, known := seated(now)
		at := slices.IndexFunc(home.Seats, func(each Seat) bool { return each.Name == rest.Name })
		if !known || at < 0 {
			return nil
		}
		again, rests, read := home.Seats[at].rest(filepath.Join(config.Home(), "state"), now, processes)
		if !rests || !read || again.Since != rest.Since {
			return nil // a line going in first may have started a turn, one ended since a rest of its own
		}
		target := "=" + rest.Name
		tmux.Ask(tmux.Own(), "if-shell", "-F", "-t", target+":", alone, "kill-session -t "+commandhelp.ShellJoin([]string{target}))
		if slept = tmux.Absent(tmux.Own(), target); !slept {
			return nil
		}
		return Update(rest.Name, func(record *run.Object) bool {
			record.Set("asleep", run.Float(seconds(time.Now())))
			return true
		})
	})
	return slept, err
}

// Wakes is whether Go carries the waking of that sleeping seat (Wake), read without waking it.
func Wakes(name string) bool {
	if !Asleep(name) {
		return false
	}
	carried, _ := Reopen(name, How{DryRun: true, Detached: true}, io.Discard, io.Discard)
	return carried
}
