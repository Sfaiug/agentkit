package seat

import (
	"cmp"
	"errors"
	"fmt"
	"io/fs"
	"maps"
	"math"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/agent"
	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/plan"
	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

// stays are the kinds of a seat's file a rename leaves under the old name: the running harness
// keeps the rulebook it was started on, its hooks the turn's latch and its ssh shim the turn's
// reach under the name it was started with, and a pane still starting reads the launch file it
// was given.  Its record moves by itself.
var stays = []string{"session", "rulebook", "stop", "live", "launch"}

// Rename is Python's orch.cmd_rename and orch.rename of the seat by that name to the name given:
// what it says, or false where the rename is Python's.  It is Python's before anything moves where
// a name's rename chain or record cannot be read, Go cannot keep what the seat's record or
// watch.json holds, a run the seat launched holds a place in a landing line (run.Lined), or
// another seat's record holds the name and only Python's listing says whether that seat has a row;
// and where a writer has since left in the record what Go cannot keep, with tmux's rename undone.
// The harness's own title is left to the next tick (watch.sync_title), which finds it behind the
// new name.  Everything happens under the locks Python's takes, in its order.
func Rename(name, given string, auto bool, now time.Time) (string, bool, error) {
	if err := config.EnsureDirs(); err != nil {
		return "", true, err
	}
	state := filepath.Join(config.Home(), "state")
	said, known := "", true
	// every lifecycle change's lock: no other rename or stop moves a name from here on
	err := under(filepath.Join(state, "watch.lock"), func() (err error) {
		said, known, err = renaming(state, name, config.SessionName(given), auto, now)
		return err
	})
	return said, known, err
}

// renaming is the half of a rename that decides: a refusal in Python's words, a seat left as it
// is, or the move.
func renaming(state, name, new string, auto bool, now time.Time) (string, bool, error) {
	old, _, err := config.ResolveSession(name)
	if err != nil {
		return "", false, nil
	}
	held, seats := holdings(state)
	server, found := seats[old]
	if !found {
		running := cmp.Or(strings.Join(slices.Sorted(maps.Keys(seats)), ", "), "none")
		return "", true, Refusal(fmt.Sprintf("no orchestrator session %s (running: %s)", commandhelp.Quote(old), running))
	}
	record, err := run.ReadJSON(filepath.Join(state, "session-"+old+".json"))
	if errors.Is(err, run.ErrLoneSurrogate) {
		return "", false, nil
	}
	if auto && (record == nil || !record.Truthy("unnamed")) {
		return "seat is already named " + old, true, nil
	}
	renamed := "renamed " + old + " -> " + new
	if new == old {
		return renamed, true, update(state, old, func(data *run.Object) bool {
			named := data.Has("unnamed")
			data.Delete("unnamed")
			return named
		})
	}
	target, _, err := config.ResolveSession(new)
	if new == "" {
		return "", true, Refusal(err.Error())
	}
	if err != nil {
		return "", false, nil
	}
	if slices.Contains(held, new) {
		return "", true, spokenFor(new)
	}
	if target != old {
		if _, seat := seats[new]; seat {
			return "", true, spokenFor(new)
		}
		listed, known := claimed(state, new, target, seats)
		if !known {
			return "", false, nil
		}
		if listed {
			return "", true, spokenFor(new)
		}
		if target != new {
			// Python finds this only once tmux has renamed the seat
			return "", true, Refusal(commandhelp.Quote(new) + " points at another session; pick a name that is not a rename")
		}
	}
	if _, err := run.ReadJSON(filepath.Join(state, "watch.json")); !runsCarry(old) || errors.Is(err, run.ErrLoneSurrogate) {
		return "", false, nil
	}
	carried := true
	err = under(filepath.Join(state, "notify-"+old+".lock"), func() error {
		// An old name of this seat keeps leading to the lock held above until its record moves
		// back there: a writer reaching it then takes this lock, and waits for the files to follow.
		return under(filepath.Join(state, "notify-"+new+".lock"), func() (err error) {
			carried, err = carry{state, server, old, new, target == old}.do(now)
			return err
		})
	})
	return renamed, carried, err
}

func spokenFor(name string) Refusal {
	return Refusal(fmt.Sprintf("the name %s is already spoken for", commandhelp.Quote(name)))
}

// holdings is what tmux holds as Python's orch.held_names and orch.sessions read it: every session
// on ak's server, and the server of each seat.  There a session is one unless it is no record's,
// ak did not open it and it runs no agent; on the person's own server only what ak opened is.
func holdings(state string) ([]string, map[string]string) {
	var held []string
	seats := map[string]string{}
	for _, session := range tmux.Sessions(tmux.Own()) {
		held = append(held, session.Name)
		record, _ := run.Shared(filepath.Join(state, "session-"+session.Name+".json"))
		if session.Mark == "1" || record != nil && !record.Has(config.Renamed) || !agent.Agentless(tmux.Own(), []string{session.Name}) {
			seats[session.Name] = tmux.Own()
		}
	}
	for _, session := range tmux.Sessions(tmux.Default) {
		if _, own := seats[session.Name]; session.Mark == "1" && !own {
			seats[session.Name] = tmux.Default
		}
	}
	return held, seats
}

// claimed is whether a name tmux does not hold is another seat's as Python's orch.taken_names
// reads it: a pointer leading to a seat or a record; a record whose seat has a row, for owning its
// conversation or being stopped by the owner.  False for known where only Python's listing can say.
func claimed(state, name, target string, seats map[string]string) (bool, bool) {
	if target != name {
		_, seat := seats[target]
		record, _ := run.ReadJSON(filepath.Join(state, "session-"+target+".json"))
		return seat || record != nil, true
	}
	record, err := run.ReadJSON(filepath.Join(state, "session-"+name+".json"))
	if errors.Is(err, run.ErrLoneSurrogate) || record != nil && record.Has(config.Renamed) {
		return false, false
	}
	if record == nil {
		return false, true
	}
	mark, _ := run.ReadJSON(filepath.Join(state, "seat-"+name+".json"))
	if mark != nil && mark.Truthy("stopped_at") || record.Truthy("conversation") && record.Get("id_source") == "launcher" {
		return true, true
	}
	return false, false
}

// runsCarry is false where Python's write of a run naming the seat does more than Change's, or Go
// cannot read a run.
func runsCarry(old string) bool {
	for _, dir := range run.Dirs() {
		record, err := run.Read(dir)
		if errors.Is(err, run.ErrLoneSurrogate) || names(record, old) && run.Lined(record) {
			return false
		}
	}
	return true
}

// names is whether a run's record names the seat.
func names(record *run.Object, seat string) bool {
	return record != nil && (record.Get("launched_session") == seat || record.Get("session") == seat)
}

// A carry is one rename under way: back is a seat renamed to a name it had.
type carry struct {
	state, server, old, new string
	back                    bool
}

// do moves everything that names the seat, tmux first, as what follows is no use if tmux refuses;
// false where the record has come to hold what Go cannot keep, and tmux's rename is undone.
func (m carry) do(now time.Time) (bool, error) {
	if err := tmux.Rename(m.server, m.old, m.new); err != nil {
		return true, Refusal(fmt.Sprintf("tmux could not rename %s to %s: %v", m.old, m.new, err))
	}
	if err := m.record(); errors.Is(err, run.ErrLoneSurrogate) {
		if err := tmux.Rename(m.server, m.new, m.old); err != nil {
			return true, Refusal(fmt.Sprintf("tmux could not rename %s to %s: %v", m.new, m.old, err))
		}
		return false, nil
	} else if err != nil {
		return true, err
	}
	// New windows get the new name; the running orchestrator follows the pointer.  One that does
	// not take costs a later window its name, and no more, as Python's.
	tmux.Ask(m.server, "set-environment", "-t", "="+m.new, "AGENTKIT_SESSION", m.new)
	if err := errors.Join(m.pointers(), m.files(), m.watch(now)); err != nil {
		return true, err
	}
	// Listed now rather than at the look: a run launched since names the old name too.
	for _, dir := range run.Dirs() {
		if record, _ := run.Read(dir); !names(record, m.old) {
			continue
		}
		// A record that cannot be written keeps the old name, which leads here.
		run.Change(dir, func(record *run.Object) error {
			for _, key := range []string{"launched_session", "session"} {
				if record.Get(key) == m.old {
					record.Set(key, m.new)
				}
			}
			return nil
		})
	}
	m.tell()
	return true, nil
}

// path is a file of state/.
func (m carry) path(file string) string { return filepath.Join(m.state, file) }

// record moves the record to the new name, titled, and leaves a pointer at the old
// (config.rename_session), all under both records' locks: a field written to the old one meanwhile
// moves with it.  What cannot be read is never written over, and its error leaves everything here
// as it was.
func (m carry) record() error {
	was, now := m.path("session-"+m.old+".json"), m.path("session-"+m.new+".json")
	return under(m.path(".session-"+m.old+".lock"), func() error {
		return under(m.path(".session-"+m.new+".lock"), func() error {
			record, err := run.ReadJSON(was)
			if err != nil && !errors.Is(err, fs.ErrNotExist) {
				return fmt.Errorf("%s: %w", was, err)
			}
			if !m.back {
				// a free name: the plan a gone seat left there, or under a name still leading
				// there, is not this seat's
				if err := plan.Forget(m.new); err != nil {
					return err
				}
			}
			if record != nil && !record.Has(config.Renamed) {
				titled(record, m.new)
				if err := replace(now, []byte(run.Encode(record)+"\n")); err != nil {
					return err
				}
			} else if m.back { // a seat with no record leaves no pointer to its own name
				if err := os.Remove(now); err != nil && !errors.Is(err, fs.ErrNotExist) {
					return err
				}
			}
			pointer := run.NewObject()
			pointer.Set(config.Renamed, m.new)
			return replace(was, []byte(run.Encode(pointer)+"\n"))
		})
	})
}

// pointers has every older name of the seat, straight or through its other old names, lead to the
// new one, so no chain passes one rename however often a seat is renamed.
func (m carry) pointers() error {
	leads := map[string]string{}
	for _, path := range config.SeatFiles() {
		held, _ := run.ReadJSON(path)
		if name, ok := sessionFile(filepath.Base(path)); ok && held != nil {
			if next, isText := held.Get(config.Renamed).(string); isText {
				leads[name] = config.Fold(next)
			}
		}
	}
	var failed []error
	for name, first := range leads {
		seen, step := map[string]bool{name: true}, first
		for step != m.old {
			next, pointer := leads[step]
			if !pointer || seen[step] {
				break
			}
			seen[step], step = true, next
		}
		if step != m.old {
			continue
		}
		failed = append(failed, put(m.path("session-"+name+".json"), m.path(".session-"+name+".lock"), run.Encode, false, func(data *run.Object) bool {
			if config.Fold(data.Str(config.Renamed)) != first {
				return false
			}
			data.Set(config.Renamed, m.new)
			return true
		}))
	}
	return errors.Join(failed...)
}

// files moves the seat's files to the new name, but what stays.  Back to a name it had, what the
// seat wrote under it since is kept rather than moved over: a seat renamed still writes its plan
// under the name it was launched with, and a plan is read under every name the seat had.  The
// verification lock always moves: the one held is the one the seat's name reaches, and one under
// the old name is a contender's that resolved that name before the last move and opened it after,
// which none keeps (config.rename_session).
func (m carry) files() error {
	was, now := config.SeatFileNames(m.old), config.SeatFileNames(m.new)
	var failed []error
	for kind, file := range was {
		from, to := m.path(file), m.path(now[kind])
		switch {
		case slices.Contains(stays, kind) || !exists(from):
		case kind == "handover":
			// the rulebook it runs on names it under the old name, and a move only adds to it: a
			// copy keeps that one readable, the newest whole under the new name
			data, err := os.ReadFile(from)
			failed = append(failed, err)
			if err == nil {
				copied := fmt.Sprintf("%s.%d.tmp", to, os.Getpid())
				failed = append(failed, os.WriteFile(copied, data, 0o666), os.Rename(copied, to))
			}
		case !m.back || !exists(to) || kind == "verify":
			failed = append(failed, os.Rename(from, to))
		}
	}
	return errors.Join(failed...)
}

// titled is what a rename changes in the record under its new name (watch.title_record): named now;
// a send for a conversation since replaced retired, and one in flight kept as an echo of a title
// ak set, since its line can be sent or recorded later, after a newer title is confirmed.
func titled(data *run.Object, new string) {
	data.Delete("unnamed")
	conversation := data.Get("conversation")
	if data.Has("title_conversation") && !run.Equal(data.Get("title_conversation"), conversation) {
		data.Delete("title_sync")
		data.Delete("title_superseded")
	}
	var echoes []string
	for _, each := range data.List("title_superseded") {
		if echo, isText := each.(string); isText && echo != new {
			echoes = append(echoes, echo)
		}
	}
	if pending := data.Dict("title_sync"); pending != nil && pending.Truthy("tries") && pending.Str("name") != new {
		echoes = append(echoes, pending.Str("name"))
	}
	if len(echoes) > 0 {
		data.Set("title_superseded", modelList(slices.Compact(slices.Sorted(slices.Values(echoes)))))
	} else {
		data.Delete("title_superseded")
	}
	if conversation != nil {
		data.Set("title_conversation", conversation)
	} else {
		data.Delete("title_conversation")
	}
}

// watch moves the seat's stall record in watch.json, under the lock Rename holds, and tombstones
// both names' generations, so a tick under way can neither restore the old key nor write over the
// moved stop latch.
func (m carry) watch(now time.Time) error {
	return rewrite(m.path("watch.json"), run.Encode, true, func(data *run.Object) bool {
		generations := watched(data)
		if data.Dict("stalls").Has(m.old) {
			data.Dict("stalls").Set(m.new, data.Dict("stalls").Get(m.old))
			data.Dict("stalls").Delete(m.old)
		}
		newest := 0.0
		for _, each := range generations.Keys() {
			at, _ := run.Num(generations.Get(each))
			newest = math.Max(newest, at)
		}
		stamp := math.Max(seconds(now), math.Nextafter(newest, math.Inf(1)))
		generations.Set(m.old, stamp)
		generations.Set(m.new, stamp)
		return true
	})
}

// tell rewrites the seat's bar under its new name with the word it last announced, and every other
// bar, so none shows the old name until a tick; a seat on the person's own server has no bar, and
// one that has announced nothing none yet to rewrite.
func (m carry) tell() {
	file, _ := run.ReadJSON(m.path("seat-" + m.new + ".json"))
	if m.server != tmux.Own() || file == nil || file.Str("word") == "" {
		return
	}
	models, _ := config.Models()
	Seat{Name: m.new, Word: file.Str("word"), reason: file.Str("reason")}.publish(m.state, models, true)
}
