package seat

import (
	"cmp"
	"context"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/adapters"
	"agentkit/internal/agent"
	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/hookfact"
	"agentkit/internal/lifecycle"
	"agentkit/internal/notify"
	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

// sessionStale is how long a seat's record outlives its last sighting (config.SESSION_STALE).
const sessionStale = 7 * 86400

var (
	// launchKeys are what a launch writes about the conversation it owns and the rulebook it hands
	// over (orch.LAUNCH_KEYS and `kept`), which a harness that never started takes back.
	launchKeys = []string{"conversation", "resumable", "id_source", "before", "codex_launch", "codex_history",
		"opencode_launch", "muse_launch", "antigravity_launch", "antigravity_open", "session_title", "title_sync",
		"rulebook_sha", "rulebook_told", "rulebook_read"}
	// cleared are what a seat launched under its name again no longer is, in its seat file: not the
	// stopped one nor the one the owner closed, running none of the work the last one's screen showed
	// and sent back by nothing yet.
	cleared  = []string{"stopped_at", "closed_by_owner", "usage_wait", "usage_refusal", "holds", "stop_nudged"}
	paneName = regexp.MustCompile(`^%[0-9]+$`)
)

// How is what the caller of Reopen has: DryRun only says what would be done, and Terminal is one
// to hand over, without which the seat's way in is said instead.  Detached is a waking with nobody
// at it (orch.resume's): a seat tmux still holds is left as it is, and one whose recorded directory
// is gone refused.  Its dry run says nothing to anyone, only whether Go carries the waking, so it
// leaves Python what the launch would.
type How struct{ DryRun, Terminal, Detached bool }

// A reopening is what a seat comes back as, read from its record.
type reopening struct {
	name, orchestrator, cwd, conversation string
	model                                 config.Model
	opened, held                          bool
	account, line                         string
	still                                 func(string) error
	moving                                *seatMove
}

// Reopen is what `ak orch`, a tick's revival and the menu do to a seat that exists, as Python's
// orch.main, attach and resume decide it: a live one is attached and never touched; a dead pane is
// respawned in place and a gone seat opened again where it ran, each on the conversation its record
// holds, and then attached.  False, before anything is done, where Go does not carry it out; a
// Refusal in Python's words where no seat can come of it.
func Reopen(name string, how How, out, errOut io.Writer) (bool, error) {
	name, record, err := config.ResolveSession(name)
	if err != nil {
		return false, nil
	}
	path, err := config.SessionPath(name)
	if _, there := os.Lstat(path); err != nil || record == nil && there == nil {
		return false, nil
	}
	state := filepath.Join(config.Home(), "state")
	held, exited, known := find(name, record)
	// the first open of a question standing records its pane as a baseline (notify.opened)
	notice := notify.Last(name)
	if !known {
		return false, nil
	}
	if how.Detached {
		cwd, _ := record["cwd"].(string)
		if info, err := os.Stat(cwd); held {
			return true, nil
		} else if err != nil || !info.IsDir() {
			return true, Refusal(fmt.Sprintf("%s: recorded directory is unavailable: %s", name, cmp.Or(cwd, ".")))
		}
	}
	if how.Terminal && !how.DryRun && notice != nil && notice.Get("opened_at") == nil {
		if !held || exited {
			return false, nil
		}
		if carried, err := notify.OpenedQuestion(name, func(current string) string { pane, _ := harnessScreen(current); return pane }); !carried || err != nil {
			return carried, err
		}
	}
	if held && !exited {
		return attachLive(name, how, out, errOut)
	}
	if !held && len(record) == 0 {
		return true, Refusal(fmt.Sprintf("no session %s to resume and no record of one", commandhelp.Quote(name)))
	}
	if record == nil {
		return true, Refusal(fmt.Sprintf("%s does not say which model held %s", path, commandhelp.Quote(name)))
	}
	seat, known := comingBack(state, name, record, held, how.DryRun && !how.Detached)
	if !known {
		return false, nil
	}
	if err := reopenProject(record, how.DryRun); err != nil {
		return true, err
	}
	settled, known, err := seat.relaunch(how.DryRun, out)
	if !known || err != nil || how.DryRun {
		return known, err
	}
	return true, handOver(settled, how, out, errOut)
}

// There is whether `ak orch NAME` means a seat that is there, as Python's orch.main asks: one tmux
// holds, or one only its record holds unless a model named asks for a new seat by that name.  What
// only Reopen can say is left to it.
func There(name string, forced bool) bool {
	current, record, err := config.ResolveSession(name)
	if err != nil {
		return true
	}
	held, _, known := find(name, record)
	return !known || held || !forced && current == name && len(record) > 0
}

// Tidy is whether Python's maintenance would do nothing a seat's open hangs on: no run to reap, no
// side session to close and no seat to forget (orch.reconcile, sweep).  Its stamp, the clock those
// forgettings run by, is the tick's as well, every three minutes, and is left to it.
func Tidy(now time.Time) bool {
	if entries, err := os.ReadDir(run.Runs()); len(entries) > 0 || err != nil && !errors.Is(err, fs.ErrNotExist) {
		return false
	}
	own := tmux.Sessions(tmux.Own())
	state := filepath.Join(config.Home(), "state")
	for _, session := range own {
		_, unrecorded := os.Lstat(filepath.Join(state, "session-"+session.Name+".json"))
		if session.Mark != "1" && unrecorded != nil && sideSession(session.Name) {
			return false
		}
	}
	for _, path := range config.SeatFiles() {
		name, _ := sessionFile(filepath.Base(path))
		record, _ := run.ReadJSON(path)
		if record == nil {
			return false
		}
		if record.Has(config.Renamed) {
			continue
		}
		since := record.Get("exited_since")
		if !slices.ContainsFunc(own, func(session tmux.Session) bool { return session.Name == name }) {
			file, _ := run.ReadJSON(seatFile(name))
			since = record.Get("seen")
			if file != nil && file.Truthy("stopped_at") {
				since = file.Get("stopped_at")
			}
		}
		if at, dated := run.Num(since); dated && 0 < at && at <= seconds(now)-sessionStale {
			return false
		}
	}
	return true
}

// find is the session tmux holds for a seat of that name, and whether all its panes have exited
// (orch.find): one with no mark and no record is a seat only while an agent runs in it.  Not known
// where the seat is on the person's own server, from before ak had its own.
func find(name string, record map[string]any) (held, exited, known bool) {
	named := func(session tmux.Session) bool { return config.Fold(session.Name) == name }
	own := tmux.Sessions(tmux.Own())
	at := slices.IndexFunc(own, named)
	if at < 0 {
		return false, false, !slices.ContainsFunc(tmux.Sessions(tmux.Default), func(session tmux.Session) bool {
			return session.Mark == "1" && named(session)
		})
	}
	if own[at].Mark != "1" && record == nil && agent.Agentless(tmux.Own(), []string{own[at].Name}) {
		return false, false, true
	}
	return true, slices.Contains(tmux.Dead(tmux.Own()), own[at].Name), true
}

// attachLive says where the running seat is and hands it over; a dry run only says.
func attachLive(name string, how How, out, errOut io.Writer) (bool, error) {
	said, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", "="+name+":", "#{session_path}\t#{session_created}")
	path, created, cut := strings.Cut(said, "\t")
	if err != nil || !cut {
		return false, nil
	}
	now := float64(time.Now().Unix())
	began, err := strconv.ParseFloat(created, 64)
	if err != nil {
		began = now
	}
	fmt.Fprintf(out, "orch: attaching to %s in %s (%s old)\n", name, path, span(now-began))
	if how.DryRun {
		return true, nil
	}
	return true, handOver(name, how, out, errOut)
}

// handOver gives the terminal to that seat, or with none to give says how to reach it
// (orch.attach).
func handOver(name string, how How, out, errOut io.Writer) error {
	if how.Terminal {
		return Attach(name, out, errOut)
	}
	return sayWhere(name, out)
}

// comingBack is what the seat comes back as, or false where Go does not carry that out: a record it
// would refuse or reconcile; a conversation only its harness's own evidence or store can name; a
// login the provider does not list; a folder gone; an unnamed seat.
// A launch also leaves Python a harness whose launch Go does not carry, a checkout's git,
// a seat cut off that its relaunch tells so, and queued account moves or editor sends.
func comingBack(state, name string, record map[string]any, held, dryRun bool) (reopening, bool) {
	orchestrator, _ := record["orchestrator"].(string)
	models, err := config.Models()
	model, named := models[orchestrator]
	if err != nil || !named || !selectable(record, models) {
		return reopening{}, false
	}
	model, known := atOwnEfforts(model, orchestrator, record)
	conversation, owned := harness.Owned(model.Harness, record)
	cwd, _ := record["cwd"].(string)
	info, unseen := os.Stat(cwd)
	account, _ := record["account"].(string)
	if !known || !owned || unseen != nil || !info.IsDir() || !listedAccount(model, account) {
		return reopening{}, false
	}
	opened := true
	if conversation != "" {
		if opened, known = harness.Opened(model.Harness, record); !known {
			return reopening{}, false
		}
	}
	if record["unnamed"] != nil {
		return reopening{}, false
	}
	seat := reopening{name: name, orchestrator: orchestrator, cwd: cwd, conversation: conversation, model: model, opened: opened, held: held, account: account}
	if dryRun {
		return seat, true
	}
	file, err := run.ReadJSON(seatFile(name))
	_, opens := harness.Opens(model.Harness)
	_, checkout := os.Lstat(filepath.Join(cwd, ".git"))
	if !opens || checkout == nil || err != nil && !errors.Is(err, fs.ErrNotExist) ||
		!owedReadable(file) || cutOff(name, model.Harness, file) {
		return reopening{}, false
	}
	return seat, true
}

// selectable is whether Python's config._validate_session takes the record's models, each one the
// config runs: workers, none only beside reviewers, and reviewers if it names any, all distinct.
func selectable(record map[string]any, models map[string]config.Model) bool {
	_, reviewed := record["reviewers"]
	for _, role := range []string{"workers", "reviewers"} {
		listed, isList := record[role].([]any)
		if role == "reviewers" && !reviewed {
			continue
		}
		if !isList || len(listed) == 0 && (role != "workers" || !reviewed) {
			return false
		}
		seen := map[string]bool{}
		for _, each := range listed {
			name, _ := each.(string)
			if _, known := models[name]; !known || seen[name] {
				return false
			}
			seen[name] = true
		}
	}
	return true
}

// atOwnEfforts is the model at the efforts the record holds for it (config.at_efforts), else its
// entry's; false where they are none Python reads.
func atOwnEfforts(model config.Model, orchestrator string, record map[string]any) (config.Model, bool) {
	efforts, there := record["efforts"]
	if !there {
		return model, true
	}
	table, isTable := efforts.(map[string]any)
	if !isTable {
		return model, false
	}
	for _, each := range table {
		held, _ := each.(map[string]any)
		if _, worded := held["effort"].(string); !worded {
			return model, false
		}
	}
	if own, held := table[orchestrator].(map[string]any); held {
		model.Efforts = map[string]string{}
		for key, value := range own {
			if word, isWord := value.(string); isWord {
				model.Efforts[key] = word
			}
		}
	}
	return model, true
}

// cutOff is whether the seat's end may have cut off something its relaunch has to tell it
// (watch.cut_off): it asked, was in a turn or held work, by its last hook's word or its last look,
// that hook's where it spoke since the look, as it is then the newest word.  One the owner closed
// or stopped ended on purpose.
func cutOff(name, own string, file *run.Object) bool {
	if file != nil && (file.Truthy("stopped_at") || file.Truthy("closed_by_owner")) {
		return false
	}
	fact := harness.For(own).HookFact(name)
	hooked, _, err := lifecycle.State(own, fact)
	if err != nil || notify.Standing(name) || len(hookfact.Standing(name).Holds) > 0 || hooked == "asking" || hooked == "working" {
		return true
	}
	if file == nil || file.Truthy("holds") {
		return file != nil
	}
	if hooked != "" && fact.At != 0 && fact.At != at(file.Get("hooked_at")) {
		return false
	}
	return file.Str("state") == "asking" || file.Str("state") == "working" ||
		file.Str("hooked") == "working" || file.Str("rule") == "none" && !continuationQueued(file)
}

// command is the seat's line and the conversation it owns on it (orch.resume, resume_command): the
// one its record holds, or one a new launch can be told, "" for none.  told is what else its adapter
// is told: the rulebook written for it.  False where none opens, a seat its adapter refuses too:
// Python's resume says why.
func (seat reopening) command(told []string) ([]string, string, bool) {
	env := slices.Concat(os.Environ(), []string{"AGENTKIT_SESSION=" + seat.name, "AGENTKIT_FIRST_PROMPT=" + seat.line, "AGENTKIT_ACCOUNT=" + seat.account}, told)
	if seat.moving != nil {
		env = append(env, "AGENTKIT_FIRST_PROMPT="+seat.moving.line)
	}
	if seat.conversation == "" {
		cmd, conversation, _ := adapters.Fresh(seat.model, env, seat.cwd)
		return cmd, conversation, cmd != nil
	}
	cmd, _ := adapters.Resumed(seat.model, seat.conversation, seat.opened, env, seat.cwd)
	return cmd, seat.conversation, cmd != nil
}

// said is what the seat is told to be doing, as orch.resume logs it.
func (seat reopening) said() string {
	where := "in " + seat.cwd
	if seat.held {
		where = "in the same window"
	}
	what := harness.FreshWords(seat.model.Harness)
	if seat.conversation != "" {
		what = "conversation " + seat.conversation
	}
	return fmt.Sprintf("orch: resuming %s on %s %s (%s)", seat.name, seat.orchestrator, where, what)
}

// launch puts the harness in the seat and writes down what it was launched with, as orch.launch
// does, all under the seat's lock, so a rename going on keeps its record: the rulebook then on disk,
// the hook facts the last harness left moved aside, then moved and linked back rather than
// rewritten, as its hooks publish by rename.  A harness that never started leaves the record and
// the facts as they were.  The name is the one the seat goes by now.
func (seat reopening) launch(state, rulebook string, cmd []string, conversation string) (string, error) {
	titled, _ := harness.Opens(seat.model.Harness)
	var settled string
	err := notify.Held(context.Background(), seat.name, func(current string) error {
		settled = current
		var frozen *frozenPane
		if seat.still != nil {
			var err error
			if frozen, err = freezePane(current); err != nil {
				return err
			}
			defer frozen.thaw()
			if err := seat.still(current); err != nil {
				return err
			}
		}
		perform := func() error {
			var before *run.Object
			var issued *run.Object
			var extra []string
			var preparing error
			facts := filepath.Join(state, "hook-"+current+".json")
			last := facts + ".last"
			defer os.Remove(last)
			handed := any(nil)
			if read, err := os.ReadFile(rulebook); err == nil {
				handed = digest(read)
			}
			// before the harness is up: its first prompt may be offered a newer rulebook already
			started, err := false, update(state, current, func(data *run.Object) bool {
				before = data.Copy()
				issued, extra, preparing = harness.Launched(seat.model.Harness, seat.cwd, conversation, before)
				if preparing != nil {
					return false
				}
				for _, key := range issued.Keys() {
					fill(data, []field{{key, issued.Get(key)}})
				}
				fill(data, []field{{"rulebook_sha", handed}, {"rulebook_told", nil}, {"rulebook_read", nil}})
				return true
			})
			if err == nil {
				err = preparing
			}
			if err == nil {
				if err = os.Rename(facts, last); errors.Is(err, fs.ErrNotExist) {
					err = os.Remove(last) // a launch killed past its move left one
					if errors.Is(err, fs.ErrNotExist) {
						err = nil
					}
				}
			}
			if err == nil {
				err = retypeOwed(current)
			}
			if err == nil {
				if len(extra) > 0 {
					cmd = slices.Concat([]string{"env"}, extra, cmd)
				}
				started, err = seat.start(state, current, cmd, frozen)
			}
			if err != nil {
				if !started {
					harness.Retire(seat.model.Harness, issued)
					if before != nil { // nil where the record took nothing
						update(state, current, func(data *run.Object) bool {
							for _, key := range launchKeys {
								fill(data, []field{{key, before.Get(key)}})
							}
							return true
						})
					}
					os.Link(last, facts) // refused where that harness wrote one since
				} else {
					harness.Retire(seat.model.Harness, before)
				}
				return err
			}
			if before == nil { // no record left to write it down in, as config.update_session leaves it
				before = run.NewObject()
			}
			if err := harness.Retire(seat.model.Harness, before); err != nil {
				return err
			}
			now := time.Now()
			// the moment from which an answer is this harness's, and the seat's title as Python's
			// launch keeps it: both harnesses Go opens take a title line
			if err := update(state, current, func(data *run.Object) bool {
				fill(data, []field{{"launched", seconds(now)}, {"title_sync", nil}})
				if seat.account != "" {
					data.Set("account", seat.account)
				}
				echo := before.Str("session_title")
				if conversation == "" || before.Str("conversation") != conversation || echo == "" || echo == current {
					title := any(nil)
					if titled {
						title = current
					}
					fill(data, []field{{"session_title", title}})
				}
				return true
			}); err != nil {
				return err
			}
			if err := retireSwitchLines(current); err != nil {
				return err
			}
			var fields []field
			for _, key := range cleared {
				fields = append(fields, field{key, nil})
			}
			return writeSeat(state, current, fields)
		}
		if seat.moving != nil {
			if err := seat.moving.launch(state, current, perform); err != nil {
				return err
			}
			return seat.moving.relaunched(current, seat.model.Harness)
		}
		return perform()
	})
	return settled, err
}

// fill merges fields into a record as config.update_session does: a nil one is removed.
func fill(data *run.Object, fields []field) {
	for _, f := range fields {
		if f.value == nil {
			data.Delete(f.key)
		} else {
			data.Set(f.key, f.value)
		}
	}
}

// start is the harness in the seat, respawned in its exited pane or a new session, and whether it
// runs: what fails after that leaves it be.
func (seat reopening) start(state, name string, cmd []string, frozen *frozenPane) (bool, error) {
	if !seat.held {
		return false, start(state, name, seat.cwd, cmd)
	}
	server := tmux.Own()
	target := harnessPane(name)
	if frozen != nil {
		target = frozen.target
	}
	values, err := environment(name, server)
	if err != nil {
		return false, err
	}
	shims, err := shims()
	if err != nil {
		return false, err
	}
	command, launch, err := launchFile(state, name, values, cmd)
	if err != nil {
		return false, err
	}
	// one command list: a failed respawn keeps the old terminal's name, and a new wrapper's client
	// cannot publish its own before the old one is gone
	args := slices.Concat([]string{"respawn-pane", "-k", "-t", target}, paneEnvironment(values), []string{command, ";", "set-option", "-pu", "-t", target, tmux.InputTTY})
	if err := tmux.Spawn(server, shims+string(os.PathListSeparator)+os.Getenv("PATH"), frozen.guarded(args)...); err != nil {
		os.Remove(launch)
		return false, Refusal(fmt.Sprintf("cannot resume the session %s: %v", name, err))
	}
	// a refused respawn leaves the old harness up: only now do later panes take this one's home
	kept := append(keptEnvironment("="+name+":", values), ";", "set-option", "-F", "-t", target, tmux.HarnessPane, "#{pane_id}")
	if _, err := tmux.Ask(server, kept[1:]...); err != nil {
		return true, Refusal(fmt.Sprintf("cannot set up the session %s: %v", name, err))
	}
	return true, nil
}

// harnessPane is the pane the seat's launch created, even with another window active; if it was
// removed, the session's current pane (orch.harness_pane).
func harnessPane(name string) string {
	session := "=" + name + ":"
	pane, err := tmux.Ask(tmux.Own(), "show-options", "-qv", "-t", session, tmux.HarnessPane)
	if err == nil && paneName.MatchString(pane) {
		if owner, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", pane, "#{session_name}"); err == nil && owner == name {
			return pane
		}
	}
	return session
}
